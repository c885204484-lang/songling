"""Resolve point-only routes with the same forward-motion planner used by Nav2."""

import math
import time

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import ComputePathToPose


def stamped_pose(values, stamp):
    pose = PoseStamped()
    pose.header.frame_id, pose.header.stamp = "map", stamp
    pose.pose.position.x, pose.pose.position.y = values["x"], values["y"]
    half_yaw = values["yaw"] / 2
    pose.pose.orientation.z, pose.pose.orientation.w = math.sin(half_yaw), math.cos(half_yaw)
    return pose


def angle_distance(a, b):
    return abs(math.remainder(a - b, math.tau))


def approach_tangent(path, *, from_start=False, look_distance=1.0):
    if len(path) < 2:
        return None
    points = path if from_start else path[::-1]
    x, y = points[0]
    candidate = None
    for px, py in points[1:]:
        if (distance := math.hypot(px - x, py - y)) > 1e-6:
            candidate = math.atan2(py - y, px - x) if from_start else math.atan2(y - py, x - px)
            if distance >= look_distance:
                break
    return candidate


def planned_tangents(targets, path):
    """Report the tangent of the accepted route in waypoint order."""
    if not targets:
        return []
    resolved = []
    index = 0
    for target in targets[:-1]:
        index = min(range(index, len(path)), key=lambda i: math.dist(path[i], (target["x"], target["y"])))
        incoming = approach_tangent(path[:index + 1], look_distance=0.0)
        outgoing = approach_tangent(path[index:], from_start=True, look_distance=0.0)
        resolved.append(dict(target, yaw=outgoing if outgoing is not None else incoming))
    # The final path chord gives the arrival tangent, including when it differs
    # slightly from the discrete orientation used by Smac's search.
    terminal = approach_tangent(path, look_distance=0.0)
    return resolved + [dict(targets[-1], yaw=terminal)]


def candidate_headings(start, target, following, incoming=None, outgoing=None):
    def bearing(a, b, fallback):
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        return math.atan2(dy, dx) if math.hypot(dx, dy) > 0.05 else fallback

    if incoming is None:
        incoming = bearing(start, target, start["yaw"])
    if outgoing is None:
        outgoing = bearing(target, following, incoming) if following else incoming
    tangent = incoming + math.remainder(outgoing - incoming, math.tau) / 2
    choices = [tangent, outgoing, incoming, start["yaw"]]
    for step in (1, 2, 3, 4, 6, 9, 12, 5, 7, 8, 10, 11):
        choices.extend((tangent + step * math.pi / 12, tangent - step * math.pi / 12))
    distinct = []
    for heading in choices:
        heading = math.remainder(heading, math.tau)
        if all(angle_distance(heading, previous) >= math.pi / 36 for previous in distinct):
            distinct.append(heading)
    return distinct


class HeadingSearch:
    def __init__(self, client, clock, start, targets, *, path_is_free=None):
        self.client, self.clock, self.targets = client, clock, targets
        self.path_is_free = path_is_free
        self.boundary_conflict = False
        self.search = self.route(start)
        self.attempts = 0
        self.limit = len(targets) + max(48, 2 * len(targets))
        self.deadline = time.monotonic() + min(180, 30 + 2 * len(targets))
        self.deepest = 0
        self.future = self.handle = None
        self.send_next()

    def route(self, start):
        guides = []
        previous = start
        for index, target in enumerate(self.targets):
            end = dict(target, yaw=0.0)
            guide = yield "RouteGuide", previous, end
            if not guide:
                point = "终点" if index == len(self.targets) - 1 else f"途径点 {index + 1}"
                raise ValueError(f"代价地图上未找到通往{point}的通路，请检查通道和安全边距")
            guides.append(guide)
            previous = end
        return (yield from self.segments(start, 0, guides))

    def segments(self, start, index, guides):
        self.deepest = max(self.deepest, index)
        target = self.targets[index]
        following = self.targets[index + 1] if index + 1 < len(self.targets) else None
        incoming = approach_tangent(guides[index])
        outgoing = approach_tangent(guides[index + 1], from_start=True) if following else None
        for heading in candidate_headings(start, target, following, incoming, outgoing):
            end = dict(target, yaw=heading)
            result = yield "GridBased", start, end
            if not result:
                continue
            path, actual_end = result
            resolved = dict(target, yaw=actual_end["yaw"])
            if following is None:
                return [resolved], [path]
            remaining = yield from self.segments(actual_end, index + 1, guides)
            if remaining:
                poses, paths = remaining
                poses.append(resolved)
                paths.append(path)
                return poses, paths
        return None

    def send_next(self, segment_result=None):
        try:
            planner, start, end = self.search.send(segment_result)
        except StopIteration as result:
            if result.value is not None:
                poses, paths = result.value
                joined = paths.pop()
                for segment in reversed(paths):
                    joined.extend(segment[1:] if joined[-1] == segment[0] else segment)
                return list(reversed(poses)), joined
            raise ValueError(self.failure_message()) from None
        now = time.monotonic()
        if self.attempts >= self.limit or now >= self.deadline:
            raise ValueError(self.failure_message())
        goal = ComputePathToPose.Goal()
        stamp = self.clock().now().to_msg()
        goal.use_start, goal.planner_id = True, planner
        goal.start, goal.goal = stamped_pose(start, stamp), stamped_pose(end, stamp)
        self.end = end
        self.planner = planner
        if planner == "GridBased":
            self.attempts += 1
        self.handle = None
        self.response_deadline = now + (12 if planner == "GridBased" else 6)
        self.future = self.client.send_goal_async(goal)
        return None

    def failure_message(self):
        point = "终点" if self.deepest == len(self.targets) - 1 else f"途径点 {self.deepest + 1}"
        if self.boundary_conflict:
            return f"未找到经过{point}且避开边界安全带的路径，请调整起点或者目标位置"
        return f"在当前车头方向和最小转弯半径约束下，未找到通往{point}的有效路线"

    def advance(self):
        if not self.future.done():
            if time.monotonic() >= self.response_deadline:
                raise ValueError("Nav2 规划器响应超时，请稍后重试")
            if time.monotonic() >= self.deadline:
                raise ValueError(self.failure_message())
            return None
        if self.handle is None:
            handle = self.future.result()
            if not handle.accepted:
                raise ValueError("Nav2 拒绝规划请求，请检查规划器状态")
            self.handle = handle
            self.future = handle.get_result_async()
            return None
        response = self.future.result()
        segment = None
        if response.status == GoalStatus.STATUS_SUCCEEDED and response.result.path.poses:
            path = [[p.pose.position.x, p.pose.position.y] for p in response.result.path.poses]
            if not all(math.isfinite(value) for point in path for value in point):
                return self.send_next()
            if self.planner == "RouteGuide":
                return self.send_next(path)
            last = response.result.path.poses[-1].pose
            q = last.orientation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            if (math.hypot(last.position.x - self.end["x"], last.position.y - self.end["y"]) <= 0.35
                    and angle_distance(yaw, self.end["yaw"]) <= 0.25):
                if self.path_is_free is not None and not self.path_is_free(path):
                    self.boundary_conflict = True
                else:
                    segment = path, dict(x=last.position.x, y=last.position.y, yaw=yaw)
        return self.send_next(segment)

    def cancel(self):
        if self.handle is not None:
            if not self.future.done():
                self.handle.cancel_goal_async()
        elif self.future is not None:
            def cancel_pending(future):
                if future.exception() is None and future.result().accepted:
                    future.result().cancel_goal_async()

            self.future.add_done_callback(cancel_pending)
