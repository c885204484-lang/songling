"""Regression coverage for region constraints, map formats, and durable HTTP edits."""

import base64
import copy
import io
import json
import math
from pathlib import Path
import urllib.error
import urllib.request
import zipfile
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image
import pytest
import yaml

from songling_navigation.offline_nav.maps import MapModel
from songling_navigation.offline_nav.server import Application, serve
from songling_navigation.offline_nav.store import ProjectStore


def open_project(model):
    p = model.empty_project()
    p["clearance_m"] = 0.0
    p["drivable"] = [
        [
            model.grid_to_world(x, y)
            for x, y in [
                (0, 0),
                (model.width, 0),
                (model.width, model.height),
                (0, model.height),
            ]
        ]
    ]
    return p


def small_model(origin=(0.0, 0.0, 0.0)):
    return MapModel(
        Image.fromarray(np.full((40, 60), 254, np.uint8)),
        dict(resolution=0.1, origin=origin),
    )


def test_nothing_is_drivable_until_annotated():
    m = small_model()
    assert np.all(m.rasterize(m.empty_project()) == 100)


def test_forbidden_overrides_drivable_and_other_drivable_polygons():
    m = small_model()
    p = open_project(m)
    p["forbidden"] = [[[2, 1], [4, 1], [4, 3], [2, 3]]]
    p["drivable"].append([[1, 0.5], [5, 0.5], [5, 3.5], [1, 3.5]])
    grid = m.rasterize(p)
    assert m.is_free(grid, 1.0, 2.0)
    assert not m.is_free(grid, 3.0, 2.0)
    assert not m.is_free(grid, -0.01, 2.0)
    assert not m.is_free(grid, 6.0, 2.0)


def test_unknown_and_original_obstacles_cannot_be_painted_free():
    pixels = np.full((40, 60), 254, np.uint8)
    pixels[12:18, 12:18] = 0
    pixels[24:30, 32:38] = 205
    m = MapModel(Image.fromarray(pixels), dict(resolution=0.1, origin=[0, 0, 0]))
    grid = m.rasterize(open_project(m))
    assert np.all(grid[m.base != 0] == 100)
    assert np.count_nonzero(grid == 0) > 1000


def test_clearance_closes_narrow_corridor_and_shrinks_boundaries():
    m = small_model()
    p = open_project(m)
    p["drivable"] = [[[1, 0], [2, 0], [2, 4], [1, 4]]]
    p["clearance_m"] = 0.65
    assert np.all(m.rasterize(p) == 100)
    p = open_project(m)
    p["clearance_m"] = 0.65
    grid = m.rasterize(p)
    assert not m.is_free(grid, 0.4, 2)
    assert m.is_free(grid, 1, 2)


@pytest.mark.parametrize("yaw", [0, 0.7, -math.pi / 2])
def test_rotated_map_coordinates_and_masks(yaw):
    m = small_model((12.0, -8.0, yaw))
    p = open_project(m)
    grid = m.rasterize(p)
    for gx, gy in [(1.5, 2.5), (30.5, 20.5), (58.5, 38.5)]:
        point = m.grid_to_world(gx, gy)
        assert m.world_to_grid(*point) == pytest.approx([gx, gy])
        assert m.is_free(grid, *point)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(clearance_m=float("nan")),
        lambda p: p.update(drivable=[[[0, 0], [1, 1]]]),
        lambda p: p.update(waypoints=[dict(id="bad", x=100, y=0, yaw=0)]),
        lambda p: p["map"].update(resolution=2),
    ],
)
def test_invalid_edits_rejected(mutate):
    m = small_model()
    p = open_project(m)
    mutate(p)
    with pytest.raises(ValueError):
        m.rasterize(p)


@pytest.mark.parametrize("yaw", [0.4, 1.2, -math.pi / 2])
def test_navigation_normalizes_rotation_without_opening_blocked_cells(yaw):
    m = small_model((3.0, -7.0, yaw))
    p = open_project(m)
    original_grid = m.rasterize(p)
    nav, grid = m.navigation_map(p)
    assert nav.origin[2] == 0.0
    assert (grid == 0).any()
    for gy, gx in np.argwhere(grid == 0)[::30]:
        for dx, dy in [
            (0, 0),
            (-0.49, -0.49),
            (0.49, 0.49),
            (-0.49, 0.49),
            (0.49, -0.49),
        ]:
            assert m.is_free(
                original_grid, *nav.grid_to_world(gx + 0.5 + dx, gy + 0.5 + dy)
            )
    preview = m.navigation_preview(p)
    assert preview.shape == m.base.shape
    for gy, gx in np.argwhere(preview == 0)[::30]:
        assert nav.is_free(grid, *m.grid_to_world(gx + 0.5, gy + 0.5))


