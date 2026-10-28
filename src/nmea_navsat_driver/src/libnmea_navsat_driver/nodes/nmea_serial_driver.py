# Software License Agreement (BSD License)
#
# Copyright (c) 2013, Eric Perko
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * Neither the names of the authors nor the names of their
#    affiliated organizations may be used to endorse or promote products derived
#    from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import serial

import rclpy

from libnmea_navsat_driver.driver import Ros2NMEADriver
from libnmea_navsat_driver.serial_buffer import NMEABuffer


def main(args=None):
    rclpy.init(args=args)

    driver = Ros2NMEADriver()
    frame_id = driver.get_frame_id()

    serial_port = driver.declare_parameter('port', '/dev/ttyACM0').value
    serial_baud = driver.declare_parameter('baud', 115200).value

    try:
        GPS = serial.Serial(port=serial_port, baudrate=serial_baud, timeout=.2)
        driver.get_logger().info("Successfully connected to {0} at {1}.".format(serial_port, serial_baud))
        buffer = NMEABuffer()
        try:
            while rclpy.ok():
                # readline() reads byte by byte in pyserial. A high-rate GNSS
                # stream can accumulate seconds of stale measurements while
                # every ROS header still receives the current wall-clock time.
                data = GPS.read(min(65536, max(1, GPS.in_waiting)))
                waiting = min(GPS.in_waiting, 65536 - len(data))
                if waiting:
                    data += GPS.read(waiting)
                for sentence in buffer.feed(data):
                    try:
                        driver.add_sentence(sentence, frame_id)
                    except ValueError as e:
                        driver.get_logger().warn(
                            "Value error, likely due to missing fields in the NMEA message. message was: %s. " % e)

        except Exception as e:
            driver.get_logger().error("Ros error: {0}".format(e))
            GPS.close()  # Close GPS serial port
    except serial.SerialException as ex:
        driver.get_logger().fatal("Could not open serial port: I/O error({0}): {1}".format(ex.errno, ex.strerror))
