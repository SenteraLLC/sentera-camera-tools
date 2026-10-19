#!/usr/bin/env python
import sys
import websocket
import json
from dataclasses import dataclass
import argparse
import threading

from websocket import WebSocket
from time import sleep

parser = argparse.ArgumentParser()
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="Enable input and output ROS message printing during runtime"
)
args = parser.parse_args()

class CameraConn:
    '''
    Class representing a websocket connection to a Sentera camera to allow for communication
    to the onboard ROS system to perform a specific set of functions to allow for 
    some aid to users in integrating a camera into their platform
    '''

    @dataclass
    class BandInfo:
        id:int = 0
        type: str = ""
        band_cwl: int = 0
        band_fwhm: int = 0

    ip:str = "192.168.42.1"
    session_name:str = ""
    ws_connected:bool = False
    in_session:bool = False
    message_id:int = 20
    help_spacing:int = 32
    verbose_mode: bool = False
    camera_info: dict = {}

    def __init__(self, verbose_mode: bool):
        self.verbose_mode = verbose_mode
        self.connectToCamera()
        self._setCameraInfo()
        self.in_session = self.checkIfSessionActive()

    @property
    def connected(self) -> bool:
        '''Catching unexpected ws drops after start of connection'''
        return self.ws.connected

    @property
    def session_running(self) -> bool:
        '''Checks for camera's status on whether or not it has a capture session in progress'''
        return (self.connected and self.in_session)

    def _setCameraInfo(self) -> None:
        '''
        Private helper function to set camera information

        Parameters:
        camera_info (dict): dictionary containing camera information to be set
        '''
        set_camera_info_msg = self._createRosCallServiceMessage(
            "/get_camera_info",
            "custom_srvs/srv/SetCameraInfo",
            {}
        )
        self.ws.send(set_camera_info_msg)

        result = self.readFromWs()
        while result.get("service") != "/get_camera_info":            
            result = self.readFromWs()
        self._setBandInfo(result)

    def _setBandInfo(self, result: dict) -> None:
        '''
        Private helper function to set the band information for each imager in the camera info.

        Parameters:
        result (dict): dictionary containing the camera info retrieved from the camera
        '''
        for imager in result["values"]["imagers"]:
            new_band = self.BandInfo()
            band_name = ""
            if imager["type"] == "RGB":
                new_band.type = imager["type"]
                band_name = "rgb"
            else:
                new_band.id = imager["imager_rig_id"]
                new_band.type = "Mono"
                band_name = imager["band_name"][0]
                new_band.band_cwl = imager["band_cwl"][0]
                new_band.band_fwhm = imager["band_fwhm"][0]
            self.camera_info[band_name] = new_band

    def _createMessage(self, op: str, **payload) -> str:
        '''
        Private helper function to create ROS messages to send over the camera's websocket
        
        Parameters:
        op (str): operation or ROS message type. [ subscribe | advertise | publish ]
        payload (dict): rest of the body for a ROS message with varying content
        
        Returns:
        str: string formatted version of the payload for a ROS message
        '''
        msg:str = json.dumps({"op": op, **payload})
        if self.verbose_mode:
            print(f"message sent: {msg}")
        return msg

    def _createTopicMessage(self, op: str, topic: str, msg_type: str, queue_len: int) -> str:
        '''
        Private helper function to create either a subscription or advertisement ROS message
        as these message types have very similar payloads

        Parameters:
        op (str): operation or ROS message type. [ subscribe | advertise ]
        topic (str): ROS topic to either advertise a message about or receive data from
        msg_type (str): ROS message type to recieve as expected response
        queue_len (int): maximum amout of stored messages of this type

        Returns:
        str: Result of _createMessage
        '''
        return self._createMessage(
            op,
            id=f"{op}:/{topic}:{self.message_id}",
            type=msg_type,
            topic=f"/{topic}",
            latch=False,
            queue_size=queue_len,
        )

    def _createRosSubscribeMessage(self, topic: str, msg_type: str, queue_len: int) -> str:
        '''create a subscription message using the _createTopicMessage helper function'''
        return self._createTopicMessage("subscribe", topic, msg_type, queue_len)

    def _createRosAdvertiseMessage(self, topic: str, msg_type: str, queue_len: int) -> str:
        '''create a advertisement message using the _createTopicMessage helper function'''
        return self._createTopicMessage("advertise", topic, msg_type, queue_len)

    def _createRosCallServiceMessage(self, service: str, service_type: str, args: dict) -> str:
        '''
        Create a call_service ROS message using the _createMessage helper function

        Parameters:
        service (str): ROS service to reach out to for state information
        service_type (str): type of message shape this service responses with
        args (dict): json data sent over to specified service

        Returns:
        str: Result of _createMessage
        '''
        self.message_id += 1
        return self._createMessage(
            "call_service",
            id=f"call_service:{service}:{self.message_id}",
            service=service,
            type=service_type,
            args=args,
        )

    def _createRosPublishMessage(self, topic: str, msg: dict) -> str:
        '''
        Create a publish ROS message using the _createMessage helper function

        Parameters:
        topic (str): topic desired to be published to other subscribers on the camera
        msg (dict): json data sent over to subscribers of this topic

        Returns:
        str: result of _createMessage
        '''
        self.message_id += 1
        return self._createMessage(
            "publish",
            id=f"publish:/{topic}:{self.message_id}",
            topic=f"/{topic}",
            msg=msg,
            latch=False,
        )

    def _createConnection(self, ip: str) -> WebSocket:
        '''Connected to ROS on camera over websocket on port 9090'''
        return websocket.create_connection(f"ws://{ip}:9090", timeout=5)

    def connectToCamera(self):
        '''
        Attempt to connect to the camera's ROS websocket, if the default USB IP address fails,
        the user will be prompted to supply a new ip address and a new connection will be attempted
        '''
        while True:
            try: 
                self.ws = self._createConnection(self.ip)
                self.ws_connected = True
                break
            except TimeoutError:
                print(f"Timeout connecting to {self.ip}, retrying...")
                continue
        print(f"Connected to {self.ip}")

    def closeConnection(self):
        '''
        Properly close the websocket connection and reset state
        '''
        self.ws.close()
        self.in_session = False
        self.ws_connected = False
        print("Connection closed")

    def readFromWs(self) -> dict:
        '''
        Attempt to read any ROS messages that have been subscribed to so far by this script

        Does not return anything until a message has been recieved

        Returns:
        str: first valid message recieved while waiting to hear from the ROS websocket
        '''
        while True:
            try:
                msg: dict = json.loads(self.ws.recv())
                if self.verbose_mode:
                    print(f"message recieved: {msg}")
                return msg
            except (websocket._exceptions.WebSocketTimeoutException, ValueError) as e:
                print(e)
                continue

    def sendSessionStatusSub(self):
        '''helper function to send a ROS subscription messsage to recieve the state of the camera's capture session'''
        adver = self._createRosSubscribeMessage("topic_session_status", "custom_msgs/SessionStatus", 0)
        self.ws.send(adver)
        
    def connectToSession(self):
        '''
        Checks to see if the camera is already running a a capture session and sets the in_session attribute accordingly
        by sending a subscription message and waiting to read the first response of that message type
        '''
        self.sendSessionStatusSub()

        result:dict = self.readFromWs()
        while result.get("topic") !="/topic_session_status" or result.get('msg') == None or not result["msg"]["active"]:
            result = self.readFromWs()
            sleep(0.5)

        self.session_name = result["msg"]["name"] 
        print(f"Connected to active session: {self.session_name}")
        self._printSessionLocation()
        self.in_session = True

    def startSession(self, command_args: list[str]):
        '''
        Called from command line to start a capture session on the camera if one is not already running

        This is done by creating an advertisement publish message to be sent over to the camera with the
        response then waited on by a call to connectToSession to verify the new session has started

        Parameters:
        command_args (list[str]): name of the session supplied by the user split by spaces
        '''
        if self.in_session:
            print("Already connected to active session")
        elif command_args == []:
            print("Please enter a session name with start command")
        else:
            self.session_name = " ".join(command_args)

        if self.session_name == "":
            return

        adver = self._createRosAdvertiseMessage("topic_session_start", "custom_msgs/SessionStart", 100)
        message = self._createRosPublishMessage(
            "topic_session_start",
            {"name": self.session_name, "unix_epoch_ns": 0}
        )

        self.ws.send(adver)
        self.ws.send(message)
        print("Starting Session (this may take a few seconds)...")
        self.connectToSession()

    def captureImage(self):
        '''
        Command from user to tell the camera to capture an image
        
        An advertisement and publish ROS message are created to send the command to capture an image
        '''
        adver = self._createRosAdvertiseMessage("topic_image_trigger", "custom_msgs/ImageTrigger", 100)
        message = self._createRosPublishMessage(
            "topic_image_trigger",
            {
                "header": {
                    "frame_id": "external_cmd",
                    "stamp": {"sec": 0, "nanosec": 0}
                }
            }
        )

        self.ws.send(adver)
        self.ws.send(message)
        print("capturing image")

    def calibrate(self):
        '''
        Command from user to start a calibration session on the camera
        
        A subscription and call_service ROS message are sent to tell the camera to start the calibration process
        '''
        calibrate_sub = self._createRosSubscribeMessage("imagers/exp_sweep/_action/status", "action_msgs/msg/GoalStatusArray", 100)
        self.ws.send(calibrate_sub)

        message = self._createRosCallServiceMessage("/imagers/exp_sweep_svc", "std_srvs/srv/Trigger", {})
        self.ws.send(message)
        print("Calibration Capture Started")

    def _printSessionLocation(self):
        '''
        Prints the location of the current session based on the session name.
        '''
        print(f"Session storage locations for session: {self.session_name}")
        for band_name, band_info in self.camera_info.items():
            if band_name != "rgb":
                print(f"/data/snapshots/{self.session_name}/{band_info.id}-{band_name}-{band_info.band_cwl}-{band_info.band_fwhm}/")
            else:
                print(f"/data/snapshots/{self.session_name}/{band_name}/")

    def _printNewImageLoc(self, capture_id: int):
        '''
        Prints the location of a newly captured image based on its capture ID.

        Args:
        capture_id (int): The ID of the captured image
        '''
        print("new image location for capture ID:", capture_id)
        for band_name, band_info in self.camera_info.items():
            if band_name != "rgb":
                print(f"/data/snapshots/{self.session_name}/{band_info.id}-{band_name}-{band_info.band_cwl}-{band_info.band_fwhm}/IMG_{str(capture_id).rjust(4, '0')}.tif")
            else:
                print(f"/data/snapshots/{self.session_name}/{band_name}/IMG_{str(capture_id).rjust(4, '0')}.jpg")

    def _listenForCaptureEvents(self, t_event: threading.Event):
        '''
        Listens for capture events from the camera and prints the total number of images captured.

        Args:
        t_event (threading.Event): Event to signal when to stop listening for capture events
        '''
        total_images_captured:int = 0
        while not t_event.is_set():
            msg: dict = self.readFromWs()
            if msg.get("topic") == "/topic_image_captured" and msg["msg"]["total_requests"] > total_images_captured:
                total_images_captured = msg["msg"]["total_requests"]
                print(f"Image captured\nTotal images captured: {total_images_captured}")
            if msg.get("topic") == "/topic_image_stored":
                capture_id:int = msg["msg"]["id"] + 1
                self._printNewImageLoc(capture_id)

    def listenCapture(self):
        '''
        Command from user to start listening for capture events from the camera
        
        A subscription ROS message is created to listen for capture events
        '''
        print("Listening for capture events. Type 'q' to stop. Type 'c' to capture an image.")
        image_captured_sub = self._createRosSubscribeMessage("topic_image_captured", "custom_msgs/ImageCaptured", 0)
        self.ws.send(image_captured_sub)
        image_stored_sub = self._createRosSubscribeMessage("topic_image_stored", "custom_msgs/ImageStored", 0)
        self.ws.send(image_stored_sub)
        usr_input:str = ""
        t_event = threading.Event()
        thread = threading.Thread(target=self._listenForCaptureEvents, args=(t_event,))
        thread.start()
        while usr_input.casefold() != "q":
            usr_input = input().strip()
            if usr_input.casefold() == "c":
                self.captureImage()
        t_event.set()
        thread.join()
        print("Stopped listening for capture events")

    def toggleVerbose(self):
        '''Flips on and off verbose mode to choose to see the incoming and outgoing ROS messages printed to the user'''
        self.verbose_mode = not self.verbose_mode
        print(f"verbose mode: {self.verbose_mode}")

    def checkIfSessionActive(self):
        '''
        Checks to see if a capture session is already running on the camera
        
        Returns:
        bool: active state of a capture session
        '''
        self.sendSessionStatusSub()
        result = self.readFromWs()
        retries = 2
        session_status = False
        while result.get("topic") != "/topic_session_status" and retries > 0:
            result = self.readFromWs()
            retries-=1

        if retries == 0:
            return session_status

        session_status = result["msg"]["active"]
        if session_status:
            self.session_name = result['msg']['name']
            self._printSessionLocation()
        else:
            print("No active session found on camera please start a session. Command: start <session_name>")
        return session_status

    def printHelp(self):
        '''Prints available commands to screen'''
        print()
        print(f'{"start <session_name>":<{self.help_spacing}} Begins a new session with name <session_name>')
        print(f'{"capture":<{self.help_spacing}} Triggers an image capture event')
        print(f'{"cal":<{self.help_spacing}} Starts a calibration capture')
        print(f'{"listen_capture":<{self.help_spacing}} Listens for capture events and prints them to the console')
        print(f'{"verbose":<{self.help_spacing}} Toggle verbose mode to choose to view camera messages')
        print(f'{"exit":<{self.help_spacing}} Closes current connection and exits program')
        print()


# Print tool header and starting prompt.
print("ROS Camera Control app started")
camera_conn = CameraConn(args.verbose)

# Execute commands until 'exit' command.
while True:
    command = input(">> ").strip()
    command_tokens = []

    if command != "":
        command_tokens = [token.casefold() for token in command.split(" ")]
        command = command_tokens[0]
        command_arg = command_tokens[1] if len(command_tokens) > 1 else ""
        print("")
    else:
        print("")
        continue

    if command == "help" or command == "man":
        camera_conn.printHelp()
    elif command == "start":
        camera_conn.startSession(command_tokens[1:])
    elif command == "capture":
        camera_conn.captureImage() if camera_conn.session_running else print("Not connected to a session. Please start or connect to session.")
    elif command == "cal":
        camera_conn.calibrate() if camera_conn.session_running else print("Not connected to a session. Please start or connect to session.")
    elif command == "listen_capture":
        camera_conn.listenCapture() if camera_conn.session_running else print("Not connected to a session. Please start or connect to session.")
    elif command == "verbose":
        camera_conn.toggleVerbose()
    elif command == "exit":
        if camera_conn.connected:
            camera_conn.closeConnection()
        sys.exit(0)
    else:
       print("Invalid command entered - see 'help' for list of commands")
