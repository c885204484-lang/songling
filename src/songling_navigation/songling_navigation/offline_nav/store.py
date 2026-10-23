"""Immutable disk snapshots and standard ROS map exports."""

import io
import json
import os
from pathlib import Path
import tempfile
import time
import uuid
import zipfile

import yaml

from .maps import MapModel, pgm_bytes


class ProjectStore:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.loaded_revision = None

    def files(self, model, project):
        nav_model, grid = model.navigation_map(project)
        original = io.BytesIO()
        model.image.save(original, format="PPM")
        meta = model.metadata()
        base_meta = {
            k: meta[k]
            for k in (
                "resolution",
                "origin",
                "negate",
                "free_thresh",
                "occupied_thresh",
                "mode",
            )
        }
        nav_meta = dict(
            base_meta,
            resolution=nav_model.resolution,
            origin=nav_model.origin,
            negate=0,
            free_thresh=0.25,
            occupied_thresh=0.65,
        )
        if "georeference" in model.context:
            nav_meta["georeference"] = model.context["georeference"]
        base_meta.update(model.context)
        if model.display_image is not None:
            base_meta["display_image"] = "basemap.png"
        files = {
            "project.json": json.dumps(project, ensure_ascii=False, indent=2).encode(),
            "original.pgm": original.getvalue(),
            "original.yaml": yaml.safe_dump(
                dict(base_meta, image="original.pgm")
            ).encode(),
            "keepout.pgm": pgm_bytes(grid),
            "keepout.yaml": yaml.safe_dump(
                dict(nav_meta, image="keepout.pgm")
            ).encode(),
            "navigation.pgm": pgm_bytes(grid),
            "navigation.yaml": yaml.safe_dump(
                dict(nav_meta, image="navigation.pgm")
            ).encode(),
        }
        if model.display_image is not None:
            display = io.BytesIO()
            model.display_image.save(display, format="PNG")
            files["basemap.png"] = display.getvalue()
        return files

    def save(self, model, project):
        project = model.validate(project)
        files = self.files(model, project)
        revision = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
        with tempfile.TemporaryDirectory(dir=self.root) as temp:
            stage = Path(temp) / "snapshot"
            stage.mkdir()
            for name, data in files.items():
                (stage / name).write_bytes(data)
            os.replace(stage, self.root / revision)
        pointer = self.root / (".latest-" + uuid.uuid4().hex)
        pointer.write_text(json.dumps({"revision": revision}))
        os.replace(pointer, self.root / "latest.json")
        return revision

    def load(self):
        pointer = self.root / "latest.json"
        if not pointer.exists():
            return None
        revision = json.loads(pointer.read_text())["revision"]
        if Path(revision).name != revision:
            raise ValueError("无效的快照路径")
        folder = self.root / revision
        model = MapModel.load(folder / "original.yaml")
        project = model.validate(json.loads((folder / "project.json").read_text()))
        self.loaded_revision = revision
        return model, project

    def archive(self, model, project):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, data in self.files(model, project).items():
                archive.writestr(name, data)
        return output.getvalue()
