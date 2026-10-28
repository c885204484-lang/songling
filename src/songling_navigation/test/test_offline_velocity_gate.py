"""Exercise fail-closed velocity checks without creating ROS participants."""

import time
from types import SimpleNamespace
from concurrent.futures import Future
import queue
import threading
import math

import pytest

pytest.importorskip("rclpy")
from geometry_msgs.msg import Twist
from geometry_msgs.msg import TransformStamped
from sensor_msgs.msg import LaserScan
from rclpy.clock import Clock, ClockType
from songling_navigation.offline_nav.maps import MapModel
from songling_navigation.offline_nav.ros_bridge import NavigationBridge
from songling_navigation.offline_nav.ros_bridge import planning_failure, distance_to_path


@pytest.mark.parametrize('text, expected', [
    ('GridBased: Starting point in lethal space!', '起点在障碍代价区内'),
    ('GridBased: failed to create plan, no valid path found.', '未找到满足车身及转弯约束的路径'),
    ('Goal occupied', '终点在障碍代价区内'),
    ('Exceeded maximum planning time', '规划搜索达到时间或迭代上限'),
])
def test_planner_logs_explain_aborted_actions(text, expected):
    assert planning_failure(text).startswith(expected)


def test_generic_abort_log_does_not_replace_specific_planner_failure():
    assert planning_failure('[compute_path_to_pose] [ActionServer] Aborting handle.') is None


def test_humble_rosout_message_updates_failure_and_ignores_old_logs():
    from rcl_interfaces.msg import Log
    data = SimpleNamespace(state_lock=threading.RLock(), operation_started_ns=2_000_000_000,
                           failure_detail='', stop_reason='', busy=False, navigation='规划失败', message='')
    log = Log()
    log.level = 30
    log.name = 'planner_server'
    log.msg = 'Starting point in lethal space!'
    log.stamp.sec = 1
    NavigationBridge.on_navigation_log(data, log)
    assert data.failure_detail == ''
    log.stamp.sec = 3
    NavigationBridge.on_navigation_log(data, log)
    assert data.message.startswith('起点在障碍代价区内')


def state():
    model = MapModel.demo()
    p = model.empty_project()
    p["drivable"] = [
        [model.grid_to_world(x, y) for x, y in [(5, 5), (475, 5), (475, 315), (5, 315)]]
    ]
    now = time.monotonic()
    command = Twist()
    command.linear.x = 0.5
    return SimpleNamespace(
        demo=True,
        motion=True,
        chassis=None,
        chassis_seen=0.0,
        stop_reason='',
        tracking_path=[[-10., 0.], [39., 0.]],
        tracking_goal=[39., 0.],
        odometry=dict(v=0., vy=0., w=0., valid=True),
        odometry_seen=now,
        active_model=model,
        active_grid=model.rasterize(p),
        busy=True,
        navigation="导航中",
        pose=dict(x=0.0, y=0.0, yaw=0.0),
        pose_seen=now,
        scan_seen=now,
        cmd_seen=now,
        cmd=command,
        scan_points=[],
    )


def test_fresh_safe_command_can_pass():
    assert NavigationBridge.velocity_block_reason(state()) == ""


def real_chassis_state():
    data = ticking_state()
    data.demo = False
    data.chassis = dict(vehicle_state=0, control_mode=1, error_code=0, linear_velocity=0.)
    data.chassis_seen = time.monotonic()
    return data


@pytest.mark.parametrize('field,value,expected', [
    ('chassis', None, '底盘反馈丢失'),
    ('chassis_seen', 0, '底盘反馈丢失'),
    ('vehicle_state', 1, '底盘急停或异常'),
    ('control_mode', 3, '底盘未处于 CAN'),
    ('error_code', 2, '底盘故障码 2'),
])
def test_chassis_loss_or_noncommandable_state_blocks_velocity(field, value, expected):
    data = real_chassis_state()
    if field in ('chassis', 'chassis_seen'):
        setattr(data, field, value)
    else:
        data.chassis[field] = value
    assert NavigationBridge.velocity_block_reason(data).startswith(expected)


