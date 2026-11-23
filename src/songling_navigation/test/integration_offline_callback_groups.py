"""Verify sensor receipt during a slow control callback on an isolated ROS domain."""

import json
import os
import threading
import time
from types import SimpleNamespace

import rclpy
from hunter_msgs.msg import HunterStatus
from nav_msgs.msg import Odometry
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node

from songling_navigation.offline_nav.ros_bridge import NavigationBridge


def main():
    assert int(os.environ.get('ROS_DOMAIN_ID', '0')) != 0, 'Use an isolated ROS domain'
    rclpy.init(args=['--ros-args', '-p', 'odom_topic:=/odometry/local'])
    bridge = NavigationBridge(SimpleNamespace(), motion=False, scan_topic='/scan', demo=False)
    writer = Node('callback_group_test_writer')
    publishers = [writer.create_publisher(Odometry, topic, 10)
                  for topic in ('/odom', '/odometry/local')]
    chassis = writer.create_publisher(HunterStatus, '/hunter_status', 10)
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(bridge)
    executor.add_node(writer)
    spin = threading.Thread(target=executor.spin, daemon=True)
    spin.start()
    stop = threading.Event()

    def feed():
        while not stop.is_set():
            stamp = writer.get_clock().now().to_msg()
            odom = Odometry()
            odom.header.stamp = stamp
            odom.child_frame_id = 'base_link'
            odom.pose.pose.orientation.w = 1.
            for publisher in publishers:
                publisher.publish(odom)
            status = HunterStatus()
            status.header.stamp = stamp
            status.control_mode = 1
            status.battery_voltage = 25.
            chassis.publish(status)
            stop.wait(.02)

    publisher_thread = threading.Thread(target=feed, daemon=True)
    publisher_thread.start()
    timer = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not bridge.wheel_odometry_seen:
            time.sleep(.02)
        assert bridge.wheel_odometry_seen and bridge.odometry_seen, 'No sensor discovery'
        entered, finished = threading.Event(), threading.Event()

        def slow_control():
            if entered.is_set():
                return
            entered.set()
            time.sleep(.75)
            finished.set()

        timer = bridge.create_timer(.01, slow_control)
        assert entered.wait(3), 'Control callback did not run'
        observed, max_age = [], 0.
        while not finished.is_set():
            now = time.monotonic()
            with bridge.state_lock:
                max_age = max(max_age, now - bridge.odometry_seen,
                              now - bridge.wheel_odometry_seen)
                observed.append(bridge.odometry_seen)
            time.sleep(.01)
        assert len(set(observed)) >= 15, 'Sensor callbacks stalled behind control'
        assert max_age < .2, f'Sensor receipt delayed {max_age:.3f}s'
        print(json.dumps(dict(control_delay_s=.75, max_sensor_age_s=max_age,
                              filtered_updates=len(set(observed)), passed=True)))
    finally:
        if timer:
            timer.cancel()
        stop.set()
        publisher_thread.join(timeout=2)
        executor.shutdown(timeout_sec=3)
        spin.join(timeout=3)
        bridge.destroy_node()
        writer.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
