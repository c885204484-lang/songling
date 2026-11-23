"""ROS adapter: maps, Nav2 actions, telemetry, and the final velocity gate."""

from array import array
from concurrent.futures import Future
import copy
import math
import queue
import time
import threading
import tempfile
from pathlib import Path as FilePath

import rclpy
from rclpy.action import ActionClient
from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
from rclpy.node import Node
from rclpy.qos import (
    QoSProfile,
    DurabilityPolicy,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from rclpy.time import Time
from geometry_msgs.msg import Twist
from nav_msgs.msg import OccupancyGrid, Path, Odometry
from nav2_msgs.action import (
    ComputePathToPose,
    ComputePathThroughPoses,
    NavigateToPose,
    NavigateThroughPoses,
)
from nav2_msgs.msg import CostmapFilterInfo, SpeedLimit
from sensor_msgs.msg import LaserScan, NavSatFix
from robot_localization.srv import FromLL
from rcl_interfaces.msg import Log
from hunter_msgs.msg import HunterStatus
from std_msgs.msg import String
from tf2_ros import Buffer, TransformListener, TransformException

from .maps import finite
from .planner_sync import PlannerResolutionSync
from .behavior import snapshot_navigation_trees
from .mission import MissionJournal
from .collision import CollisionRecorder
from .heading_search import HeadingSearch, stamped_pose


SPEED_GEARS_MPS = {kmh: kmh / 3.6 for kmh in (2, 4, 6)}
MAX_GEAR_SPEED_MPS = max(SPEED_GEARS_MPS.values())
DEFAULT_LINEAR_LIMIT = 0.7
ANGULAR_LIMIT = 0.8
PREDICTION_HORIZON = 1.5


def yaw_of(q):
    return math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))


def valid_transform(transform):
    t, q = transform.translation, transform.rotation
    return (
        all(math.isfinite(v) for v in (t.x, t.y, t.z, q.x, q.y, q.z, q.w))
        and abs(q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w - 1.0) < 0.01
    )


