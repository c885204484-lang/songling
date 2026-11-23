"""Route preview preserves waypoint poses without enabling vehicle motion."""

from concurrent.futures import Future
from types import SimpleNamespace
import math
import time

import pytest

pytest.importorskip("rclpy")
from builtin_interfaces.msg import Time
from nav2_msgs.action import ComputePathToPose, ComputePathThroughPoses
from nav_msgs.msg import Path
from action_msgs.msg import GoalStatus
from songling_navigation.offline_nav.ros_bridge import NavigationBridge
from songling_navigation.offline_nav.behavior import snapshot_navigation_trees
from songling_navigation.offline_nav.heading_search import HeadingSearch


class Planner:
    def __init__(self):
        self.goals = []

    def server_is_ready(self):
        return True

    def send_goal_async(self, goal):
        self.goals.append(goal)
        return Future()


def bridge():
    model = SimpleNamespace(is_free=lambda grid, x, y: x >= 0, resolution=0.1)
    project = {"waypoints": []}
    return SimpleNamespace(
        busy=False, active_grid=object(), active_model=model,
        source_model=model, applied_project=project,
        app=SimpleNamespace(model=model, project=project),
        applied_at=time.monotonic() - 2,
        pose=dict(x=0., y=0., yaw=0.), motion=False,
        plan_client=Planner(), plan_route_client=Planner(),
        get_clock=lambda: SimpleNamespace(
            now=lambda: SimpleNamespace(to_msg=Time, nanoseconds=1)),
        operation=0, accepted=lambda *args: None,
        planner_sync=SimpleNamespace(ready_for=lambda resolution: True),
    )


def test_route_preview_keeps_order_and_individual_headings_with_motion_disabled():
    data = bridge()
    poses = [dict(x=2., y=1., yaw=math.pi / 2),
             dict(x=4., y=-1., yaw=-math.pi / 3)]
    NavigationBridge.dispatch(data, "plan", {"poses": poses})
    assert not data.plan_client.goals
    goal = data.plan_route_client.goals[0]
    assert isinstance(goal, ComputePathThroughPoses.Goal)
    assert goal.use_start is False
    assert goal.planner_id == "GridBased"
    for actual, expected in zip(goal.goals, poses):
        assert actual.header.frame_id == "map"
        assert actual.pose.position.x == expected["x"]
        assert actual.pose.position.y == expected["y"]
        assert actual.pose.orientation.z == pytest.approx(math.sin(expected["yaw"] / 2))
        assert actual.pose.orientation.w == pytest.approx(math.cos(expected["yaw"] / 2))
    assert len(goal.goals) == 2
    assert data.navigation == "规划中"
    assert data.tracking_goal is None


def test_single_goal_preview_still_uses_single_pose_planner():
    data = bridge()
    NavigationBridge.dispatch(data, "plan", dict(x=2., y=1., yaw=0.))
    assert isinstance(data.plan_client.goals[0], ComputePathToPose.Goal)
    assert not data.plan_route_client.goals


def test_point_only_preview_uses_planner_without_sending_navigation():
    data = bridge()
    data.goal_client = Planner()
    NavigationBridge.dispatch(data, "plan", {"auto_heading": True, "x": 2., "y": 1.})
    attempt = data.plan_client.goals[0]
    assert attempt.use_start is True
    assert attempt.start.pose.position.x == 0.
    assert attempt.goal.pose.position.x == 2.
    assert data.busy and data.navigation == "规划中"
    assert not data.goal_client.goals


def test_automatic_headings_revisit_waypoint_when_next_segment_is_blocked():
    class SegmentPlanner(Planner):
        def send_goal_async(self, goal):
            accepted = super().send_goal_async(goal)
            result = Future()
            blocked = goal.start.pose.position.x == 2. and abs(goal.start.pose.orientation.z) < 0.1
            result.set_result(SimpleNamespace(
                status=GoalStatus.STATUS_ABORTED if blocked else GoalStatus.STATUS_SUCCEEDED,
                result=SimpleNamespace(path=Path(poses=[goal.start, goal.goal])),
            ))
            accepted.set_result(SimpleNamespace(accepted=True, get_result_async=lambda: result))
            return accepted

    data = bridge()
    search = HeadingSearch(SegmentPlanner(), data.get_clock, data.pose, [
        dict(x=2., y=0.), dict(x=4., y=0.),
    ])
    for _ in range(60):
        result = search.advance()
        if result:
            break
    assert result is not None
    targets, path = result
    assert targets[0]["yaw"] == pytest.approx(math.pi / 4)
    assert path == [[0., 0.], [2., 0.], [4., 0.]]