def test_healthy_real_chassis_allows_other_checks_to_pass():
    assert NavigationBridge.velocity_block_reason(real_chassis_state()) == ''


def test_segment_distance_is_independent_of_path_sampling():
    assert distance_to_path(5., .2, [[0., 0.], [0., 0.], [10., 0.]]) == pytest.approx(.2)
    assert distance_to_path(11., 0., [[0., 0.], [10., 0.]]) == 1.


@pytest.mark.parametrize('change', ['stale', 'diverged', 'mismatch', 'uncertain'])
def test_local_odometry_fault_cancels_and_latches_stop(change):
    data = real_chassis_state()
    cancellations = []
    data.action_handle = SimpleNamespace(cancel_goal_async=lambda: cancellations.append(True))
    if change == 'stale':
        data.odometry_seen = 0.
    elif change == 'diverged':
        data.odometry['v'] = -20.
    elif change == 'mismatch':
        data.odometry['v'] = -.8
    else:
        data.odometry['valid'] = False
    NavigationBridge.tick(data)
    assert data.stop_reason.startswith('里程计')
    assert data.output[-1].linear.x == 0.
    assert cancellations == [True]
    data.odometry = dict(v=0., vy=0., w=0., valid=True)
    data.odometry_seen = time.monotonic()
    NavigationBridge.tick(data)
    assert data.output[-1].linear.x == 0.
    assert cancellations == [True]


def test_off_path_vehicle_stops_even_inside_drivable_area():
    data = ticking_state()
    data.pose['y'] = -.8
    NavigationBridge.tick(data)
    assert data.stop_reason.startswith('车辆偏离本次规划路径')
    assert data.output[-1].linear.x == 0.


def test_wrong_direction_command_is_blocked_before_leaving_path_corridor():
    data = ticking_state()
    data.pose['yaw'] = -math.pi / 2
    data.pose['y'] = -.1
    assert NavigationBridge.velocity_block_reason(data).startswith('预测轨迹偏离本次规划路径')
    NavigationBridge.tick(data)
    assert data.stop_reason.startswith('预测轨迹偏离本次规划路径')
    assert data.output[-1].linear.x == 0.
    data.pose['yaw'] = 0.
    NavigationBridge.tick(data)
    assert data.output[-1].linear.x == 0.


def test_no_motion_without_a_fresh_path_for_current_task():
    data = state()
    data.tracking_path = []
    assert NavigationBridge.velocity_block_reason(data) == '等待本次导航路径'


def test_replan_from_deviated_pose_cannot_erase_initial_tracking_error():
    from nav_msgs.msg import Path
    from geometry_msgs.msg import PoseStamped
    data = ticking_state()
    data.operation_started_ns = 1_000_000_000
    data.tracking_goal = [39., 0.]
    path = Path()
    path.header.frame_id = 'map'
    path.header.stamp.sec = 2
    for x, y in [[0., -.8], [39., 0.]]:
        p = PoseStamped()
        p.pose.position.x, p.pose.position.y = x, y
        path.poses.append(p)
    data.pose['y'] = -.8
    NavigationBridge.on_path(data, path)
    assert data.path[0] == [0., -.8]
    assert data.tracking_path[0] == [-10., 0.]
    NavigationBridge.tick(data)
    assert data.stop_reason.startswith('车辆偏离本次规划路径')


def test_previous_task_path_cannot_release_motion_gate():
    from nav_msgs.msg import Path
    data = ticking_state()
    data.operation_started_ns = 2_000_000_000
    data.tracking_path, data.path = [], []
    path = Path()
    path.header.frame_id = 'map'
    path.header.stamp.sec = 1
    NavigationBridge.on_path(data, path)
    assert data.tracking_path == []


def replan_message(points):
    from nav_msgs.msg import Path
    from geometry_msgs.msg import PoseStamped
    path = Path()
    path.header.frame_id = 'map'
    path.header.stamp.sec = 2
    for x, y in points:
        pose = PoseStamped()
        pose.pose.position.x, pose.pose.position.y = x, y
        path.poses.append(pose)
    return path


