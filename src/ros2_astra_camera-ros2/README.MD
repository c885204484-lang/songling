# OpenNI2 SDK for ROS2

ROS2 Wrapper for Orbbec RGB-D Astra Cameras.
Tested with ROS2-Humble (Ubuntu 22.04)

## Dependencies
    sudo apt install ros-humble-magic-enum 
    sudo apt install libuvc-dev

## UDEV rules
In order for the launch files to work, udev rules must be in place and working.
Under the "scripts" folder, run the "install.sh" that will copy the rules "56-orbbec-usb.rules" into the "/etc/udev/rules.d" folder for you, or do it manually.
Once the rules are copied, either restart your computer or execute the following command:

    sudo udevadm control --reload-rules && sudo udevadm trigger
