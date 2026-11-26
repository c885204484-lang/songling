"""Opt-in map-only navigation regression on an isolated ROS domain, without /scan."""

import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.request

import rclpy
from nav_msgs.msg import Path as NavPath


def main():
    assert os.environ.get("ROS_DOMAIN_ID") == "96", "Use isolated ROS_DOMAIN_ID=96"
    folder = Path(tempfile.mkdtemp(prefix="songling-no-lidar-integration-"))
    log = open(folder / "launch.log", "w")
    process = subprocess.Popen([
        "ros2", "launch", "songling_navigation", "offline_navigation.launch.py",
        "demo:=true", "sample_map:=true", "use_lidar:=false", "enable_motion:=true",
        "port:=8096", "store:=" + str(folder / "store"),
    ], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

    def api(name, data=None):
        request = urllib.request.Request("http://127.0.0.1:8096/api/" + name,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)

    def wait(predicate, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if node:
                rclpy.spin_once(node, timeout_sec=0)
            try:
                state = api("state")
                if predicate(state):
                    return state
            except (OSError, urllib.error.URLError):
                pass
            time.sleep(.2)
        raise AssertionError("Timed out; inspect " + str(folder / "launch.log"))

    node = None
    try:
        state = wait(lambda s: s["runtime"]["pose"] and s["runtime"]["connection"]["navigator_ready"])
        assert state["runtime"]["connection"]["lidar_enabled"] is False
        assert state["runtime"]["scan_age_s"] is None
        project = state["project"]
        project["drivable"] = [[[-8., -14.], [38., -14.], [38., 14.], [-8., 14.]]]
        project["forbidden"] = [[[5., -2.], [8., -2.], [8., 2.], [5., 2.]]]
        api("project", project)
        api("apply", {})
        wait(lambda s: s["runtime"]["connection"].get("planner_map_ready"))
        time.sleep(1.2)
        try:
            api("plan", dict(x=6., y=0., yaw=0.))
            raise AssertionError("Forbidden target was accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code == 400
        api("plan", dict(x=26., y=0., yaw=0.))
        state = wait(lambda s: not s["runtime"]["busy"])
        assert state["runtime"]["navigation"] == "规划完成", state["runtime"]
        path = state["runtime"]["path"]
        assert len(path) > 50
        assert any(abs(y) > 2.8 for x, y in path if 5 <= x <= 8)
        print("PASS: map-only planning avoids the forbidden area,", len(path), "points", flush=True)
        rclpy.init()
        node = rclpy.create_node("map_only_path_assertion")
        plans = []
        node.create_subscription(NavPath, "/plan", plans.append, 10)
        wait(lambda _: node.count_publishers("/plan") > 0)
        assert not node.get_publishers_info_by_topic("/scan")

        api("goal", dict(x=3., y=0., yaw=0.))
        initial = wait(lambda s: bool(s["runtime"]["path"]))["runtime"]["path"]
        moved = wait(lambda s: s["runtime"]["pose"]["x"] > .65)["runtime"]
        assert moved["scan_age_s"] is None
        assert moved["guard"] == "通行", moved["guard"]
        assert moved["path"] == initial
        api("cancel", {})
        wait(lambda s: not s["runtime"]["busy"])
        single_goal_plans = len(plans)
        assert single_goal_plans == 1

        plans.clear()
        api("route", {"poses": [dict(x=2., y=0.), dict(x=3.5, y=0.)]})
        # Two guide paths and two feasible segment plans precede the route
        # sent to the controller. The route must stay fixed once accepted.
        started = wait(lambda s: bool(s["runtime"]["path"]) and len(plans) >= 5)["runtime"]
        initial = started["path"]
        route_plans_at_start = len(plans)
        assert len(started["planned_targets"]) == 2
        assert all(abs(target["yaw"]) < .05 for target in started["planned_targets"])
        via = wait(lambda s: s["runtime"]["mission"].get("completed") == 1)["runtime"]
        assert via["path"] == initial
        arrival = wait(lambda s: not s["runtime"]["busy"])["runtime"]
        assert arrival["navigation"] == "已到达", arrival["message"]
        assert arrival["path"] == initial
        assert len(plans) == route_plans_at_start
        (folder / "evidence.json").write_text(json.dumps({
            "planning_points": len(path), "moving_runtime": moved,
            "single_goal_plans": single_goal_plans, "route_plans": len(plans),
            "visited_waypoints_before_arrival": via["mission"]["completed"],
            "scan_publishers": 0,
        }, ensure_ascii=False, indent=2))
        print("PASS: fixed paths with zero /scan publishers; coordinate-only route recorded its waypoint and reached the goal; evidence:", folder, flush=True)
    finally:
        if node:
            node.destroy_node()
            rclpy.shutdown()
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    main()