def test_safe_replan_updates_reference_before_following_new_curve():
    data = ticking_state()
    data.operation_started_ns = 1_000_000_000
    # The vehicle is still on the old path when Nav2 routes around an obstacle.
    path = replan_message([[0., 0.], [0., -2.], [39., 0.]])
    NavigationBridge.on_path(data, path)
    assert data.tracking_path == data.path
    assert NavigationBridge.velocity_block_reason(data) == '速度指令过期'
    # A fresh controller command follows the new route safely; the previous
    # implementation wrongly cancelled it against the original horizontal path.
    data.pose['y'], data.pose['yaw'] = -.2, -math.pi / 2
    data.cmd_seen = time.monotonic()
    assert NavigationBridge.velocity_block_reason(data) == ''


@pytest.mark.parametrize('change', ['wrong_goal', 'remote_start', 'stale_pose', 'cancelling', 'latched_fault'])
def test_unrelated_or_unsafe_replan_cannot_replace_reference(change):
    data = ticking_state()
    data.operation_started_ns = 1_000_000_000
    original = list(data.tracking_path)
    points = [[0., 0.], [0., -2.], [39., 0.]]
    if change == 'wrong_goal':
        points[-1] = [30., 0.]
    elif change == 'remote_start':
        points[0] = [2., 0.]
    elif change == 'stale_pose':
        data.pose_seen = 0.
    elif change == 'cancelling':
        data.navigation = '取消中'
    else:
        data.stop_reason = '预测轨迹偏离本次规划路径'
    NavigationBridge.on_path(data, replan_message(points))
    assert data.tracking_path == original


@pytest.mark.parametrize('value', [math.nan, -1.])
def test_invalid_odometry_covariance_is_rejected(value):
    from nav_msgs.msg import Odometry
    data = real_chassis_state()
    clock = Clock(clock_type=ClockType.ROS_TIME)
    data.get_clock = lambda: clock
    msg = Odometry()
    msg.header.stamp = clock.now().to_msg()
    msg.child_frame_id = 'base_link'
    msg.pose.covariance[0] = value
    NavigationBridge.on_odometry(data, msg)
    assert NavigationBridge.odometry_block_reason(data).startswith('里程计数值')


def odometry_sample(data):
    from nav_msgs.msg import Odometry
    clock = Clock(clock_type=ClockType.ROS_TIME)
    data.get_clock = lambda: clock
    msg = Odometry()
    msg.header.stamp = clock.now().to_msg()
    msg.child_frame_id = 'base_link'
    for i in (0, 7, 35):
        msg.twist.covariance[i] = .001
    return msg


def test_integrated_local_pose_uncertainty_does_not_block_accurate_velocity():
    data = real_chassis_state()
    msg = odometry_sample(data)
    msg.pose.covariance[0], msg.pose.covariance[7], msg.pose.covariance[35] = 2.5e9, 6.7e7, 2030.
    NavigationBridge.on_odometry(data, msg)
    assert NavigationBridge.odometry_block_reason(data) == ''
    assert NavigationBridge.velocity_block_reason(data) == ''


@pytest.mark.parametrize('axis,index', [('前向速度', 0), ('横向速度', 7), ('角速度', 35)])
def test_uncertain_control_velocity_is_still_blocked_with_explicit_axis(axis, index):
    data = real_chassis_state()
    msg = odometry_sample(data)
    msg.twist.covariance[index] = 811.
    NavigationBridge.on_odometry(data, msg)
    assert axis + '方差 811' in NavigationBridge.odometry_block_reason(data)


def test_reconnection_with_large_local_pose_covariance_does_not_bypass_velocity_consistency():
    data = real_chassis_state()
    msg = odometry_sample(data)
    msg.pose.covariance[0] = 1e11
    msg.twist.twist.linear.x = -.8
    NavigationBridge.on_odometry(data, msg)
    assert NavigationBridge.odometry_block_reason(data).startswith('里程计与底盘速度不一致')


