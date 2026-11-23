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


def candidate_headings(start, target, following):
    def bearing(a, b, fallback):
        dx, dy = b["x"] - a["x"], b["y"] - a["y"]
        return math.atan2(dy, dx) if math.hypot(dx, dy) > 0.05 else fallback

    incoming = bearing(start, target, start["yaw"])
    outgoing = bearing(target, following, incoming) if following else incoming
    tangent = incoming + math.remainder(outgoing - incoming, math.tau) / 2
    choices = [tangent, outgoing, incoming, start["yaw"]]
    for step in (3, 6, 9, 12, 1, 2, 4, 5, 7, 8, 10, 11):
        choices.extend((tangent + step * math.pi / 12, tangent - step * math.pi / 12))
    distinct = []
    for heading in choices:
        heading = math.remainder(heading, math.tau)
        if all(angle_distance(heading, previous) >= math.pi / 36 for previous in distinct):
            distinct.append(heading)
    return distinct


class HeadingSearch:
    def __init__(self, client, clock, start, targets):
        self.client, self.clock, self.targets = client, clock, targets
        self.search = self.segments(start, 0)
        self.attempts = 0
        self.limit = len(targets) + max(48, 2 * len(targets))
        self.deadline = time.monotonic() + min(180, 30 + 2 * len(targets))
        self.deepest = 0
        self.future = self.handle = None
        self.send_next()

    def segments(self, start, index):
        self.deepest = max(self.deepest, index)
        target = self.targets[index]
        following = self.targets[index + 1] if index + 1 < len(self.targets) else None
        for heading in candidate_headings(start, target, following):
            end = dict(target, yaw=heading)
            result = yield start, end
            if not result:
                continue
            path, actual_end = result
            if following is None:
                return [end], [path]
            remaining = yield from self.segments(actual_end, index + 1)
            if remaining:
                poses, paths = remaining
                poses.append(end)
                paths.append(path)
                return poses, paths
        return None

    def send_next(self, segment_result=None):
        try:
            start, end = self.search.send(segment_result)
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
        goal.use_start, goal.planner_id = True, "GridBased"
        goal.start, goal.goal = stamped_pose(start, stamp), stamped_pose(end, stamp)
        self.end = end
        self.attempts += 1
        self.handle = None
        self.response_deadline = min(now + 6, self.deadline)
        self.future = self.client.send_goal_async(goal)
        return None

    def failure_message(self):
        point = "终点" if self.deepest == len(self.targets) - 1 else f"途径点 {self.deepest + 1}"
        return f"未能为经过{point}的路线找到可行驶朝向，请调整点位或检查可行驶区和转弯空间"

    def advance(self):
        if not self.future.done():
            if time.monotonic() >= self.response_deadline:
                raise ValueError("Nav2 规划器响应超时，请稍后重试")
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
            last = response.result.path.poses[-1].pose
            q = last.orientation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            if (math.hypot(last.position.x - self.end["x"], last.position.y - self.end["y"]) <= 0.35
                    and angle_distance(yaw, self.end["yaw"]) <= 0.25):
                path = [[p.pose.position.x, p.pose.position.y] for p in response.result.path.poses]
                if all(math.isfinite(value) for point in path for value in point):
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
