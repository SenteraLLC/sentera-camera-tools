# Test API Scripts

This directory collects scripts and examples that help customers and integrators explore Sentera camera APIs and integrate camera functionality into their projects. Each entry below summarizes the script's purpose and quick-start requirements; add a new entry here as additional test APIs are added.

## Available test APIs

| Script | Purpose | Requirements / notes |
| --- | --- | --- |
| [`6x_control.py`](6x_control.py) | Interactive 6X camera control example. Connects to the camera's ROS bridge over WebSocket and demonstrates topic subscriptions, advertisements and publishing, service calls, capture sessions, image capture, and calibration. | Python 3, `websocket-client`, and network access to the camera's bridge on port `9090`. Defaults to `ws://192.168.42.1:9090`. |

## Quick start: 6X control

Run from the repository root:

```sh
python -m pip install websocket-client
python test-api/6x_control.py
```

Use `python test-api/6x_control.py --verbose` to log raw JSON traffic. To connect to a camera at another IP address, update the default IP in the script. At the interactive prompt, `help` lists commands such as `start`, `capture`, `cal`, `listen_capture`, `verbose`, and `exit`.

The example prints session and image-storage locations in a human-readable form. Verbose mode shows the underlying ROS bridge messages and responses. See the script for implementation details; camera-specific topics, message types, and service names must match the interfaces supported by the target camera.