def test_portable_export_preserves_original_pixels_and_occupancy_orientation(tmp_path):
    pixels = np.full((40, 60), 254, np.uint8)
    pixels[1:5, 10:20] = 0
    pixels[20:25, 40:45] = 205
    m = MapModel(Image.fromarray(pixels), dict(resolution=0.1, origin=[3, -7, 0.4]))
    p = open_project(m)
    store = ProjectStore(tmp_path / "snapshots")
    revision = store.save(m, p)
    archive = store.archive(m, p)
    unpacked = tmp_path / "moved"
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        assert len(z.namelist()) == 7
        z.extractall(unpacked)
    original = MapModel.load(unpacked / "original.yaml")
    navigation = MapModel.load(unpacked / "navigation.yaml")
    assert np.array_equal(np.asarray(original.image), pixels)
    assert np.array_equal(original.base, m.base)
    nav_model, nav_grid = m.navigation_map(p)
    assert navigation.origin == nav_model.origin
    assert navigation.origin[2] == 0.0
    assert np.array_equal(navigation.base, nav_grid)
    for gy, gx in np.argwhere(nav_grid == 0)[::20]:
        assert m.is_free(m.rasterize(p), *nav_model.grid_to_world(gx + 0.5, gy + 0.5))
    assert (tmp_path / "snapshots" / revision / "original.pgm").exists()
    restored_m, restored_p = ProjectStore(tmp_path / "snapshots").load()
    assert restored_p == p
    assert np.array_equal(restored_m.base, m.base)


def test_saves_retain_prior_snapshots_and_failed_save_keeps_latest(tmp_path):
    m = small_model()
    p = open_project(m)
    store = ProjectStore(tmp_path)
    first = store.save(m, p)
    p["waypoints"] = [dict(id="one", name="航点", x=2, y=2, yaw=0)]
    second = store.save(m, p)
    bad = copy.deepcopy(p)
    bad["clearance_m"] = -1
    with pytest.raises(ValueError):
        store.save(m, bad)
    assert first != second
    assert (tmp_path / first / "project.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text())["revision"] == second
    assert store.load()[1] == p


def test_http_edit_import_export_and_restart(tmp_path):
    app = Application(tmp_path / "data", demo=True, sample=True)
    assets = Path(__file__).resolve().parents[1] / "web/offline_nav"
    server = serve(app, "127.0.0.1", 0, assets)
    base = "http://127.0.0.1:" + str(server.server_port)

    def request(path, payload=None, origin=None):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            base + path,
            data=json.dumps(payload).encode() if payload is not None else None,
            headers=headers,
        )
        return urllib.request.urlopen(req)

    try:
        with request("/") as r:
            assert "地图工作台".encode() in r.read()
        state = json.load(request("/api/state"))
        project = state["project"]
        project["waypoints"].append(dict(id="new", name="测试", x=3, y=4, yaw=0.3))
        assert json.load(request("/api/project", project))["revision"]
        assert request("/api/mask.png").read().startswith(b"\x89PNG")
        assert json.load(request("/api/state"))["project"] == project
        with zipfile.ZipFile(io.BytesIO(request("/api/export").read())) as z:
            assert json.loads(z.read("project.json")) == project
            payload = dict(
                yaml=z.read("original.yaml").decode(),
                image=base64.b64encode(z.read("original.pgm")).decode(),
                project=project,
            )
        assert json.load(request("/api/import", payload))["project"] == project
        with pytest.raises(urllib.error.HTTPError) as error:
            request("/api/project", project, origin="http://untrusted.example")
        assert error.value.code == 403
        with pytest.raises(urllib.error.HTTPError) as error:
            request("/api/goal", {"x": 2, "y": 2, "yaw": 0})
        assert error.value.code == 400
        assert Application(tmp_path / "data").project == project
    finally:
        server.shutdown()
        server.server_close()


