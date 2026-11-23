"""Capture the costmap used immediately before a collision, before recovery clears it."""

from collections import deque
import json
import os
import threading
import time

from nav2_msgs.msg import Costmap
from nav_msgs.msg import Path
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import TransformException


class CollisionRecorder:
    def __init__(self, node, folder=None):
        self.node, self.folder = node, folder
        self.lock = threading.Lock()
        self.costmaps = deque(maxlen=3)
        self.arc = None
        self.events = deque(maxlen=5)
        self.last_recorded = 0.0
        node.create_subscription(Costmap, '/local_costmap/costmap_raw', self.on_costmap,
                                 qos_profile_sensor_data, callback_group=node.telemetry_group)
        node.create_subscription(Path, '/lookahead_collision_arc', self.on_arc,
                                 qos_profile_sensor_data, callback_group=node.telemetry_group)

    def on_costmap(self, message):
        with self.lock:
            self.costmaps.append((time.monotonic(), message))

    def on_arc(self, message):
        with self.lock:
            self.arc = message

    def record(self, stamp_ns):
        now = time.monotonic()
        if now - self.last_recorded < 2:
            return
        self.last_recorded = now
        with self.lock:
            snapshots = list(self.costmaps)
            arc = self.arc
        n = self.node
        frames = []
        for observed, message in snapshots:
            m = message.metadata
            try:
                t = n.tf.lookup_transform('map', message.header.frame_id, Time.from_msg(message.header.stamp)).transform
                to_map = dict(translation=[t.translation.x, t.translation.y, t.translation.z],
                              rotation=[t.rotation.x, t.rotation.y, t.rotation.z, t.rotation.w])
            except TransformException:
                to_map = None
            frames.append(dict(age_s=round(now-observed, 3), frame=message.header.frame_id,
                               stamp_ns=message.header.stamp.sec*1_000_000_000+message.header.stamp.nanosec,
                               width=m.size_x, height=m.size_y, resolution=m.resolution,
                               origin=[m.origin.position.x, m.origin.position.y], to_map=to_map,
                               data=list(message.data)))
        summary = dict(time_ns=stamp_ns, pose=n.pose,
                       lidar_enabled=getattr(n, 'use_lidar', True),
                       scan_age_s=round(now-n.scan_seen, 3) if n.scan_seen else None,
                       costmap_age_s=frames[-1]['age_s'] if frames else None,
                       message='控制器碰撞保护触发，已保存触发前局部栅格与预测轨迹')
        self.events.append(summary)
        record = dict(**summary, local_costmaps=frames, scan_points=n.scan_points,
                      predicted_arc=dict(frame=arc.header.frame_id,
                                         points=[[p.pose.position.x,p.pose.position.y] for p in arc.poses]) if arc else None,
                      map_revision=n.applied_revision,
                      mission=getattr(n, 'mission', None).data if getattr(n, 'mission', None) else None)
        # Build an immutable payload before returning to the control executor.
        payload = json.dumps(record, ensure_ascii=False, allow_nan=False)
        if self.folder:
            threading.Thread(target=self.write, args=(payload,), daemon=True).start()
        n.get_logger().warning(summary['message'])

    def write(self, payload):
        try:
            self.folder.mkdir(exist_ok=True)
            temp = self.folder / '.collision-latest.tmp'
            temp.write_text(payload)
            os.replace(temp, self.folder / 'collision-latest.json')
        except OSError as exc:
            self.node.get_logger().error(f'碰撞诊断保存失败：{exc}')
