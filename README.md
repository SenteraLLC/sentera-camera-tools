# 6x-tools-public
## Applications
/test-api/

└── 6x_control.py

###  6x_control.py
A command line application to allow for testing the core functionality of a 6X camera:
- Connect to the camera
- Start a capture session
- Capture an image
- Calibrate the camera's image tuning
- Toggle verbose mode to choose to see incoming and outgoing camera messages
  - This can be set with -v when starting the program or, while running the program,
  with a "verbose" command
