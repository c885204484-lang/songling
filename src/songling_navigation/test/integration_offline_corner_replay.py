"""Replay a paused field corner in simulation on ROS_DOMAIN_ID=96 (no vehicle IO)."""

import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import urllib.request

from songling_navigation.offline_nav.store import ProjectStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store", required=True)
    parser.add_argument("--collision", required=True)
    args = parser.parse_args()
    assert os.environ.get("ROS_DOMAIN_ID") == "96", "Use isolated ROS_DOMAIN_ID=96"
    model, project = ProjectStore(args.store).load()
    collision = json.loads(Path(args.collision).read_text())
    pose = collision["pose"]
    folder = Path(tempfile.mkdtemp(prefix="songling-corner-replay-"))
    store = folder / "store"
    ProjectStore(store).save(model, project)
    # Scope initial pose overrides to this isolated launch; no production launch
    # arguments or actual vehicle services are used by this test.
    wrapper = folder / "replay.launch.py"
    wrapper.write_text('''
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import SetParameter
from ament_index_python.packages import get_package_share_directory
import os
def generate_launch_description():
    return LaunchDescription([
        SetParameter(name='initial_x', value=%r),
        SetParameter(name='initial_y', value=%r),
        SetParameter(name='initial_yaw', value=%r),
        IncludeLaunchDescription(PythonLaunchDescriptionSource(os.path.join(
            get_package_share_directory('songling_navigation'),'launch','offline_navigation.launch.py')),
            launch_arguments={'demo':'true','use_lidar':'false','enable_motion':'true',
                              'port':'8096','store':%r}.items()),
    ])
''' % (pose["x"], pose["y"], pose["yaw"], str(store)))
    log = open(folder / "launch.log", "w")
    process = subprocess.Popen(["ros2", "launch", str(wrapper)], stdout=log,
        stderr=subprocess.STDOUT, start_new_session=True)

    def api(name, data=None):
        request = urllib.request.Request("http://127.0.0.1:8096/api/" + name,
            data=None if data is None else json.dumps(data).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=8) as response:
            return json.load(response)

    def wait(predicate, timeout=30):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                state = api("state")
                if predicate(state["runtime"]):
                    return state
            except OSError:
                pass
            time.sleep(.2)
        raise AssertionError("Timed out; inspect " + str(folder / "launch.log"))

    samples = []
    try:
        state = wait(lambda r: r["pose"] and r["connection"]["navigator_ready"])
        assert math.dist([state["runtime"]["pose"][k] for k in ("x", "y")],
                         [pose[k] for k in ("x", "y")]) < .05
        api("apply", {})
        wait(lambda r: r["connection"].get("planner_map_ready"))
        time.sleep(1.2)
        goals = [project["waypoints"][3], project["navigation_goal"]]
        api("route", {"poses": goals})
        end = time.monotonic() + 180
        reported = time.monotonic()
        while time.monotonic() < end:
            runtime = api("state")["runtime"]
            samples.append(runtime)
            if not runtime["busy"]:
                break
            if time.monotonic() - reported > 10:
                p = runtime["pose"]
                print(runtime["navigation"], round(p["x"], 2), round(p["y"], 2),
                      runtime["guard"], flush=True)
                reported = time.monotonic()
            time.sleep(.2)
        (folder / "evidence.json").write_text(json.dumps(samples, ensure_ascii=False))
        assert runtime["navigation"] == "已到达", runtime["message"]
        assert not any(s["collision_events"] for s in samples)
        assert all(s["scan_age_s"] is None for s in samples)
        print("PASS: exact paused pose -> waypoint 4 -> terminal, no radar, no collision events;", folder, flush=True)
    finally:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    main()
