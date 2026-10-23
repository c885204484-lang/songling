"""Opt-in moving-obstacle check after integration_offline_nav.py has completed."""

import json
import math
import time
import urllib.request

base = "http://127.0.0.1:8091/api/"


def api(name, payload=None):
    req = urllib.request.Request(
        base + name,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.load(r)


def state():
    return api("state")["runtime"]


def main():
    api("obstacles", {"points": []})
    api(
        "route",
        {
            "poses": [
                {"x": 28.0, "y": 0.0, "yaw": 0.0},
                {"x": 30.0, "y": 0.0, "yaw": 0.0},
            ]
        },
    )
    time.sleep(0.8)
    s = state()
    p = s["pose"]
    obstacle = [p["x"] + 0.9 * math.cos(p["yaw"]), p["y"] + 0.9 * math.sin(p["yaw"])]
    t0 = time.monotonic()
    api("obstacles", {"points": [obstacle]})
    observations = []
    stopped = None
    while time.monotonic() - t0 < 2:
        s = state()
        observations.append(s["pose"])
        if s["guard"] == "预测轨迹遇到激光障碍":
            stopped = time.monotonic() - t0
            break
        time.sleep(0.05)
    assert stopped is not None, s["guard"]
    pose = s["pose"]
    time.sleep(0.3)
    after = state()["pose"]
    assert math.dist([pose["x"], pose["y"]], [after["x"], after["y"]]) < 0.04
    print(
        "PASS: live obstacle guard reaction",
        round(stopped, 3),
        "s; robot stopped",
        flush=True,
    )
    api("obstacles", {"points": []})
    end = time.monotonic() + 45
    while time.monotonic() < end:
        s = state()
        if not s["busy"]:
            break
        time.sleep(0.15)
    assert s["navigation"] == "已到达", {
        k: v for k, v in s.items() if k not in ("scan_points", "path")
    }
    assert math.dist([s["pose"]["x"], s["pose"]["y"]], [30, 0]) < 0.5
    print("PASS: multi-waypoint route reached last goal", s["pose"], flush=True)
    open("/tmp/songling-offline-reaction-evidence.json", "w").write(
        json.dumps(
            {
                "reaction_s": stopped,
                "stop_pose": pose,
                "after_stop": after,
                "final_pose": s["pose"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
