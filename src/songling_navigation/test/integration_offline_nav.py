"""Opt-in verification against a live, isolated demo launch (not collected by pytest).

Run after the demo launch on a fresh store:
PYTHONPATH=src/songling_navigation python3 src/songling_navigation/test/integration_offline_nav.py
"""

import argparse
import io
import json
import math
from pathlib import Path
import time
import urllib.error
import urllib.request
import zipfile

from songling_navigation.offline_nav.maps import MapModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8091")
    parser.add_argument("--output", default="/tmp/songling-offline-evidence.json")
    args = parser.parse_args()

    def api(path, payload=None):
        req = urllib.request.Request(
            args.url + "/api/" + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.load(response)

    def state():
        return api("state")["runtime"]

    def wait_idle(timeout=20):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            s = state()
            if not s["busy"]:
                return s
            time.sleep(0.2)
        raise AssertionError("Action did not complete: " + str(state()["navigation"]))

    s = state()
    assert s["pose"] and s["scan_age_s"] < 0.6
    assert s["motion_enabled"]
    project = api("state")["project"]
    project["forbidden"] = [[[5.0, -2.0], [8.0, -2.0], [8.0, 2.0], [5.0, 2.0]]]
    api("project", project)
    applied = api("apply", {})
    time.sleep(2)
    try:
        api("goal", dict(x=6.0, y=0.0, yaw=0.0))
        raise AssertionError("Forbidden target accepted")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    api("plan", dict(x=26.0, y=0.0, yaw=0.0))
    planned = wait_idle()
    assert planned["navigation"] == "规划完成", planned
    path = planned["path"]
    assert len(path) > 50
    model = MapModel.demo()
    grid = model.rasterize(project)
    assert all(model.is_free(grid, *point) for point in path)
    assert any(abs(y) > 2.8 for x, y in path if 5 <= x <= 8)
    print(
        "PASS: forbidden goal rejected; Nav2 planned",
        len(path),
        "safe points",
        flush=True,
    )

    # Insert a previously absent laser obstacle directly on the planned path.
    obstacle = path[len(path) // 4]
    api("obstacles", {"points": [obstacle]})
    time.sleep(2)
    api("plan", dict(x=26.0, y=0.0, yaw=0.0))
    replanned = wait_idle()
    assert replanned["navigation"] == "规划完成"
    distance = min(math.dist(p, obstacle) for p in replanned["path"])
    assert distance > 0.85, distance
    assert replanned["scan_age_s"] < 0.6
    print(
        "PASS: laser obstacle causes new path; clearance",
        round(distance, 3),
        flush=True,
    )

    # Exercise the full NavigateToPose -> controller -> final gate -> robot loop.
    api("goal", dict(x=26.0, y=0.0, yaw=0.0))
    samples = []
    end = time.monotonic() + 200
    report = time.monotonic()
    while time.monotonic() < end:
        s = state()
        if s["pose"]:
            p = s["pose"]
            assert model.is_free(grid, p["x"], p["y"]), p
            assert math.dist([p["x"], p["y"]], obstacle) > 0.9, p
            samples.append(p)
        if not s["busy"]:
            break
        if time.monotonic() - report >= 10:
            print("driving:", s["pose"], s["guard"], flush=True)
            report = time.monotonic()
        time.sleep(0.15)
    assert s["navigation"] == "已到达", {
        k: v for k, v in s.items() if k not in ("path", "scan_points")
    }
    assert math.dist([s["pose"]["x"], s["pose"]["y"]], [26, 0]) < 0.5
    print("PASS: full navigation reached the goal; samples", len(samples), flush=True)

    # Route and cancellation exercise the alternate action and cancellation state.
    api(
        "route", {"poses": [dict(x=28.0, y=0.0, yaw=0.0), dict(x=30.0, y=0.0, yaw=0.0)]}
    )
    time.sleep(1)
    try:
        api("apply", {})
        raise AssertionError("Map changed during navigation")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    api("cancel", {})
    cancelled = wait_idle()
    assert cancelled["navigation"] == "已取消", cancelled["navigation"]
    pose = cancelled["pose"]
    time.sleep(1)
    assert (
        math.dist([pose["x"], pose["y"]], [state()["pose"]["x"], state()["pose"]["y"]])
        < 0.05
    )
    print(
        "PASS: waypoint route accepted, map switch rejected, cancellation stops robot",
        flush=True,
    )

    with urllib.request.urlopen(args.url + "/api/export") as response:
        with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
            assert json.loads(archive.read("project.json")) == project
    evidence = dict(
        free_cells=applied["free_cells"],
        initial_path=path,
        obstacle=obstacle,
        obstacle_path_clearance=distance,
        driven_samples=samples,
        final_pose=s["pose"],
        cancellation=cancelled["navigation"],
    )
    Path(args.output).write_text(json.dumps(evidence, ensure_ascii=False, indent=2))
    print("Evidence:", args.output, flush=True)


if __name__ == "__main__":
    main()