def test_preview_waits_for_planner_resolution_refresh():
    data = bridge()
    data.planner_sync.ready_for = lambda resolution: False
    with pytest.raises(ValueError, match="同步规划器"):
        NavigationBridge.dispatch(data, "plan", dict(x=2., y=1., yaw=0.))
    assert not data.plan_client.goals


def test_current_satellite_map_can_preview_and_start_without_registration_gate():
    data = bridge()
    data.source_model.context = {"georeference": {"registration": {"accuracy_verified": False}}}
    NavigationBridge.dispatch(data, "plan", dict(x=2., y=1., yaw=0.))
    assert data.plan_client.goals
    data = bridge()
    data.motion = True
    data.source_model.context = {"georeference": {"registration": {"accuracy_verified": False}}}
    data.chassis_block_reason = lambda: ''
    data.odometry_block_reason = lambda: ''
    data.scan_seen = time.monotonic()
    data.goal_client = Planner()
    NavigationBridge.dispatch(data, "goal", dict(x=2., y=1., yaw=0.))
    assert data.goal_client.goals
    assert data.navigation == '正在接受目标'
    assert not data.plan_client.goals


def test_changed_tree_gets_a_new_filename_without_replacing_cached_xml(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for filename in ('offline_to_pose.xml', 'offline_through_poses.xml'):
        (source / filename).write_text('<root>original</root>')
    old = snapshot_navigation_trees(source, tmp_path / 'cache')
    (source / 'offline_through_poses.xml').write_text('<root>updated</root>')
    new = snapshot_navigation_trees(source, tmp_path / 'cache')
    assert new['goal'] == old['goal']
    assert new['route'] != old['route']
    from pathlib import Path
    assert Path(old['route']).read_text() == '<root>original</root>'
    assert Path(new['route']).read_text() == '<root>updated</root>'


def test_route_navigation_selects_current_behavior_tree_snapshot():
    data = bridge()
    data.motion = True
    data.chassis_block_reason = lambda: ''
    data.odometry_block_reason = lambda: ''
    data.scan_seen = time.monotonic()
    data.route_client = Planner()
    data.behavior_trees = {'route': '/tmp/route-current.xml'}
    NavigationBridge.dispatch(data, 'route', {'poses': [dict(x=2., y=1., yaw=0.)]})
    assert data.route_client.goals[0].behavior_tree == '/tmp/route-current.xml'


@pytest.mark.parametrize("poses", [[], None, [dict(x=1., y=0., yaw=0.)] * 201])
def test_invalid_route_preview_rejected(poses):
    data = bridge()
    with pytest.raises(ValueError, match="1–200"):
        NavigationBridge.dispatch(data, "plan", {"poses": poses})
    assert not data.plan_route_client.goals


def test_route_preview_checks_every_waypoint_for_obstacles():
    data = bridge()
    with pytest.raises(ValueError, match="禁行区"):
        NavigationBridge.dispatch(data, "plan", {"poses": [
            dict(x=1., y=0., yaw=0.), dict(x=-1., y=0., yaw=0.)]})
    assert not data.plan_route_client.goals


def test_resume_sends_only_remaining_goals_and_keeps_task_identity():
    from songling_navigation.offline_nav.mission import MissionJournal
    data = bridge()
    data.motion = True
    data.chassis_block_reason = lambda: ''
    data.odometry_block_reason = lambda: ''
    data.scan_seen = time.monotonic()
    project = dict(waypoints=[dict(x=i+1., y=0., yaw=0., name=f'航点 {i+1}') for i in range(4)],
                   navigation_goal=dict(x=8.,y=0.,yaw=1.),drivable=[],forbidden=[],clearance_m=.65)
    data.app.project = data.applied_project = project
    data.app.map_id = 'test-map'
    data.mission = MissionJournal()
    data.mission.start(project['waypoints']+[project['navigation_goal']], 'test-map', project)
    data.mission.feedback(2)
    data.mission.finish(False,'collision')
    task_id = data.mission.data['task_id']
    class FeedbackPlanner(Planner):
        def send_goal_async(self, goal, feedback_callback=None):
            self.feedback = feedback_callback
            return super().send_goal_async(goal)
    data.route_client = FeedbackPlanner()
    NavigationBridge.dispatch(data,'resume',dict(task_id=task_id))
    action = data.route_client.goals[0]
    assert len(action.poses)==2
    assert [p.pose.position.x for p in action.poses]==[4.,8.]
    assert data.mission.data['task_id']==task_id
    assert data.mission.data['next_index']==3
    assert data.route_client.feedback is not None
