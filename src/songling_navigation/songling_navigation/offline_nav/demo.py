"""A local kinematic robot and synthetic lidar; no hardware drivers are started."""

import json
import math
import time

import numpy as np
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped, Twist
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from PIL import Image
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from tf2_ros import TransformBroadcaster

from .maps import MapModel
from .store import ProjectStore


class DemoRobot(Node):
    def __init__(self):
        super().__init__("offline_demo_robot")
        self.declare_parameter("map_yaml", "")
        self.declare_parameter("sample_map", False)
        self.declare_parameter("store", "")
        filename = self.get_parameter("map_yaml").value
        saved = (
            ProjectStore(self.get_parameter("store").value).load()
            if self.get_parameter("store").value and not filename
            else None
        )
        self.model = (
            MapModel.load(filename)
            if filename
            else (
                saved[0]
                if saved
                else (
                    MapModel.demo()
                    if self.get_parameter("sample_map").value
                    else MapModel.default_site()
                )
            )
        )
        self.declare_parameter("initial_x", 0.0)
        self.declare_parameter("initial_y", 0.0)
        self.declare_parameter("initial_yaw", 0.0)
        self.x, self.y, self.yaw = [
            self.get_parameter(k).value
            for k in ("initial_x", "initial_y", "initial_yaw")
        ]
        self.cmd, self.cmd_at, self.last = Twist(), 0.0, time.monotonic()
        self.obstacles = []
        self.last_tf_stamp = None
        self.tf = TransformBroadcaster(self)
        self.odom_pub = self.create_publisher(Odometry, "/odom", 10)
        self.scan_pub = self.create_publisher(LaserScan, "/scan", 10)
        durable = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.create_subscription(
            OccupancyGrid, "/offline_nav/source_map", self.source_map, durable
        )
        self.create_subscription(Twist, "/cmd_vel", self.velocity, 10)
        self.create_subscription(
            String, "/offline_nav/demo_obstacles", self.set_obstacles, 1
        )
        self.create_timer(0.05, self.tick)
        self.create_timer(0.1, self.scan)

    def velocity(self, msg):
        self.cmd, self.cmd_at = msg, time.monotonic()

    def set_obstacles(self, msg):
        self.obstacles = json.loads(msg.data)

    def source_map(self, msg):
        """Map import changes simulated walls while annotations stay virtual."""
        data = np.asarray(msg.data, dtype=np.int8).reshape(
            msg.info.height, msg.info.width
        )
        image = Image.fromarray(
            np.flipud(np.where(data == 0, 254, np.where(data == 100, 0, 205))).astype(
                np.uint8
            )
        )
        origin = msg.info.origin
        self.model = MapModel(
            image,
            dict(
                resolution=msg.info.resolution,
                origin=[
                    origin.position.x,
                    origin.position.y,
                    2 * math.atan2(origin.orientation.z, origin.orientation.w),
                ],
            ),
        )

    def tick(self):
        now = time.monotonic()
        dt, self.last = min(now - self.last, 0.1), now
        v = self.cmd.linear.x if now - self.cmd_at < 0.3 else 0.0
        w = self.cmd.angular.z if now - self.cmd_at < 0.3 else 0.0
        self.x += v * math.cos(self.yaw) * dt
        self.y += v * math.sin(self.yaw) * dt
        self.yaw += w * dt
        stamp = self.get_clock().now().to_msg()
        self.last_tf_stamp = stamp
        origin = TransformStamped()
        origin.header.stamp, origin.header.frame_id = stamp, "map"
        origin.child_frame_id, origin.transform.rotation.w = "odom", 1.0
        body = TransformStamped()
        body.header.stamp, body.header.frame_id, body.child_frame_id = (
            stamp,
            "odom",
            "base_link",
        )
        body.transform.translation.x, body.transform.translation.y = self.x, self.y
        body.transform.rotation.z, body.transform.rotation.w = math.sin(
            self.yaw / 2
        ), math.cos(self.yaw / 2)
        self.tf.sendTransform([origin, body])
        odom = Odometry()
        odom.header, odom.child_frame_id = body.header, "base_link"
        odom.pose.pose.position.x, odom.pose.pose.position.y = self.x, self.y
        odom.pose.pose.orientation = body.transform.rotation
        odom.twist.twist.linear.x, odom.twist.twist.angular.z = v, w
        self.odom_pub.publish(odom)

    def scan(self):
        if self.last_tf_stamp is None:
            return
        count = 360
        angles = np.arange(count) * 2 * math.pi / count - math.pi
        rays = angles + self.yaw
        distances = np.arange(0.1, 15.0, 0.1)
        xs = self.x + np.cos(rays)[:, None] * distances
        ys = self.y + np.sin(rays)[:, None] * distances
        ox, oy, yaw = self.model.origin
        c, s, res = math.cos(yaw), math.sin(yaw), self.model.resolution
        gx = np.floor((c * (xs - ox) + s * (ys - oy)) / res).astype(int)
        gy = np.floor((-s * (xs - ox) + c * (ys - oy)) / res).astype(int)
        valid = (
            (gx >= 0) & (gy >= 0) & (gx < self.model.width) & (gy < self.model.height)
        )
        hit = ~valid
        hit[valid] = self.model.base[gy[valid], gx[valid]] != 0
        for x, y in self.obstacles:
            hit |= (xs - x) ** 2 + (ys - y) ** 2 <= 0.4 ** 2
        ranges = np.where(hit.any(axis=1), distances[hit.argmax(axis=1)], np.inf)
        msg = LaserScan()
        # Match the latest published body transform exactly.
        msg.header.stamp = self.last_tf_stamp
        msg.header.frame_id = "base_link"
        msg.angle_min, msg.angle_increment = -math.pi, 2 * math.pi / count
        msg.angle_max = msg.angle_min + (count - 1) * msg.angle_increment
        msg.range_min, msg.range_max, msg.scan_time = 0.1, 15.0, 0.1
        msg.ranges = ranges.astype(np.float32).tolist()
        self.scan_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = DemoRobot()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
