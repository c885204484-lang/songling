"""Isolated Nav2 tracking and wrong-command regression; no chassis drivers.

Run with ROS sourced: python3 test/integration_offline_tracking.py
The test owns ROS domain 91, port 8096, and a fresh temporary map store.
"""
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.request

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from songling_navigation.offline_nav.ros_bridge import distance_to_path


def main():
    os.environ['ROS_DOMAIN_ID'] = '91'
    os.environ['ROS_LOCALHOST_ONLY'] = '1'
    base = 'http://127.0.0.1:8096/api/'
    def api(name, payload=None):
        req = urllib.request.Request(base + name,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(req, timeout=5))
    def state():
        return api('state')['runtime']
    def wait_idle(timeout=40):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = state()
            if not s['busy']:
                return s
            time.sleep(.1)
        raise AssertionError(('navigation timeout', s['navigation'], s['guard']))

    log_path = '/tmp/songling-tracking-integration.log'
    node = None
    proc = None
    owned_processes = []
    with tempfile.TemporaryDirectory(prefix='songling-tracking-test-') as store, open(log_path, 'wb') as log:
        def launch_demo(directory):
            process = subprocess.Popen(['ros2', 'launch', 'songling_navigation', 'offline_navigation.launch.py',
                'demo:=true', 'sample_map:=true', 'enable_motion:=true', 'port:=8096', 'store:=' + directory],
                stdout=log, stderr=log, start_new_session=True)
            owned_processes.append(process)
            end = time.monotonic() + 45
            while time.monotonic() < end:
                try:
                    s = state()
                    if s.get('pose') and s['connection']['navigator_ready'] and s['scan_age_s'] < .6:
                        break
                except Exception:
                    pass
                time.sleep(.2)
            else:
                raise AssertionError('Demo did not start: ' + log_path)
            api('apply', {})
            time.sleep(2)
            return process

        def stop_demo(process):
            os.killpg(process.pid, signal.SIGINT)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)

        try:
            proc = launch_demo(store + '/normal')
            api('goal', dict(x=5., y=1.5, yaw=0.))
            s = wait_idle()
            assert s['navigation'] == '已到达', (s['navigation'], s['message'], s['guard'])
            print('PASS: curved Nav2 path reached goal with tracking gate enabled', flush=True)
            api('route', {'poses': [dict(x=8., y=1.5, yaw=0.), dict(x=11., y=1.5, yaw=0.)]})
            s = wait_idle()
            assert s['navigation'] == '已到达', (s['navigation'], s['message'], s['guard'])
            print('PASS: waypoint route reached final goal', flush=True)

            # A fresh robot on an open straight removes endpoint/turn-radius
            # feasibility from the fault-injection experiment.
            stop_demo(proc)
            proc = launch_demo(store + '/fault')

            rclpy.init()
            node = Node('isolated_bad_tracking_command')
            publisher = node.create_publisher(Twist, '/offline_nav/cmd_vel', 10)
            # Wait for publisher discovery before injecting, strictly in domain 91.
            end = time.monotonic() + 3
            while time.monotonic() < end:
                rclpy.spin_once(node, timeout_sec=.05)
            assert node.context.get_domain_id() == 91
            target = dict(x=8., y=0., yaw=0.)
            api('plan', target)
            s = wait_idle()
            assert s['navigation'] == '规划完成', (s['navigation'], s['message'])
            api('goal', target)
            end = time.monotonic() + 8
            reference = None
            while time.monotonic() < end:
                s = state()
                if s['navigation'] == '导航中' and len(s['path']) >= 2:
                    reference = s['path']
                    break
                time.sleep(.05)
            assert reference, s['navigation']
            wrong = Twist()
            wrong.linear.x, wrong.angular.z = .6, -.8
            samples = []
            end = time.monotonic() + 8
            while time.monotonic() < end:
                publisher.publish(wrong)
                rclpy.spin_once(node, timeout_sec=.01)
                s = state()
                samples.append(s['pose'])
                if s['navigation'] in ('取消中', '任务失败'):
                    break
            s = wait_idle()
            assert s['navigation'] == '任务失败', (s['navigation'], s['message'])
            assert '偏离本次规划路径' in s['message'], s['message']
            error = max(distance_to_path(p['x'], p['y'], reference) for p in samples if p)
            assert error < .8, error
            stop = s['pose']
            time.sleep(1)
            after = state()['pose']
            assert math.dist([stop['x'], stop['y']], [after['x'], after['y']]) < .04
            print('PASS: injected right-turn command cancelled before corridor exit; max error', round(error, 3), flush=True)
            Path('/tmp/songling-tracking-integration-evidence.json').write_text(json.dumps(
                dict(max_error_m=error, reference=reference, samples=samples, final_state=s), ensure_ascii=False, indent=2))
        finally:
            if node:
                node.destroy_node()
                rclpy.shutdown()
            for process in owned_processes:
                if process.poll() is None:
                    stop_demo(process)


if __name__ == '__main__':
    main()
