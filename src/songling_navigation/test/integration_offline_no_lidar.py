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
        api("goal", dict(x=3., y=0., yaw=0.))
        moved = wait(lambda s: s["runtime"]["pose"]["x"] > .15)
        assert moved["runtime"]["scan_age_s"] is None
        assert moved["runtime"]["guard"] == "通行", moved["runtime"]["guard"]
        api("cancel", {})
        wait(lambda s: not s["runtime"]["busy"])
        rclpy.init()
        node = rclpy.create_node("no_scan_assertion")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=.1)
        assert not node.get_publishers_info_by_topic("/scan")
        (folder / "evidence.json").write_text(json.dumps({
            "planning_points": len(path), "moving_runtime": moved["runtime"],
            "scan_publishers": 0,
        }, ensure_ascii=False, indent=2))
        print("PASS: simulated navigation moves and cancels with zero /scan publishers; evidence:", folder, flush=True)
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
