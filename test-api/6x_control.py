#!/usr/bin/env python
import sys
import websocket
import json
import time

from websocket import WebSocket
from time import sleep


class CameraConn:

    ip:str = "192.168.42.1"
    ws_connected:bool = False
    in_session:bool = False
    message_id:int = 20
    help_spacing:int = 32

    def __init__(self):
        self.connectToCamera()
        self.in_session = self.checkIfSessionActive()

    @property
    def connected(self) -> bool:
        # catching unexpected ws drops after start of connection
        return (self.ws_connected and self.ws.connected)

    @property
    def session_running(self) -> bool:
        return (self.connected and self.in_session)

    def _createMessage(self, op: str, **payload) -> str:
        return json.dumps({"op": op, **payload})

    def _createTopicMessage(self, op: str, topic: str, msg_type: str, queue_len: int) -> str:
        return self._createMessage(
            op,
            id=f"{op}:/{topic}:{self.message_id}",
            type=msg_type,
            topic=f"/{topic}",
            latch=False,
            queue_size=queue_len,
        )

    def _createSubscribeMessage(self, topic: str, msg_type: str, queue_len: int) -> str:
        return self._createTopicMessage("subscribe", topic, msg_type, queue_len)

    def _createAdvertiseMessage(self, topic: str, msg_type: str, queue_len: int) -> str:
        return self._createTopicMessage("advertise", topic, msg_type, queue_len)

    def _createRosCallServiceMessage(self, service: str, service_type: str, args: dict) -> str:
        self.message_id += 1
        return self._createMessage(
            "call_service",
            id=f"call_service:{service}:{self.message_id}",
            service=service,
            type=service_type,
            args=args,
        )

    def _createRosPublishMessage(self, topic: str, msg: dict) -> str:
        self.message_id += 1
        return self._createMessage(
            "publish",
            id=f"publish:/{topic}:{self.message_id}",
            topic=f"/{topic}",
            msg=msg,
            latch=False,
        )

    def _createConnection(self, ip: str) -> WebSocket:
        return websocket.create_connection(f"ws://{ip}:9090", timeout=5)

    def connectToCamera(self):
        while True:
            try: 
                self.ws = self._createConnection(self.ip)
                self.ws_connected = True
                break
            except TimeoutError:
                ip = input(f"could not connect to {self.ip}\nPlease enter a new ip.\n>>")
                self.ip = ip
        print(f"Connected to {self.ip}")

    def closeConnection(self):
        self.ws.close()
        self.in_session = False
        self.ws_connected = False
        print("Connection closed")

    def readFromWs(self) -> dict:
        while True:
            try:
                return json.loads(self.ws.recv())
            except (websocket._exceptions.WebSocketTimeoutException, ValueError):
                continue

    def sendSessionStatusSub(self):
        adver = self._createAdvertiseMessage("topic_session_status", "custom_msgs/SessionStatus", 0)
        self.ws.send(adver)
        
    def connectToSession(self):
        self.sendSessionStatusSub()

        result:dict = self.readFromWs()
        while result.get("topic") !="/topic_session_status" or result.get('msg') == None or not result["msg"]["active"]:
            result = self.readFromWs()
            sleep(0.5)

        session_name = result["msg"]["name"] 
        print(f"Connected to active session: {session_name}")
        self.in_session = True

    def startSession(self, command_args: list[str]):
        session_name = ""
        if camera_conn.in_session:
            print("Already connected to active session")
        elif command_arg == "":
            print("Please enter a session name with start command")
        else:
            session_name = " ".join(command_args)

        if session_name == "":
            return

        adver = self._createAdvertiseMessage("topic_session_start", "custom_msgs/SessionStart", 100)
        message = self._createRosPublishMessage(
            "topic_session_start",
            {"name": session_name, "unix_epoch_ns": 0}
        )

        self.ws.send(adver)
        self.ws.send(message)
        print("Starting Session (this may take a few seconds)...")
        self.connectToSession()

    def checkForCapture(self):
        image_captured_sub = self._createSubscribeMessage("topic_image_captured", "custom_msgs/ImageCaptured", 0)
        self.ws.send(image_captured_sub)

        result = self.readFromWs()
        while result.get("topic") != "/topic_image_captured" or result.get("msg") == None:
            result = self.readFromWs()
        print(result)

    def captureImage(self):
        adver = self._createAdvertiseMessage("topic_image_trigger", "custom_msgs/ImageTrigger", 100)
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
        self.checkForCapture()
        print("captured image")

    def calibrate(self):
        calibrate_sub = self._createSubscribeMessage("imagers/exp_sweep/_action/status", "action_msgs/msg/GoalStatusArray", 100)
        self.ws.send(calibrate_sub)

        message = self._createRosCallServiceMessage("/imagers/exp_sweep_svc", "std_srvs/srv/Trigger", {})
        self.ws.send(message)
        print("Calibration Capture Started")

    def validateGimbalAngle(self, pitch_deg: str) -> float:
        pitch_deg_int:float = 361.0
        try:
            pitch_deg_int = float(pitch_deg)
        except (ValueError, TypeError):
            print(f"invalid pitch of {pitch_deg} given")
        return pitch_deg_int

    def gimbalAngleApply(self, pitch_deg: str):
        pitch_degree_float = self.validateGimbalAngle(pitch_deg)
        if pitch_degree_float == 361.0:
            return

        adver = self._createAdvertiseMessage("topic_gimbal_angle_apply", "custom_msgs/GimbalAngleApply", 100)
        message = self._createRosPublishMessage(
            "topic_gimbal_angle_apply",
            {
                "header":{
                    "frame_id":"external_cmd", "stamp":{"sec":0, "nanosec":0}
                },
                "pitch_deg": pitch_degree_float,
                "roll_deg":0.0,
                "yaw_deg":0.0,
                "pitch_apply":True,
                "roll_apply":False,
                "yaw_apply":False
            }
        )
        self.ws.send(adver)
        self.ws.send(message)
        print("Gimbal Angle Set")

    def getTime(self):
        message = self._createRosCallServiceMessage(
            "get_time",
            "custom_srvs/srv/GetTime",
            {"src_time1_ns": 0, "src_time2_ns": 0}
        )
        self.ws.send(message)
        # Wait for the service response for up to 5 seconds
        end_time = time.time() + 5
        while time.time() < end_time:
            result = self.readFromWs()
            if result.get('op') == "service_response" and result.get('service') == "/get_time":
                get_time_val:dict = result['values']
                # print the returned timestamps
                print("Camera Times:")
                print("  - FPGA (ns): ", get_time_val['fpag_time_ns'])
                print("  - Sys (us): ", get_time_val['sys_time_us'])
                print("  - ROS: ", get_time_val['ros_time'])
                break

    def checkIfSessionActive(self):
        self.sendSessionStatusSub()
        result = self.readFromWs()
        retries = 2
        while result.get("topic") != "/topic_session_status" and retries > 0:
            result = self.readFromWs()
            retries-=1

        return result["msg"]["active"]

    def printHelp(self):
        print()
        print(f'{"start <session_name>":<{self.help_spacing}} Begins a new session with name <session_name>')
        print(f'{"capture":<{self.help_spacing}} Triggers an image capture event')
        print(f'{"status":<{self.help_spacing}} State of connection')
        print(f'{"cal":<{self.help_spacing}} Starts a calibration capture')
        print(f'{"gimbal-angle <tilt_degrees>":<{self.help_spacing}} Control the gimbal tilt')
        print(f'{"get-time":<{self.help_spacing}} Get camera time')
        print(f'{"close":<{self.help_spacing}} Closes current connection')
        print(f'{"exit":<{self.help_spacing}} Closes current connection and exits program')
        print()


# Print tool header and starting prompt.
print("6X Camera Control (v1.3)")
camera_conn = CameraConn()

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
    elif command == "connect":
        camera_conn.connectToCamera() if not camera_conn.connected else print("already connected to camera")
    elif command == "capture":
        camera_conn.captureImage() if camera_conn.session_running else print("Not connected to a session. Please start or connect to session.")
    elif command == "status":
        print("Connection open") if camera_conn.connected else print("Connection closed")
    elif command == "cal":
        camera_conn.calibrate() if camera_conn.session_running else print("Not connected to a session. Please start or connect to session.")
    elif command == "gimbal-angle":
        camera_conn.gimbalAngleApply(command_arg)
    elif command == "get-time":
        camera_conn.getTime()
    elif command == "close":
        camera_conn.closeConnection() if camera_conn.connected else print("No connections open")
    elif command == "exit":
        if camera_conn.connected:
            camera_conn.closeConnection()
        sys.exit(0)
    else:
       print("Invalid command entered - see 'help' for list of commands")