def distance_to_path(x, y, path, within=0.):
    """Distance to segments, including repeated points and sparsely sampled paths."""
    result = math.inf
    for a, b in zip(path, path[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = max(0., min(1., ((x - a[0]) * dx + (y - a[1]) * dy) / length2)) if length2 else 0.
        result = min(result, math.hypot(x - a[0] - t * dx, y - a[1] - t * dy))
        if result <= within:
            break
    return result


def planning_failure(text):
    message = text.lower()
    if "detected collision ahead" in message:
        return "控制器检测到前方碰撞风险，已停止：请检查局部障碍、禁行区及定位偏差"
    if "failed to make progress" in message:
        return "车辆未按预期前进：请检查底盘反馈、控制模式及附近障碍"
    if "starting point in lethal space" in message or "start occupied" in message:
        return "起点在障碍代价区内：检查小车附近激光障碍、禁行区及安全边距"
    if "goal" in message and ("lethal" in message or "occupied" in message):
        return "终点在障碍代价区内：请将终点移到道路中央"
    if "no valid path found" in message:
        return "未找到满足车身及转弯约束的路径：检查通道、终点朝向和附近激光障碍"
    if "exceeded" in message and ("time" in message or "iteration" in message):
        return "规划搜索达到时间或迭代上限，请检查通道及终点朝向"
    return None


class NavigationBridge(Node):
    def __init__(self, app, motion, scan_topic, demo):
        super().__init__("offline_map_workbench")
        self.app = app
        self.motion, self.demo = motion, demo
        self.use_lidar = self.declare_parameter("use_lidar", True).value
        self.connection = dict(
            domain_id=self.context.get_domain_id(),
            scan_topic=scan_topic,
            lidar_enabled=self.use_lidar,
            simulated=demo,
            planner_ready=False,
            navigator_ready=False,
        )
        self.requests = queue.Queue()
        self.urgent_requests = queue.Queue()
        self.deferred_request = None
        self.state_lock = threading.RLock()
        # Keep sensor receipt independent of map edits and control callbacks.
        self.telemetry_group = MutuallyExclusiveCallbackGroup()
        from ament_index_python.packages import get_package_share_directory
        self.behavior_trees = snapshot_navigation_trees(
            FilePath(get_package_share_directory("songling_navigation")) / "behavior_trees",
            tempfile.mkdtemp(prefix="songling-navigation-bt-"),
        )
        self.get_logger().info(f"Navigation trees: {self.behavior_trees}")
        self.active_model = self.active_grid = None
        self.source_model = None
        self.applied_at = 0.0
        self.applied_revision = None
        self.applied_project = None
        self.busy = False
        self.operation = 0
        self.operation_started_ns = 0
        self.failure_detail = ""
        store = getattr(app, "store", None)
        self.mission = MissionJournal(store.root / "mission.json" if store else None)
        self.stop_reason = ""
        self.action_handle = None
        self.heading_search = None
        self.planned_targets = []
        self.navigation = "待应用地图"
        self.message = ""
        self.path = []
        self.tracking_path = []
        self.tracking_goal = None
        self.odometry = None
        self.odometry_seen = 0.0
        self.odometry_stamp_ns = 0
        self.odometry_waiting = False
        self.odometry_wait_started = 0.0
        self.odometry_recovery_samples = 0
        self.odometry_events = []
        self.wheel_odometry = None
        self.wheel_odometry_seen = 0.0
        self.pose = None
        self.pose_seen = 0.0
        self.gps_fix = None
        self.gps_seen = 0.0
        self.chassis = None
        self.chassis_seen = 0.0
        self.from_ll = self.create_client(FromLL, "/fromLL")
        self.scan_points = []
        self.scan_seen = 0.0
        self.pending_scan = None
        self.cmd = Twist()
        self.cmd_seen = 0.0
        self.speed_gear_kmh = None
        self.guard_reason = "尚未导航"
        self.tf = Buffer()
        self.tf_listener = TransformListener(self.tf, self)
        durable = QoSProfile(
            depth=1,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            reliability=ReliabilityPolicy.RELIABLE,
        )
        self.map_pub = self.create_publisher(OccupancyGrid, "/map", durable)
        self.footprint_map_pub = self.create_publisher(
            OccupancyGrid, "/offline_nav/footprint_map", durable
        )
        self.source_pub = self.create_publisher(
            OccupancyGrid, "/offline_nav/source_map", durable
        )
        self.mask_pub = self.create_publisher(
            OccupancyGrid, "/offline_nav/keepout_mask", durable
        )
        self.info_pub = self.create_publisher(
            CostmapFilterInfo, "/offline_nav/filter_info", durable
        )
        self.vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.speed_limit_pub = self.create_publisher(SpeedLimit, "/offline_nav/speed_limit", durable)
        self.obstacle_pub = self.create_publisher(
            String, "/offline_nav/demo_obstacles", 1
        )
        self.create_subscription(Twist, "/offline_nav/cmd_vel", self.on_cmd, 10)
        if self.use_lidar:
            self.create_subscription(
                LaserScan, scan_topic, self.on_scan, qos_profile_sensor_data
            )
        self.create_subscription(Path, "/plan", self.on_path, 10)
        odom_topic = self.declare_parameter("odom_topic", "/odom").value
        self.require_wheel_odometry = not demo and odom_topic != "/odom"
        self.create_subscription(Odometry, odom_topic, self.on_odometry, qos_profile_sensor_data,
                                 callback_group=self.telemetry_group)
        if self.require_wheel_odometry:
            self.create_subscription(Odometry, "/odom", self.on_wheel_odometry, qos_profile_sensor_data,
                                     callback_group=self.telemetry_group)
        self.create_subscription(NavSatFix, "/gps/fix", self.on_fix, qos_profile_sensor_data,
                                 callback_group=self.telemetry_group)
        self.create_subscription(Log, "/rosout", self.on_navigation_log, 50)
        self.create_subscription(HunterStatus, "/hunter_status", self.on_chassis, qos_profile_sensor_data,
                                 callback_group=self.telemetry_group)
        self.plan_client = ActionClient(
            self, ComputePathToPose, "/compute_path_to_pose"
        )
        self.plan_route_client = ActionClient(
            self, ComputePathThroughPoses, "/compute_path_through_poses"
        )
        self.goal_client = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self.route_client = ActionClient(
            self, NavigateThroughPoses, "/navigate_through_poses"
        )
        self.planner_sync = PlannerResolutionSync(self)
        self.collision_recorder = CollisionRecorder(self, store.root / "diagnostics" if store else None)
        self.create_timer(0.05, self.tick)
        self.create_timer(1.0, self.publish_speed_limit)
        self.create_timer(0.1, self.telemetry, callback_group=self.telemetry_group)

    def status(self):
        with self.state_lock:
            return dict(
                mode="ros",
                connection=dict(self.connection),
                motion_enabled=self.motion,
                speed_gear_kmh=self.speed_gear_kmh,
                busy=self.busy,
                navigation=self.navigation,
                message=self.message,
                mission=self.mission.summary(self.app.map_id, self.app.project),
                collision_events=list(self.collision_recorder.events),
                guard=self.guard_reason,
                pose=self.pose if time.monotonic() - self.pose_seen <= 0.5 else None,
                path=copy.deepcopy(self.tracking_path or self.path),
                planned_targets=copy.deepcopy(self.planned_targets),
                scan_points=copy.deepcopy(
                    self.scan_points[:: max(1, len(self.scan_points) // 800)]
                ),
                scan_age_s=round(time.monotonic() - self.scan_seen, 2)
                if self.scan_seen
                else None,
                applied_revision=self.applied_revision,
                gps=self.gps_fix if time.monotonic() - self.gps_seen < 2 else None,
                chassis=dict(
                    **(self.chassis or {}),
                    age_s=round(time.monotonic() - self.chassis_seen, 2) if self.chassis_seen else None,
                    ready=not bool(self.chassis_block_reason()),
                    message=self.chassis_block_reason() or ("仿真底盘" if self.demo else "CAN 控制正常"),
                ),
                odometry=dict(**(self.odometry or {}),
                    age_s=round(time.monotonic() - self.odometry_seen, 2) if self.odometry_seen else None,
                    waiting=getattr(self, "odometry_waiting", False),
                    events=copy.deepcopy(getattr(self, "odometry_events", [])),
                    ready=not bool(self.odometry_block_reason()),
                    message=self.odometry_block_reason() or "里程计正常"),
                wheel_odometry=dict(**(self.wheel_odometry or {}),
                    required=self.require_wheel_odometry,
                    age_s=round(time.monotonic() - self.wheel_odometry_seen, 2) if self.wheel_odometry_seen else None,
                    ready=not bool(self.wheel_odometry_block_reason()),
                    message=self.wheel_odometry_block_reason() or "原始底盘里程计正常"),
            )

    def on_wheel_odometry(self, msg):
        age = (self.get_clock().now() - Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
        if not -.1 <= age <= .5:
            return
        values = (msg.twist.twist.linear.x, msg.twist.twist.linear.y,
                  msg.twist.twist.angular.z, msg.twist.covariance[0])
        valid = (all(math.isfinite(v) for v in values)
                 and values[3] >= 0 and msg.child_frame_id == "base_link")
        observed_at = time.monotonic() - max(0, age)
        with self.state_lock:
            if observed_at < self.wheel_odometry_seen:
                return
            self.wheel_odometry = dict(
                v=values[0] if math.isfinite(values[0]) else None,
                valid=valid, frame=msg.child_frame_id)
            self.wheel_odometry_seen = observed_at

    def wheel_odometry_block_reason(self):
        if not getattr(self, "require_wheel_odometry", False):
            return ""
        if (not self.wheel_odometry
                or time.monotonic() - self.wheel_odometry_seen > .5):
            return "底盘原始里程计中断：检查 USB/CAN 连接，滤波器外推不能代替实测反馈"
        if not self.wheel_odometry["valid"]:
            return "底盘原始里程计异常：速度、协方差或参考坐标系无效"
        return ""

    def on_odometry(self, msg):
        stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        age = (self.get_clock().now() - Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
        values = (msg.twist.twist.linear.x, msg.twist.twist.linear.y, msg.twist.twist.angular.z,
                  msg.twist.covariance[0], msg.twist.covariance[7], msg.twist.covariance[35],
                  msg.pose.covariance[0], msg.pose.covariance[7], msg.pose.covariance[35])
        if not -.1 <= age <= .5:
            return
        detail = ""
        if not all(math.isfinite(v) for v in values):
            detail = "速度或协方差含非有限数值"
        elif any(v < 0 for v in values[3:]):
            detail = "协方差出现负值"
        elif msg.child_frame_id != "base_link":
            detail = f"速度参考坐标系错误：{msg.child_frame_id}"
        else:
            for axis, variance in zip(("前向速度", "横向速度", "角速度"), values[3:6]):
                if variance > .25:
                    detail = f"{axis}方差 {variance:.3g} 超过 0.25"
                    break
        # This local filter integrates wheel velocity and gyro rate, with no
        # absolute position/yaw observation. Its accumulated pose covariance
        # is unbounded even when instantaneous velocity is accurate. Global
        # map->base_link supplies the navigation pose; a fixed upper bound on
        # local pose covariance incorrectly disables a healthy long-running EKF.
        with self.state_lock:
            if stamp_ns <= getattr(self, "odometry_stamp_ns", 0):
                return
            observed_at = time.monotonic() - max(0, age)
            if getattr(self, "odometry_waiting", False):
                # Recovery uses the same freshness contract as motion gating.
                # A fixed 0.2s cadence incorrectly rejects delayed valid data.
                consecutive = observed_at - self.odometry_seen <= .5
                self.odometry_recovery_samples = (
                    getattr(self, "odometry_recovery_samples", 0) + 1
                    if consecutive and not detail else (0 if detail else 1)
                )
            self.odometry_stamp_ns = stamp_ns
            self.odometry = dict(v=values[0] if math.isfinite(values[0]) else None,
                                 vy=values[1] if math.isfinite(values[1]) else None,
                                 w=values[2] if math.isfinite(values[2]) else None,
                                 valid=not detail, detail=detail,
                                 velocity_variance=[v if math.isfinite(v) else None for v in values[3:6]],
                                 pose_variance=[v if math.isfinite(v) else None for v in values[6:]])
            self.odometry_seen = observed_at

    def odometry_block_reason(self):
        if self.demo:
            return ""
        raw_reason = NavigationBridge.wheel_odometry_block_reason(self)
        if raw_reason:
            return raw_reason
        o = self.odometry
        if o is None or time.monotonic() - self.odometry_seen > .5:
            return "里程计反馈过期：已停止速度输出，等待有效反馈"
        if not o["valid"]:
            return "里程计数值异常：" + o.get("detail", "请检查底盘断流及局部滤波器")
        if abs(o["v"]) > 2 or abs(o["vy"]) > .2 or abs(o["w"]) > 1:
            return f"里程计速度异常：前向 {o['v']:.2f}、横向 {o['vy']:.2f} m/s、角速度 {o['w']:.2f} rad/s"
        if self.chassis and abs(o["v"] - self.chassis["linear_velocity"]) > .25:
            return f"里程计与底盘速度不一致：滤波 {o['v']:.2f} / 底盘 {self.chassis['linear_velocity']:.2f} m/s"
        if (getattr(self, "odometry_waiting", False)
                and getattr(self, "odometry_recovery_samples", 0) < 3):
            return "里程计恢复确认中：保持零速，等待连续 3 帧有效反馈"
        return ""

    def record_odometry_event(self, event):
        entry = dict(event=event, time_ns=time.time_ns(),
                     age_s=round(time.monotonic() - self.odometry_seen, 3),
                     chassis_age_s=round(time.monotonic() - self.chassis_seen, 3),
                     recovery_samples=getattr(self, "odometry_recovery_samples", 0))
        if getattr(self, "require_wheel_odometry", False):
            entry["wheel_age_s"] = (round(time.monotonic() - self.wheel_odometry_seen, 3)
                                    if self.wheel_odometry_seen else None)
        self.odometry_events = (getattr(self, "odometry_events", []) + [entry])[-10:]
        if hasattr(self, "get_logger"):
            self.get_logger().warning(f"Odometry watchdog: {entry}")

    def odometry_navigation_fault(self):
        """Hold zero immediately for a brief gap; cancel only sustained loss.

        The velocity watchdog still rejects samples older than 0.5 seconds.
        Recovery needs three consecutive samples and a new controller command.
        """
        reason = NavigationBridge.odometry_block_reason(self)
        now = time.monotonic()
        delayed = reason.startswith(("里程计反馈过期", "里程计恢复确认中"))
        if reason.startswith("底盘原始里程计"):
            NavigationBridge.record_odometry_event(self, "wheel_feedback_unavailable")
            return reason
        if delayed:
            if not getattr(self, "odometry_waiting", False):
                self.odometry_waiting = True
                self.odometry_wait_started = now
                self.odometry_recovery_samples = 0
                NavigationBridge.record_odometry_event(self, "waiting")
                self.stop()
            # Fresh valid samples are recovery progress. Do not cancel merely
            # because a wall-clock deadline since the FIRST gap has expired.
            if now - self.odometry_seen >= 1.5:
                NavigationBridge.record_odometry_event(self, "timeout")
                return f"里程计反馈持续中断，任务已停止（有效数据年龄 {now-self.odometry_seen:.2f} 秒）"
            self.message = "里程计暂时延迟，已暂停输出；等待连续 3 帧有效反馈"
            return ""
        if not reason and getattr(self, "odometry_waiting", False):
            NavigationBridge.record_odometry_event(self, "recovered")
            self.odometry_waiting = False
            self.odometry_wait_started = 0.0
            self.message = "里程计已恢复，继续导航"
            self.stop()
        return reason

    def on_chassis(self, msg):
        age = (self.get_clock().now() - Time.from_msg(msg.header.stamp)).nanoseconds / 1e9
        if not -.1 <= age <= 1 or not all(math.isfinite(v) for v in
                (msg.linear_velocity, msg.steering_angle, msg.battery_voltage)):
            return
        with self.state_lock:
            self.chassis = dict(vehicle_state=msg.vehicle_state, control_mode=msg.control_mode,
                                error_code=msg.error_code, battery_voltage=msg.battery_voltage,
                                linear_velocity=msg.linear_velocity)
            self.chassis_seen = time.monotonic() - max(0, age)

    def chassis_block_reason(self):
        if self.demo:
            return ""
        if self.chassis is None or time.monotonic() - self.chassis_seen > 1:
            return "底盘反馈丢失：检查 CAN 激活状态、USB 连接及底盘驱动"
        if self.chassis['vehicle_state'] != 0:
            return "底盘急停或异常状态，禁止运动"
        if self.chassis['error_code'] != 0:
            return f"底盘故障码 {self.chassis['error_code']}，禁止运动"
        if self.chassis['control_mode'] != 1:
            return "底盘未处于 CAN 控制模式，请检查遥控器控制档位"
        return ""

    def on_fix(self, msg):
        if msg.status.status < 0 or not all(math.isfinite(v) for v in (msg.latitude, msg.longitude)):
            return
        variance = max(msg.position_covariance[0], msg.position_covariance[4])
        sigma = math.sqrt(variance) if msg.position_covariance_type and math.isfinite(variance) and variance >= 0 else None
        with self.state_lock:
            self.gps_fix = dict(latitude=msg.latitude, longitude=msg.longitude,
                                status=msg.status.status, horizontal_sigma_m=sigma)
            self.gps_seen = time.monotonic()

    def on_navigation_log(self, msg):
        if msg.name not in ("planner_server", "controller_server") or msg.level < 30:
            return
        stamp = msg.stamp.sec * 1_000_000_000 + msg.stamp.nanosec
        detail = planning_failure(msg.msg)
        if detail and not getattr(self, "use_lidar", True) and "detected collision ahead" in msg.msg.lower():
            detail = "控制器检测到车身与地图障碍的碰撞风险，已停止：请检查禁行区边界及定位偏差"
        with self.state_lock:
            if detail and self.operation_started_ns and stamp >= self.operation_started_ns:
                if "detected collision ahead" in msg.msg.lower() and getattr(self, "collision_recorder", None):
                    self.collision_recorder.record(stamp)
                self.failure_detail = detail
                if not self.busy and self.navigation in ("规划失败", "任务失败") and not self.stop_reason:
                    self.message = detail

    def project_geographic(self, samples):
        """Called on an HTTP thread; the ROS executor remains free to stop motion."""
        if self.demo:
            raise ValueError("经纬度自动对齐需要真实 GPS 定位模块")
        if not self.from_ll.wait_for_service(timeout_sec=1):
            raise ValueError("未发现 /fromLL，请先启动 navsat_transform_node 并设置固定 datum")
        futures = []
        try:
            for p in samples:
                req = FromLL.Request()
                req.ll_point.latitude, req.ll_point.longitude = p["lat"], p["lon"]
                futures.append(self.from_ll.call_async(req))
            deadline = time.monotonic() + 3
            result = []
            for future in futures:
                done = threading.Event()
                future.add_done_callback(lambda _, event=done: event.set())
                if not done.wait(max(0, deadline - time.monotonic())):
                    raise ValueError("经纬度转换超时，请检查 GPS 定位模块")
                response = future.result()
                if response is None:
                    raise ValueError("经纬度转换失败，定位模块尚未就绪")
                point = response.map_point
                result.append([finite(point.x), finite(point.y)])
            return result
        finally:
            for future in futures:
                if not future.done():
                    future.cancel()

    def command(self, name, payload):
        future = Future()
        (self.urgent_requests if name == "cancel" else self.requests).put(
            (name, payload, future)
        )
        try:
            return future.result(timeout=5)
        except TimeoutError:
            future.cancel()
            raise ValueError("ROS 执行器未响应，请检查进程")

    def stop(self):
        self.cmd = Twist()
        self.cmd_seen = 0.0
        self.vel_pub.publish(Twist())

    def on_cmd(self, msg):
        self.cmd, self.cmd_seen = msg, time.monotonic()

    def publish_speed_limit(self):
        if self.speed_gear_kmh is not None:
            self.speed_limit_pub.publish(SpeedLimit(speed_limit=SPEED_GEARS_MPS[self.speed_gear_kmh]))

    def on_path(self, msg):
        if msg.header.frame_id == "map":
            with self.state_lock:
                if getattr(self, "heading_search", None) is not None:
                    return
                stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
                if stamp < self.operation_started_ns:
                    return
                path = [[p.pose.position.x, p.pose.position.y] for p in msg.poses]
                if len(path) < 2 or not all(math.isfinite(v) for p in path for v in p):
                    return
                self.path = path
                if (not self.tracking_goal or not self.busy
                        or self.navigation not in ("导航中", "正在接受目标")
                        or self.stop_reason
                        or math.dist(path[-1], self.tracking_goal) > .5):
                    return
                # Check the OLD reference before accepting a replan. A path
                # starting at an already deviated pose must never clear a fault.
                if NavigationBridge.tracking_block_reason(self):
                    return
                if (not self.pose or time.monotonic() - self.pose_seen > .5
                        or math.dist(path[0], [self.pose["x"], self.pose["y"]]) > .75):
                    return
                # Nav2 can legitimately replace an obstructed path. Following
                # that new path while predicting against the first path causes
                # false stops. The gate and display must use the same reference.
                self.tracking_path = copy.deepcopy(path)
                # Wait for a fresh controller command after the path change;
                # the previous command may still belong to the previous path.
                self.cmd_seen = 0.0

    def on_scan(self, msg):
        self.pending_scan = msg

    def consume_scan(self):
        msg = self.pending_scan
        if msg is None:
            return
        fields = (msg.angle_min, msg.angle_increment, msg.range_min, msg.range_max)
        valid_layout = (
            all(math.isfinite(v) for v in fields)
            and msg.angle_increment != 0.0
            and 0.0 <= msg.range_min < msg.range_max
        )
        usable = valid_layout and any(
            (math.isfinite(d) and msg.range_min <= d <= msg.range_max) or d == math.inf
            for d in msg.ranges
        )
        if not usable:
            # Invalid packets must neither clear prior obstacles nor refresh the
            # watchdog. Positive infinity is a valid no-return measurement.
            self.pending_scan = None
            return
        # Transform at the measurement time. A missing/stale TF cannot refresh the watchdog.
        stamp = Time.from_msg(msg.header.stamp)
        age = (self.get_clock().now() - stamp).nanoseconds / 1e9
        if age < -0.1 or age > 0.6:
            return
        try:
            transform = self.tf.lookup_transform("map", msg.header.frame_id, stamp)
        except TransformException:
            return
        if not valid_transform(transform.transform):
            self.pending_scan = None
            return
        t, q = transform.transform.translation, transform.transform.rotation
        # Full 3D quaternion rotation handles mounted lidar roll/pitch.
        xx, yy, zz, ww = q.x, q.y, q.z, q.w
        r00, r01 = 1 - 2 * (yy * yy + zz * zz), 2 * (xx * yy - zz * ww)
        r10, r11 = 2 * (xx * yy + zz * ww), 1 - 2 * (xx * xx + zz * zz)
        points = []
        for i, distance in enumerate(msg.ranges):
            if math.isfinite(distance) and msg.range_min <= distance <= msg.range_max:
                angle = msg.angle_min + i * msg.angle_increment
                x, y = distance * math.cos(angle), distance * math.sin(angle)
                points.append([t.x + r00 * x + r01 * y, t.y + r10 * x + r11 * y])
        with self.state_lock:
            self.scan_points, self.scan_seen = points, time.monotonic() - max(0.0, age)
            self.pending_scan = None

    def telemetry(self):
        with self.state_lock:
            self.connection.update(
                planner_ready=self.plan_client.server_is_ready(),
                navigator_ready=self.goal_client.server_is_ready(),
                planner_map_ready=(self.active_model is not None
                                   and self.planner_sync.ready_for(self.active_model.resolution)),
            )
        try:
            transform = self.tf.lookup_transform("map", "base_link", Time())
            stamp_age = (
                self.get_clock().now() - Time.from_msg(transform.header.stamp)
            ).nanoseconds / 1e9
            if stamp_age > 0.5 or stamp_age < -0.1:
                raise ValueError("定位 TF 已过期")
            if not valid_transform(transform.transform):
                raise ValueError("定位 TF 数据无效")
            t, q = transform.transform.translation, transform.transform.rotation
            with self.state_lock:
                self.pose = dict(x=t.x, y=t.y, yaw=yaw_of(q))
                self.pose_seen = time.monotonic() - max(0.0, stamp_age)
        except (TransformException, ValueError):
            with self.state_lock:
                self.pose = None

    def tick(self):
        self.consume_scan()
        # Never wait behind an HTTP edit on the executor thread. Cancels have
        # a separate queue and bypass the edit lock entirely.
        for _ in range(8):
            try:
                entry = self.urgent_requests.get_nowait()
            except queue.Empty:
                if self.deferred_request is not None:
                    entry, self.deferred_request = self.deferred_request, None
                else:
                    try:
                        entry = self.requests.get_nowait()
                    except queue.Empty:
                        break
            name, payload, future = entry
            edit_acquired = False
            document_acquired = False
            if name not in ("cancel", "speed"):
                edit_acquired = self.app.edit_lock.acquire(blocking=False)
                if edit_acquired:
                    document_acquired = self.app.lock.acquire(blocking=False)
                if not document_acquired:
                    if edit_acquired:
                        self.app.edit_lock.release()
                    self.deferred_request = entry
                    break
            try:
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    with self.state_lock:
                        result = self.dispatch(name, payload)
                    future.set_result(result)
                except Exception as exc:
                    future.set_exception(ValueError(str(exc)))
            finally:
                if document_acquired:
                    self.app.lock.release()
                if edit_acquired:
                    self.app.edit_lock.release()
        if getattr(self, "heading_search", None) is not None:
            self.advance_heading_search()
        with self.state_lock:
            navigating = self.busy and self.navigation in ("导航中", "正在接受目标")
            fault = (NavigationBridge.chassis_block_reason(self)
                     or (NavigationBridge.odometry_navigation_fault(self) if navigating
                         else NavigationBridge.odometry_block_reason(self))
                     or NavigationBridge.tracking_block_reason(self))
            if navigating and fault:
                self.stop_reason = fault
                self.odometry_waiting = False
                self.odometry_wait_started = 0.0
                self.odometry_recovery_samples = 0
                self.navigation, self.message = "取消中", fault
                if self.action_handle:
                    self.action_handle.cancel_goal_async()
                self.stop()
            command, reason = NavigationBridge.guarded_velocity(self)
            if self.busy and self.navigation in ("导航中", "正在接受目标") and reason.startswith("预测轨迹偏离"):
                self.stop_reason = reason
                self.navigation, self.message = "取消中", reason
                if self.action_handle:
                    self.action_handle.cancel_goal_async()
                self.stop()
            self.guard_reason = reason or "通行"
            # Only this gate writes to the chassis velocity topic in this launch.
            self.vel_pub.publish(Twist() if reason else command)

    def limit_command(self):
        # Keep the steering curvature when an old controller command arrives
        # after a downshift, or a turn would exceed the angular limit.
        command = self.cmd
        gear = getattr(self, "speed_gear_kmh", None)
        v, w = command.linear.x, command.angular.z
        if not gear or not (0.0 < v <= MAX_GEAR_SPEED_MPS) or not math.isfinite(w):
            return command
        scale = min(1.0, SPEED_GEARS_MPS[gear] / v, ANGULAR_LIMIT / max(ANGULAR_LIMIT, abs(w)))
        if self.pose and self.tracking_goal:
            distance = math.hypot(self.pose["x"] - self.tracking_goal[0], self.pose["y"] - self.tracking_goal[1])
            scale = min(scale, distance / (PREDICTION_HORIZON * v))
        return NavigationBridge.scale_command(command, scale) if scale < 1.0 else command

    @staticmethod
    def scale_command(command, scale):
        scaled = copy.deepcopy(command)
        scaled.linear.x *= scale
        scaled.angular.z = max(-ANGULAR_LIMIT, min(ANGULAR_LIMIT, command.angular.z * scale))
        return scaled

    def guarded_velocity(self):
        command = NavigationBridge.limit_command(self)
        reason, on_path_fraction = NavigationBridge.check_velocity(self, command)
        if command.linear.x > DEFAULT_LINEAR_LIMIT and on_path_fraction > 0.0:
            # Low speeds let the controller finish correcting its heading near
            # a bend. Keep the same curvature and verify the shorter projection.
            slower = NavigationBridge.scale_command(command, on_path_fraction)
            if not NavigationBridge.check_velocity(self, slower)[0]:
                return slower, ""
        return command, reason

    def velocity_block_reason(self, command=None):
        if command is None:
            return NavigationBridge.guarded_velocity(self)[1]
        return NavigationBridge.check_velocity(self, command)[0]

    def check_velocity(self, command):
        now = time.monotonic()
        if not self.motion:
            return "运动未启用", 0.0
        chassis_reason = NavigationBridge.chassis_block_reason(self)
        if chassis_reason:
            return chassis_reason, 0.0
        odometry_reason = NavigationBridge.odometry_block_reason(self)
        if odometry_reason:
            return odometry_reason, 0.0
        if self.active_grid is None:
            return "地图未应用", 0.0
        if not self.busy or self.navigation not in ("导航中", "正在接受目标"):
            return "未执行导航", 0.0
        if not self.pose:
            return "定位不可用或过期", 0.0
        if not self.tracking_path:
            return "等待本次导航路径", 0.0
        tracking_reason = NavigationBridge.tracking_block_reason(self)
        if tracking_reason:
            return tracking_reason, 0.0
        if getattr(self, "use_lidar", True) and now - self.scan_seen > 0.6:
            return "激光雷达数据过期", 0.0
        if now - self.cmd_seen > 0.3:
            return "速度指令过期", 0.0
        values = [command.linear.x, command.linear.y, command.angular.z]
        if not all(math.isfinite(v) for v in values):
            return "速度指令无效", 0.0
        v, _, w = values
        gear = getattr(self, "speed_gear_kmh", None)
        forward_limit = SPEED_GEARS_MPS[gear] + 1e-9 if gear else DEFAULT_LINEAR_LIMIT
        if (not -DEFAULT_LINEAR_LIMIT <= v <= forward_limit or abs(w) > ANGULAR_LIMIT
                or abs(command.linear.y) > 0.001):
            return "速度指令超过上限", 0.0
        x, y, theta = self.pose["x"], self.pose["y"], self.pose["yaw"]
        # Circumscribed robot radius (0.52 m) + 0.13 m margin is baked into the map.
        # The laser gate uses that same conservative disk along a 1.5 s trajectory.
        steps = 30
        if abs(v) > DEFAULT_LINEAR_LIMIT:
            steps = max(steps, math.ceil(abs(v) * PREDICTION_HORIZON / (self.active_model.resolution / 2)))
        dt = PREDICTION_HORIZON / steps
        for step in range(steps + 1):
            if not self.active_model.is_free(self.active_grid, x, y):
                return "预测轨迹超出可行驶区域", 0.0
            if getattr(self, "use_lidar", True) and any(
                (x - px) ** 2 + (y - py) ** 2 <= 0.65 ** 2
                for px, py in self.scan_points
            ):
                return "预测轨迹遇到激光障碍", 0.0
            if distance_to_path(x, y, self.tracking_path, within=.75) > .75:
                return "预测轨迹偏离本次规划路径（超过 0.75 米），已停止", max(0, step - 1) / steps
            x += v * math.cos(theta) * dt
            y += v * math.sin(theta) * dt
            theta += w * dt
        return "", 0.0

    def tracking_block_reason(self):
        if self.tracking_path and self.pose:
            error = distance_to_path(self.pose["x"], self.pose["y"], self.tracking_path)
            if error > .75:
                return f"车辆偏离本次规划路径 {error:.2f} 米，已停止；请核对定位和转向"
        return ""

    def advance_heading_search(self):
        # Preserve the same lock order and recheck the map and motion guards
        # before submitting the resolved poses to the navigator.
        if not self.app.edit_lock.acquire(blocking=False):
            return
        try:
            if not self.app.lock.acquire(blocking=False):
                return
            try:
                with self.state_lock:
                    search, name, route = self.heading_search
                    try:
                        result = search.advance()
                        if result is None:
                            return
                        targets, path = result
                        if self.app.model is not self.source_model or self.app.project != self.applied_project:
                            raise ValueError("保存的地图已变化，请重新应用后规划")
                        self.heading_search, self.busy = None, False
                        if name == "plan":
                            self.operation_started_ns = self.get_clock().now().nanoseconds
                            self.navigation, self.message = "规划完成", "已自动确定途径点和终点的行驶朝向"
                            self.path = path
                        else:
                            self.dispatch(name, {"poses": targets} if route else targets[0], automatic=True)
                        self.planned_targets = targets
                    except Exception as exc:
                        search.cancel()
                        self.heading_search, self.busy = None, False
                        self.navigation, self.message = "规划失败", str(exc)
            finally:
                self.app.lock.release()
        finally:
            self.app.edit_lock.release()

    def dispatch(self, name, payload, *, automatic=False):
        if name == "cancel":
            search = getattr(self, "heading_search", None)
            if search is not None:
                search[0].cancel()
                self.heading_search, self.busy = None, False
                self.operation_started_ns = self.get_clock().now().nanoseconds
            if self.action_handle:
                self.action_handle.cancel_goal_async()
            self.navigation = "取消中" if self.busy else "已取消"
            self.odometry_waiting = False
            self.odometry_wait_started = 0.0
            self.odometry_recovery_samples = 0
            self.stop()
            return {"ok": True}
        if name == "speed":
            gear = payload.get("kmh") if isinstance(payload, dict) else None
            if type(gear) is not int or gear not in SPEED_GEARS_MPS:
                raise ValueError("请选择 2、4 或 6 km/h 档位")
            if not self.speed_limit_pub.get_subscription_count():
                raise ValueError("Nav2 速度接口尚未就绪，请稍候重试")
            self.speed_gear_kmh = gear
            self.publish_speed_limit()
            return {"speed_gear_kmh": gear}
        if name == "obstacles":
            if not getattr(self, "use_lidar", True):
                raise ValueError("当前为无雷达模式，请在地图中标注障碍或禁行区")
            if not self.demo:
                raise ValueError("只可在仿真模式中添加模拟障碍")
            points = [[finite(v) for v in p] for p in payload.get("points", [])]
            if len(points) > 50 or any(len(p) != 2 for p in points):
                raise ValueError("模拟障碍最多 50 个，每个为 [x, y]")
            import json

            self.obstacle_pub.publish(String(data=json.dumps(points)))
            return {"ok": True}
        if self.busy:
            raise ValueError("已有规划或导航任务，请先取消")
        resume_index = None
        if name == "resume":
            resume_index, targets = self.mission.prepare_resume(payload, self.app.map_id, self.app.project)
            name = "route" if len(targets) > 1 else "goal"
            payload = {"poses": targets} if name == "route" else targets[0]
        if name == "apply":
            self.stop()
            source_model, project = self.app.model, copy.deepcopy(self.app.project)
            if (
                not self.demo
                and source_model.context.get("georeference", {}).get(
                    "navigation_aligned"
                )
                is False
            ):
                raise ValueError("园区底图尚未与实车 RTK/SLAM 坐标配准；请先完成地图配准，再用于实车导航")
            if project["clearance_m"] < 0.65:
                raise ValueError("导航所需安全边距至少 0.65 米（包含车身半径）")
            model, grid = source_model.navigation_map(project)
            if not (grid == 0).any():
                raise ValueError("没有可行驶栅格，请检查可行驶区域、禁行区和安全边距")
            self.active_model, self.active_grid = model, grid
            self.source_model = source_model
            self.applied_project = project
            self.applied_revision = self.app.revision or "初始地图"
            msg = OccupancyGrid()
            msg.header.frame_id = "map"
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.info.width, msg.info.height = model.width, model.height
            msg.info.resolution = model.resolution
            msg.info.origin.position.x, msg.info.origin.position.y = model.origin[:2]
            msg.info.origin.orientation.z = math.sin(model.origin[2] / 2)
            msg.info.origin.orientation.w = math.cos(model.origin[2] / 2)
            msg.data = array("b", grid.tobytes())
            self.map_pub.publish(msg)
            self.mask_pub.publish(msg)
            physical_model, physical_grid = source_model.footprint_map(project)
            physical_msg = copy.deepcopy(msg)
            physical_msg.info.width = physical_model.width
            physical_msg.info.height = physical_model.height
            physical_msg.info.resolution = physical_model.resolution
            physical_msg.info.origin.position.x, physical_msg.info.origin.position.y = physical_model.origin[:2]
            physical_msg.data = array("b", physical_grid.tobytes())
            self.footprint_map_pub.publish(physical_msg)
            info = CostmapFilterInfo()
            info.header = msg.header
            info.type, info.base, info.multiplier = 0, 0.0, 1.0
            info.filter_mask_topic = "/offline_nav/keepout_mask"
            self.info_pub.publish(info)
            original = copy.deepcopy(msg)
            original.info.width, original.info.height = (
                source_model.width,
                source_model.height,
            )
            original.info.resolution = source_model.resolution
            (
                original.info.origin.position.x,
                original.info.origin.position.y,
            ) = source_model.origin[:2]
            original.info.origin.orientation.z = math.sin(source_model.origin[2] / 2)
            original.info.origin.orientation.w = math.cos(source_model.origin[2] / 2)
            original.data = array("b", source_model.base.tobytes())
            self.source_pub.publish(original)
            self.applied_at = time.monotonic()
            self.navigation, self.message = "地图已应用", "可设置终点并请求 Nav2 规划"
            self.path = []
            self.planned_targets = []
            return {"ok": True, "free_cells": int((grid == 0).sum())}
        if name not in ("plan", "goal", "route"):
            raise ValueError("未知操作")
        if self.active_grid is None or time.monotonic() - self.applied_at < 1.0:
            raise ValueError("请先应用地图并等待代价地图接收")
        if not self.planner_sync.ready_for(self.active_model.resolution):
            raise ValueError("正在同步规划器与地图分辨率，请稍候再规划")
        if (
            self.app.model is not self.source_model
            or self.app.project != self.applied_project
        ):
            raise ValueError("保存的地图已变化，请重新应用后规划")
        if not self.pose:
            raise ValueError("缺少 map → base_link 定位，请启动仿真或实车定位")
        if not self.active_model.is_free(
            self.active_grid, self.pose["x"], self.pose["y"]
        ):
            raise ValueError("小车当前位置不在安全可行驶区内")
        targets = (
            payload["poses"]
            if name == "route" or (name == "plan" and "poses" in payload)
            else [payload]
        )
        if not isinstance(targets, list) or not 1 <= len(targets) <= 200:
            raise ValueError("需要 1–200 个目标")
        auto_heading = payload.get("auto_heading") is True
        coordinates = []
        for target in targets:
            x, y = (finite(target[k]) for k in ("x", "y"))
            if not self.active_model.is_free(self.active_grid, x, y):
                raise ValueError("终点或途径点超出可行驶区域，或位于禁行区、未知区或边界安全带内")
            coordinates.append(dict(x=x, y=y) if auto_heading else dict(x=x, y=y, yaw=finite(target["yaw"])))
        if name != "plan" and not self.motion:
            raise ValueError("启动参数未启用运动；可先使用仅规划")
        if name != "plan":
            chassis_reason = self.chassis_block_reason()
            if chassis_reason:
                raise ValueError(chassis_reason)
            odometry_reason = self.odometry_block_reason()
            if odometry_reason:
                raise ValueError(odometry_reason)
        if name != "plan" and getattr(self, "use_lidar", True) and time.monotonic() - self.scan_seen > 0.6:
            raise ValueError("激光雷达数据不可用或过期")
        if auto_heading:
            if not self.plan_client.server_is_ready():
                raise ValueError("Nav2 规划器尚未就绪，请检查生命周期及代价地图")
            search = HeadingSearch(self.plan_client, self.get_clock, self.pose, coordinates)
            self.heading_search = (search, name, "poses" in payload)
            self.operation += 1
            self.operation_started_ns = self.get_clock().now().nanoseconds
            self.busy, self.navigation, self.message = True, "规划中", "正在自动选择可行驶朝向"
            self.path = self.tracking_path = self.planned_targets = []
            self.tracking_goal = None
            return {"ok": True, "operation": self.operation}
        stamp = self.get_clock().now().to_msg()
        poses = [stamped_pose(target, stamp) for target in coordinates]
        if name == "plan":
            if "poses" in payload:
                client, goal = self.plan_route_client, ComputePathThroughPoses.Goal()
                goal.goals = poses
            else:
                client, goal = self.plan_client, ComputePathToPose.Goal()
                goal.goal = poses[0]
            goal.planner_id = "GridBased"
            # Ask Nav2 to resolve the live robot pose when planning starts.
            goal.use_start = False
        elif name == "goal":
            client, goal = self.goal_client, NavigateToPose.Goal()
            goal.pose = poses[0]
            goal.behavior_tree = getattr(self, "behavior_trees", {}).get(name, "")
        else:
            client, goal = self.route_client, NavigateThroughPoses.Goal()
            goal.poses = poses
            goal.behavior_tree = getattr(self, "behavior_trees", {}).get(name, "")
        if not client.server_is_ready():
            raise ValueError("Nav2 action 尚未就绪，请检查生命周期及代价地图")
        if not automatic:
            self.operation += 1
        self.operation_started_ns = self.get_clock().now().nanoseconds
        self.failure_detail = ""
        self.stop_reason = ""
        self.odometry_waiting = False
        self.odometry_wait_started = 0.0
        self.odometry_recovery_samples = 0
        self.tracking_path = []
        self.tracking_goal = None if name == "plan" else [poses[-1].pose.position.x, poses[-1].pose.position.y]
        self.path = []
        self.planned_targets = []
        operation = self.operation
        journal = getattr(self, "mission", None)
        if name != "plan" and journal:
            if resume_index is None:
                journal.start(targets, self.app.map_id, self.app.project, automatic=automatic)
            else:
                journal.resumed(resume_index)
        if name == "route" and journal:
            future = client.send_goal_async(goal, feedback_callback=lambda msg: self.on_route_feedback(msg, operation))
        else:
            future = client.send_goal_async(goal)
        self.busy = True
        self.navigation = "规划中" if name == "plan" else "正在接受目标"
        self.message = ""
        self.cmd_seen = 0.0
        future.add_done_callback(lambda f: self.accepted(f, operation, name))
        return {"ok": True, "operation": operation}

    def on_route_feedback(self, message, operation):
        with self.state_lock:
            if operation == self.operation:
                self.mission.feedback(message.feedback.number_of_poses_remaining)

    def accepted(self, future, operation, kind):
        with self.state_lock:
            try:
                handle = future.result()
                if operation != self.operation:
                    if handle.accepted:
                        handle.cancel_goal_async()
                    return
                if not handle.accepted:
                    raise ValueError("Nav2 拒绝目标")
                self.action_handle = handle
                if self.navigation == "取消中":
                    handle.cancel_goal_async()
                else:
                    self.navigation = "规划中" if kind == "plan" else "导航中"
                handle.get_result_async().add_done_callback(
                    lambda f: self.finished(f, operation, kind)
                )
            except Exception as exc:
                self.busy = False
                self.navigation, self.message = "任务失败", str(exc)
                if kind != "plan" and getattr(self, "mission", None):
                    self.mission.finish(False, self.message)
                self.stop()

    def finished(self, future, operation, kind):
        with self.state_lock:
            if operation != self.operation:
                return
            try:
                response = future.result()
                self.navigation = {
                    4: "规划完成" if kind == "plan" else "已到达",
                    5: "已取消",
                    6: "任务失败",
                }.get(response.status, "任务结束")
                if kind == "plan":
                    self.path = [
                        [p.pose.position.x, p.pose.position.y]
                        for p in response.result.path.poses
                    ]
                    if response.status == 4 and not self.path:
                        self.navigation = "规划失败"
                self.message = f"Nav2 状态码 {response.status}"
                if kind != "plan" and response.status == 5:
                    self.message = "任务已停止，进度已保留；点击开始导航可选择继续"
                if kind == "plan" and response.status == 6:
                    self.navigation = "规划失败"
                    self.message = self.failure_detail or "Nav2 中止规划：检查起点障碍、通道和终点朝向"
                elif response.status == 6:
                    self.message = self.failure_detail or "导航执行中止，请检查底盘状态、局部障碍及定位"
                if self.stop_reason:
                    self.navigation, self.message = "任务失败", self.stop_reason
            except Exception as exc:
                self.navigation, self.message = "任务失败", str(exc)
            self.busy, self.action_handle = False, None
            if kind != "plan" and getattr(self, "mission", None):
                self.mission.finish(self.navigation == "已到达", self.message)
                if self.navigation == "任务失败" and "碰撞风险" in self.message:
                    self.navigation = "已暂停"
                    self.message += "；任务进度已保留，点击开始导航可继续"
            self.odometry_waiting = False
            self.odometry_wait_started = 0.0
            self.odometry_recovery_samples = 0
            self.stop()
