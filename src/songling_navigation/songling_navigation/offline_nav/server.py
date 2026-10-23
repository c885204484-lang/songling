"""Local HTTP API and static editor; ROS is an optional adapter."""

import argparse
import copy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

import yaml

from .maps import MapModel, finite, image_from_upload
from .store import ProjectStore
from .registration import fit_registration, registered_document
from .geodetic import geographic_samples, projection_report, projected_document


class Application:
    def __init__(self, store, map_path=None, demo=False, sample=False):
        self.lock = threading.RLock()
        # Serialize edits and map switching, without blocking the ROS velocity loop.
        self.edit_lock = threading.Lock()
        self.store = ProjectStore(store)
        saved = self.store.load() if not map_path else None
        self.model, self.project = saved or (
            MapModel.load(map_path)
            if map_path
            else (MapModel.demo() if sample else MapModel.default_site()),
            None,
        )
        if self.project is None:
            self.project = self.model.empty_project()
            if sample and not map_path:
                self.project["drivable"] = [
                    [
                        self.model.grid_to_world(x, y)
                        for x, y in [(5, 5), (475, 5), (475, 315), (5, 315)]
                    ]
                ]
                self.project["waypoints"] = [
                    dict(id="goal", name="绕障终点", x=26.0, y=0.0, yaw=0.0)
                ]
        self.bridge = None
        self.revision = self.store.loaded_revision if saved else None
        self.map_id = self.model.fingerprint()

    def storage(self, revision):
        return dict(
            root=str(self.store.root),
            snapshot_path=str(self.store.root / revision) if revision else None,
        )

    def snapshot(self):
        with self.lock:
            result = dict(
                project=copy.deepcopy(self.project),
                revision=self.revision,
                storage=self.storage(self.revision),
                map_id=self.map_id,
            )
        # Never nest the document lock with the independent ROS state lock.
        result["runtime"] = (
            self.bridge.status()
            if self.bridge
            else {
                "mode": "editor",
                "navigation": "离线编辑",
                "message": "未连接 ROS；可编辑、保存和导出地图",
            }
        )
        return result

    def document(self):
        with self.lock:
            return self.model, copy.deepcopy(self.project)

    def update(self, project):
        with self.edit_lock:
            model, _ = self.document()
            candidate = model.validate(project)
            revision = self.store.save(model, candidate)
            with self.lock:
                self.project, self.revision = candidate, revision
            return dict(revision=revision, storage=self.storage(revision))

    def import_map(self, payload):
        # Navigation commands defer while an edit holds this lock; cancellation
        # and the velocity watchdog continue to run independently.
        with self.edit_lock:
            if self.bridge and self.bridge.status()["busy"]:
                raise ValueError("请先取消当前导航或规划")
            model = MapModel(
                image_from_upload(payload["image"]),
                yaml.safe_load(payload["yaml"]),
                image_from_upload(payload["basemap"], color=True)
                if payload.get("basemap")
                else None,
            )
            project = (
                model.validate(payload["project"])
                if payload.get("project")
                else model.empty_project()
            )
            revision = self.store.save(model, project)
            map_id = model.fingerprint()
            with self.lock:
                self.model, self.project, self.revision = model, project, revision
                self.map_id = map_id

    def registration_pose(self):
        if not self.bridge:
            raise ValueError("当前为离线编辑模式，可手工输入 ROS 坐标；实时采集需先连接 ROS")
        status = self.bridge.status()
        if status["busy"]:
            raise ValueError("请先取消导航并停稳小车，再采集对应点")
        if not status.get("pose"):
            raise ValueError("未收到有效的 map → base_link 实时定位")
        pose = status["pose"]
        return dict(
            robot=[pose["x"], pose["y"]],
            yaw=pose["yaw"],
            source="ros",
            simulated=status.get("connection", {}).get("simulated", False),
            captured_at=datetime.now(timezone.utc).isoformat(),
        )

    def register(self, payload, commit=False):
        with self.edit_lock:
            if self.bridge and self.bridge.status()["busy"]:
                raise ValueError("请先取消规划或导航，再进行地图配准")
            model, stored = self.document()
            with self.lock:
                revision = self.revision
            if payload.get("revision") != revision:
                raise ValueError("地图快照已变化，请重新载入后采点配准")
            project = model.validate(payload["project"])
            if project != stored:
                raise ValueError("请先保存当前标注，再进行地图配准")
            automatic = payload.get("method") == "geodetic_fromll"
            if automatic:
                if not self.bridge or not hasattr(self.bridge, "project_geographic"):
                    raise ValueError("自动对齐需要连接带 /fromLL 接口的 GPS 定位模块")
                samples = geographic_samples(model)
                report = projection_report(model, samples, self.bridge.project_geographic(samples))
            else:
                report = fit_registration(model, payload)
            if self.bridge and self.bridge.status().get("connection", {}).get(
                "simulated"
            ):
                report["simulated"] = True
            if not commit:
                return report
            if not automatic and payload.get("fixed_frame_confirmed") is not True:
                raise ValueError("请先确认定位 map 坐标原点及朝向已固定，重启后保持一致")
            if not report["passed"]:
                raise ValueError("需要至少一个独立检查点，且所有配准点和检查点误差均不超过允许值")
            if revision is None:
                raise ValueError("请先保存原地图快照，再另存配准地图")
            aligned, aligned_project = (projected_document if automatic else registered_document)(
                model, project, report, revision
            )
            saved_revision = self.store.save(aligned, aligned_project)
            map_id = aligned.fingerprint()
            with self.lock:
                self.model, self.project, self.revision = (
                    aligned,
                    aligned_project,
                    saved_revision,
                )
                self.map_id = map_id
        return self.snapshot()


