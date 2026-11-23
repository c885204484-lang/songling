"""Replay a recovered 0.25s frame beyond the old deadline on an isolated domain."""

import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from nav_msgs.msg import Odometry
from hunter_msgs.msg import HunterStatus

from songling_navigation.offline_nav.ros_bridge import NavigationBridge


def main():
    assert int(os.environ.get('ROS_DOMAIN_ID', '0')) != 0, 'Use an isolated ROS domain'
    expect_cancel = '--expect-cancel' in sys.argv
    rclpy.init(args=['--ros-args', '-p', 'odom_topic:=/odometry/local'])
    bridge = NavigationBridge(SimpleNamespace(), motion=False, scan_topic='/scan', demo=False)
    writer = Node('recovery_replay_writer')
    wheel = writer.create_publisher(Odometry, '/odom', 10)
    filtered = writer.create_publisher(Odometry, '/odometry/local', 10)
    chassis = writer.create_publisher(HunterStatus, '/hunter_status', 10)
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(bridge)
    executor.add_node(writer)
    spin = threading.Thread(target=executor.spin, daemon=True)
    spin.start()
    stop = threading.Event()
    replay = dict(start=None, filtered_return_count=0)

    def feed():
        while not stop.is_set():
            stamp = writer.get_clock().now().to_msg()
            msg = Odometry()
            msg.header.stamp = stamp
            msg.child_frame_id = 'base_link'
            msg.pose.pose.orientation.w = 1.
            wheel.publish(msg)
            status = HunterStatus()
            status.header.stamp = stamp
            status.control_mode = 1
            status.battery_voltage = 25.
            chassis.publish(status)
            send_filter = replay['start'] is None
            if replay['start'] is not None:
                elapsed = time.monotonic() - replay['start']
                if elapsed >= 1.85:
                    send_filter = True
                elif elapsed >= 1.60 and replay['filtered_return_count'] < 2:
                    send_filter = True
                elif elapsed >= 1.25 and replay['filtered_return_count'] < 1:
                    send_filter = True
            if send_filter:
                filtered.publish(msg)
                if replay['start'] is not None:
                    replay['filtered_return_count'] += 1
            stop.wait(.02)

    publisher_thread = threading.Thread(target=feed, daemon=True)
    publisher_thread.start()
    cancellations, samples = [], []
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not (bridge.wheel_odometry_seen and bridge.odometry_seen):
            time.sleep(.02)
        assert bridge.wheel_odometry_seen and bridge.odometry_seen
        with bridge.state_lock:
            bridge.busy = True
            bridge.navigation = '导航中'
            bridge.action_handle = SimpleNamespace(cancel_goal_async=lambda: cancellations.append(True))
        replay['start'] = time.monotonic()
        while time.monotonic() - replay['start'] < 3.:
            with bridge.state_lock:
                samples.append(dict(elapsed=time.monotonic()-replay['start'],
                    navigation=bridge.navigation, waiting=bridge.odometry_waiting,
                    filtered_age_s=time.monotonic()-bridge.odometry_seen,
                    wheel_age_s=time.monotonic()-bridge.wheel_odometry_seen,
                    recovery_samples=bridge.odometry_recovery_samples))
            time.sleep(.01)
        events = list(bridge.odometry_events)
        if expect_cancel:
            assert cancellations, 'Expected the old fixed deadline to reproduce cancellation'
            timeout = next(event for event in events if event['event'] == 'timeout')
            assert timeout['age_s'] < .5, 'Did not reproduce the fresh-data cancellation'
        else:
            assert not cancellations, 'Fresh recovery was incorrectly cancelled'
            assert bridge.navigation == '导航中' and not bridge.odometry_waiting
            assert [e['event'] for e in events] == ['waiting', 'recovered']
        report = dict(expect_cancel=expect_cancel, cancelled=bool(cancellations),
                      events=events, passed=True, samples=samples)
        if os.environ.get('RECOVERY_REPLAY_REPORT'):
            path = Path(os.environ['RECOVERY_REPLAY_REPORT'])
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({k:v for k,v in report.items() if k != 'samples'}, ensure_ascii=False))
    finally:
        stop.set()
        publisher_thread.join(timeout=2)
        executor.shutdown(timeout_sec=3)
        spin.join(timeout=3)
        bridge.destroy_node()
        writer.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