def test_slow_save_does_not_block_document_reads(tmp_path, monkeypatch):
    app = Application(tmp_path / "data", demo=True, sample=True)
    project = copy.deepcopy(app.project)
    project["waypoints"][0]["name"] = "保存中的新名称"
    entered, release = threading.Event(), threading.Event()
    original_save = app.store.save

    def slow_save(model, candidate):
        entered.set()
        assert release.wait(3)
        return original_save(model, candidate)

    monkeypatch.setattr(app.store, "save", slow_save)
    with ThreadPoolExecutor(2) as pool:
        writer = pool.submit(app.update, project)
        try:
            assert entered.wait(1)
            reader = pool.submit(app.snapshot)
            snapshot = reader.result(timeout=1)
            assert snapshot["project"]["waypoints"][0]["name"] == "绕障终点"
        finally:
            release.set()
        assert writer.result(timeout=3)["revision"]
    assert app.snapshot()["project"] == project


def test_slow_http_export_does_not_block_status_poll(tmp_path, monkeypatch):
    app = Application(tmp_path / "data", demo=True, sample=True)
    assets = Path(__file__).resolve().parents[1] / "web/offline_nav"
    entered, release = threading.Event(), threading.Event()
    original_archive = app.store.archive

    def slow_archive(model, project):
        entered.set()
        assert release.wait(3)
        return original_archive(model, project)

    monkeypatch.setattr(app.store, "archive", slow_archive)
    server = serve(app, "127.0.0.1", 0, assets)
    base = "http://127.0.0.1:" + str(server.server_port)

    def get(path):
        with urllib.request.urlopen(base + path, timeout=2) as response:
            return response.read()

    try:
        with ThreadPoolExecutor(2) as pool:
            download = pool.submit(get, "/api/export")
            try:
                assert entered.wait(1)
                heartbeat = pool.submit(get, "/api/state")
                assert json.loads(heartbeat.result(timeout=1))["project"] == app.project
            finally:
                release.set()
            assert download.result(timeout=3).startswith(b"PK")
    finally:
        release.set()
        server.shutdown()
        server.server_close()


def test_default_map_is_xidian_new_campus_with_real_color_basemap(tmp_path):
    app = Application(tmp_path / "campus")
    meta = app.model.metadata()
    assert meta["site"]["id"] == "xidian_hangzhou_lvxuelu177"
    assert "旅学路177号" in meta["site"]["address"]
    assert meta["has_basemap"]
    assert meta["site"]["basemap_type"] == "satellite"
    assert app.model.image.size == (1600, 1600)
    assert np.asarray(app.model.display_image).std() > 20
    assert app.project["drivable"] == []
    assert app.project["waypoints"] == []
    assert np.all(app.model.rasterize(app.project) == 100)
    assert meta["georeference"]["navigation_aligned"] is False


def color_map():
    pixels = np.full((40, 60), 254, np.uint8)
    display = np.zeros((40, 60, 3), np.uint8)
    display[:20] = [10, 160, 50]
    display[20:] = [180, 20, 90]
    return MapModel(
        Image.fromarray(pixels),
        dict(
            resolution=0.1,
            origin=[0.0, 0.0, 0.0],
            display_image="basemap.png",
            site={"name": "彩色地图"},
            georeference={"navigation_aligned": False},
        ),
        Image.fromarray(display),
    )


def test_color_basemap_survives_save_export_and_restore(tmp_path):
    model = color_map()
    project = open_project(model)
    store = ProjectStore(tmp_path / "snapshots")
    store.save(model, project)
    restored, restored_project = store.load()
    assert restored.metadata() == model.metadata()
    assert restored_project == project
    assert restored.png() == model.png()
    assert np.array_equal(restored.base, model.base)
    with zipfile.ZipFile(io.BytesIO(store.archive(model, project))) as archive:
        assert "basemap.png" in archive.namelist()
        assert (
            yaml.safe_load(archive.read("original.yaml"))["display_image"]
            == "basemap.png"
        )
        assert (
            yaml.safe_load(archive.read("navigation.yaml"))["georeference"][
                "navigation_aligned"
            ]
            is False
        )


def test_import_preserves_color_basemap_and_georeference(tmp_path):
    model = color_map()
    project = open_project(model)
    app = Application(tmp_path / "data", sample=True)
    with zipfile.ZipFile(io.BytesIO(app.store.archive(model, project))) as archive:
        payload = dict(
            yaml=archive.read("original.yaml").decode(),
            image=base64.b64encode(archive.read("original.pgm")).decode(),
            basemap=base64.b64encode(archive.read("basemap.png")).decode(),
            project=project,
        )
    app.import_map(payload)
    assert app.model.png() == model.png()
    assert app.project == project
    del payload["basemap"]
    with pytest.raises(ValueError, match="彩色底图"):
        app.import_map(payload)