def serve(app, host, port, assets):
    assets = Path(assets).resolve()

    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, data, content_type="application/json"):
            if content_type == "application/json":
                data = json.dumps(data, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'self'; img-src 'self' blob:; connect-src 'self'",
            )
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                path = urlsplit(self.path).path
                if path == "/api/state":
                    return self.respond(200, app.snapshot())
                if path in ("/api/map.png", "/api/export", "/api/mask.png"):
                    model, project = app.document()
                    if path == "/api/map.png":
                        return self.respond(200, model.png(), "image/png")
                    if path == "/api/export":
                        return self.respond(
                            200, app.store.archive(model, project), "application/zip"
                        )
                    import io
                    import numpy as np
                    from PIL import Image

                    grid = model.navigation_preview(project)
                    rgba = np.zeros((*grid.shape, 4), np.uint8)
                    rgba[grid != 0] = [239, 77, 86, 110]
                    out = io.BytesIO()
                    Image.fromarray(np.flipud(rgba)).save(out, format="PNG")
                    return self.respond(200, out.getvalue(), "image/png")
                filename = {
                    "/": "index.html",
                    "/app.js": "app.js",
                    "/registration.js": "registration.js",
                    "/style.css": "style.css",
                }.get(path)
                if filename:
                    kind = {
                        "html": "text/html; charset=utf-8",
                        "js": "text/javascript",
                        "css": "text/css",
                    }
                    return self.respond(
                        200,
                        (assets / filename).read_bytes(),
                        kind[filename.rsplit(".", 1)[1]],
                    )
                self.respond(404, {"error": "未找到资源"})
            except (ValueError, KeyError, TypeError) as exc:
                self.respond(400, {"error": str(exc)})

        def do_POST(self):
            # Browser mutations must originate from this local editor.
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                return self.respond(403, {"error": "拒绝跨站请求"})
            try:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("需要 application/json")
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 32 * 1024 * 1024:
                    raise ValueError("请求为空或超过 32 MB")
                payload = json.loads(
                    self.rfile.read(length), parse_float=finite, parse_constant=finite
                )
                path = urlsplit(self.path).path
                if path == "/api/project":
                    return self.respond(200, app.update(payload))
                if path == "/api/import":
                    app.import_map(payload)
                    return self.respond(200, app.snapshot())
                if path == "/api/registration/pose":
                    return self.respond(200, app.registration_pose())
                if path == "/api/registration/preview":
                    return self.respond(200, app.register(payload))
                if path == "/api/registration/save":
                    return self.respond(200, app.register(payload, commit=True))
                if path in (
                    "/api/apply",
                    "/api/plan",
                    "/api/goal",
                    "/api/route",
                    "/api/cancel",
                    "/api/obstacles",
                ):
                    if not app.bridge:
                        raise ValueError("当前为离线编辑模式，请启动 ROS 集成模式使用此功能")
                    return self.respond(
                        200, app.bridge.command(path.rsplit("/", 1)[1], payload)
                    )
                self.respond(404, {"error": "未找到接口"})
            except (
                ValueError,
                KeyError,
                TypeError,
                OSError,
                TimeoutError,
                yaml.YAMLError,
            ) as exc:
                self.respond(400, {"error": str(exc)})

        def log_message(self, fmt, *args):
            if args and not str(args[0]).startswith("GET /api/state"):
                super().log_message(fmt, *args)

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    parser = argparse.ArgumentParser(description="离线地图标注与 Nav2 工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--store",
        default=str(
            Path.home()
            / ".local/share/songling/offline_maps/xidian_hangzhou_lvxuelu177"
        ),
    )
    parser.add_argument("--map", dest="map_path")
    parser.add_argument("--ros", action="store_true")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument(
        "--sample-map",
        action="store_true",
        help="Use the synthetic regression map instead of the campus map",
    )
    parser.add_argument("--assets")
    parser.add_argument("--enable-motion", action="store_true")
    parser.add_argument("--scan-topic", default="/scan")
    options, ros_args = parser.parse_known_args()
    if options.assets:
        assets = options.assets
    else:
        local = Path(__file__).resolve().parents[2] / "web/offline_nav"
        if local.exists():
            assets = local
        else:
            from ament_index_python.packages import get_package_share_directory

            assets = (
                Path(get_package_share_directory("songling_navigation"))
                / "web/offline_nav"
            )
    app = Application(options.store, options.map_path, options.demo, options.sample_map)
    node = executor = None
    if options.ros:
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from .ros_bridge import NavigationBridge

        rclpy.init(args=ros_args)
        node = NavigationBridge(
            app, options.enable_motion, options.scan_topic, options.demo
        )
        app.bridge = node
        executor = SingleThreadedExecutor()
        executor.add_node(node)
    server = serve(app, options.host, options.port, assets)
    print(
        f"地图工作台 http://{options.host}:{options.port} | 数据目录 {app.store.root}",
        flush=True,
    )
    try:
        if executor:
            executor.spin()
        else:
            threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
        if node:
            node.stop()
            node.destroy_node()
            executor.shutdown()
            if rclpy.ok():
                rclpy.shutdown()


if __name__ == "__main__":
    main()