def test_chassis_loss_cancels_navigation_and_never_resumes_on_reconnection():
    data = real_chassis_state()
    cancellations = []
    data.action_handle = SimpleNamespace(cancel_goal_async=lambda: cancellations.append(True))
    data.chassis_seen = 0
    NavigationBridge.tick(data)
    assert cancellations == [True]
    assert data.navigation == '取消中'
    assert data.stop_reason.startswith('底盘反馈丢失')
    assert data.output[-1].linear.x == 0
    data.chassis_seen = time.monotonic()
    NavigationBridge.tick(data)
    assert data.output[-1].linear.x == 0
    assert len(cancellations) == 1


def test_controller_collision_log_explains_navigation_abort():
    from rcl_interfaces.msg import Log
    data = SimpleNamespace(state_lock=threading.RLock(), operation_started_ns=1,
                           failure_detail='', stop_reason='', busy=False, navigation='任务失败', message='')
    log = Log()
    log.level, log.name = 40, 'controller_server'
    log.msg = 'RegulatedPurePursuitController detected collision ahead!'
    log.stamp.sec = 1
    NavigationBridge.on_navigation_log(data, log)
    assert data.message.startswith('控制器检测到前方碰撞风险')


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("motion", False, "运动未启用"),
        ("active_grid", None, "地图未应用"),
        ("busy", False, "未执行导航"),
        ("navigation", "取消中", "未执行导航"),
        ("pose", None, "定位不可用或过期"),
        ("scan_seen", 0.0, "激光雷达数据过期"),
        ("cmd_seen", 0.0, "速度指令过期"),
        ("scan_points", [[1.0, 0.0]], "预测轨迹遇到激光障碍"),
        ("pose", dict(x=39.0, y=0.0, yaw=0.0), "预测轨迹超出可行驶区域"),
    ],
)
def test_missing_or_unsafe_input_stops(field, value, reason):
    data = state()
    setattr(data, field, value)
    assert NavigationBridge.velocity_block_reason(data) == reason


@pytest.mark.parametrize("velocity", [float("nan"), float("inf"), 2.0])
def test_invalid_and_excessive_commands_stop(velocity):
    data = state()
    data.cmd.linear.x = velocity
    assert NavigationBridge.velocity_block_reason(data) in ("速度指令无效", "速度指令超过上限")


def ticking_state():
    data = state()
    data.app = SimpleNamespace(lock=threading.RLock(), edit_lock=threading.Lock())
    data.state_lock = threading.RLock()
    data.requests, data.urgent_requests = queue.Queue(), queue.Queue()
    data.deferred_request = None
    data.consume_scan = lambda: None
    data.velocity_block_reason = lambda: NavigationBridge.velocity_block_reason(data)
    data.output = []
    data.vel_pub = SimpleNamespace(publish=lambda msg: data.output.append(msg))
    data.action_handle = None
    data.stop = lambda: NavigationBridge.stop(data)
    data.dispatch = lambda name, payload: NavigationBridge.dispatch(data, name, payload)
    return data


def test_edit_in_progress_cannot_delay_stale_scan_stop():
    data = ticking_state()
    data.scan_seen = 0.0
    pending = Future()
    data.requests.put(("goal", {}, pending))
    with data.app.edit_lock:
        NavigationBridge.tick(data)
    assert not pending.done()
    assert data.guard_reason == "激光雷达数据过期"
    assert data.output[-1].linear.x == 0.0


def test_cancel_bypasses_save_and_pending_navigation_commands():
    data = ticking_state()
    pending, cancel = Future(), Future()
    data.requests.put(("goal", {}, pending))
    data.urgent_requests.put(("cancel", {}, cancel))
    with data.app.edit_lock:
        NavigationBridge.tick(data)
    assert cancel.result(timeout=0.1) == {"ok": True}
    assert not pending.done()
    assert data.navigation == "取消中"
    assert data.guard_reason == "未执行导航"
    assert data.output[-1].linear.x == 0.0


def test_document_reader_cannot_block_velocity_watchdog():
    data = ticking_state()
    data.scan_seen = 0.0
    with data.app.lock:
        worker = threading.Thread(target=NavigationBridge.tick, args=(data,))
        worker.start()
        worker.join(timeout=1)
        completed_while_document_locked = not worker.is_alive()
    worker.join(timeout=1)
    assert completed_while_document_locked
    assert data.output[-1].linear.x == 0.0


def test_pending_goal_and_cancel_never_wait_on_document_reader():
    data = ticking_state()
    pending, cancel = Future(), Future()
    data.requests.put(("goal", {}, pending))
    with data.app.lock:
        first = threading.Thread(target=NavigationBridge.tick, args=(data,))
        first.start()
        first.join(timeout=1)
        first_completed = not first.is_alive()
        data.urgent_requests.put(("cancel", {}, cancel))
        second = threading.Thread(target=NavigationBridge.tick, args=(data,))
        second.start()
        second.join(timeout=1)
        second_completed = not second.is_alive()
    first.join(timeout=1)
    second.join(timeout=1)
    assert first_completed and second_completed
    assert cancel.result(timeout=0.1) == {"ok": True}
    assert not pending.done()
    assert data.output[-1].linear.x == 0.0


def test_edits_preserve_apply_before_goal_order():
    data = ticking_state()
    calls = []
    data.dispatch = lambda name, payload: calls.append(name)
    for name in ["apply", "goal", "route"]:
        data.requests.put((name, {}, Future()))
    with data.app.edit_lock:
        NavigationBridge.tick(data)
        NavigationBridge.tick(data)
    NavigationBridge.tick(data)
    assert calls == ["apply", "goal", "route"]


def scan_state(ranges):
    data = ticking_state()
    clock = Clock(clock_type=ClockType.ROS_TIME)
    scan = LaserScan()
    scan.header.stamp = clock.now().to_msg()
    scan.header.frame_id = "laser"
    scan.angle_min, scan.angle_increment = -1.0, 0.1
    scan.range_min, scan.range_max = 0.1, 15.0
    scan.ranges = ranges
    transform = TransformStamped()
    transform.transform.rotation.w = 1.0
    data.tf = SimpleNamespace(lookup_transform=lambda *args: transform)
    data.get_clock = lambda: clock
    data.pending_scan = scan
    data.scan_points, data.scan_seen = [[1.0, 0.0]], 123.0
    return data, transform


@pytest.mark.parametrize(
    "ranges", [[], [math.nan], [-math.inf], [0.01, math.nan, -1.0]]
)
def test_invalid_scan_cannot_clear_obstacles_or_refresh_watchdog(ranges):
    data, _ = scan_state(ranges)
    NavigationBridge.consume_scan(data)
    assert data.scan_points == [[1.0, 0.0]]
    assert data.scan_seen == 123.0


def test_infinite_no_return_scan_is_valid_and_clears_previous_points():
    data, _ = scan_state([math.inf] * 10)
    NavigationBridge.consume_scan(data)
    assert data.scan_points == []
    assert data.scan_seen > 123.0


@pytest.mark.parametrize("field,value", [("x", math.nan), ("w", 0.0)])
def test_invalid_scan_transform_cannot_refresh_watchdog(field, value):
    data, transform = scan_state([2.0] * 10)
    if field == "x":
        transform.transform.translation.x = value
    else:
        transform.transform.rotation.w = value
    NavigationBridge.consume_scan(data)
    assert data.scan_points == [[1.0, 0.0]]
    assert data.scan_seen == 123.0


def test_unaligned_geographic_basemap_cannot_be_applied_to_real_robot():
    data = ticking_state()
    data.busy = False
    data.demo = False
    data.app.model = MapModel.demo()
    data.app.model.context["georeference"] = {"navigation_aligned": False}
    data.app.project = data.app.model.empty_project()
    with pytest.raises(ValueError, match="配准"):
        NavigationBridge.dispatch(data, "apply", {})
