"""Map coordinates and conservative annotation rasterization (no ROS imports)."""

import base64
import copy
import io
import hashlib
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import yaml

MAX_CELLS = 4_000_000
MAX_NAV_CELLS = 2 * MAX_CELLS


def finite(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("坐标或参数必须是有限数值")
    return value


class MapModel:
    """Image rows point down; occupancy rows and project coordinates point up."""

    def __init__(self, image, metadata, display_image=None, *, max_cells=MAX_CELLS):
        if not isinstance(metadata, dict):
            raise ValueError("地图 YAML 必须为包含 resolution 和 origin 的对象")
        self.width, self.height = image.size
        if self.width * self.height > max_cells:
            raise ValueError(f"地图最多支持 {max_cells // 10_000} 万栅格")
        self.image = image.convert("L")
        self.display_image = (
            display_image.convert("RGB") if display_image is not None else None
        )
        if (
            self.display_image is not None
            and self.display_image.size != self.image.size
        ):
            raise ValueError("彩色底图与栅格地图尺寸不一致")
        if metadata.get("display_image") and self.display_image is None:
            raise ValueError("该地图需要彩色底图，请同时导入 basemap.png")
        self.context = {
            k: copy.deepcopy(metadata[k])
            for k in ("site", "georeference")
            if k in metadata
        }
        if any(not isinstance(value, dict) for value in self.context.values()):
            raise ValueError("site 和 georeference 必须为对象")
        self.resolution = finite(metadata["resolution"])
        if not 0.01 <= self.resolution <= 10:
            raise ValueError("分辨率应在 0.01–10 米之间")
        self.origin = [finite(v) for v in metadata["origin"]]
        if len(self.origin) != 3:
            raise ValueError("origin 必须为 [x, y, yaw]")
        if metadata.get("mode", "trinary") != "trinary":
            raise ValueError("目前支持 trinary 栅格地图")
        self.negate = int(metadata.get("negate", 0))
        self.free_thresh = finite(metadata.get("free_thresh", 0.25))
        self.occupied_thresh = finite(metadata.get("occupied_thresh", 0.65))
        if (
            self.negate not in (0, 1)
            or not 0 <= self.free_thresh < self.occupied_thresh <= 1
        ):
            raise ValueError("地图阈值或 negate 无效")
        pixels = np.flipud(np.asarray(self.image)).astype(float) / 255
        occupancy = pixels if self.negate else 1 - pixels
        self.base = np.full(pixels.shape, -1, dtype=np.int8)
        self.base[occupancy < self.free_thresh] = 0
        self.base[occupancy > self.occupied_thresh] = 100

    @classmethod
    def load(cls, filename):
        filename = Path(filename).expanduser().resolve()
        meta = yaml.safe_load(filename.read_text())
        if not isinstance(meta, dict):
            raise ValueError("地图 YAML 必须为对象")
        display = None
        if meta.get("display_image"):
            with Image.open(filename.parent / meta["display_image"]) as photo:
                display = photo.convert("RGB")
        with Image.open(filename.parent / meta["image"]) as image:
            return cls(image, meta, display)

    @classmethod
    def default_site(cls):
        local = Path(__file__).resolve().parents[2] / "maps/xidian_hangzhou/map.yaml"
        if not local.exists():
            from ament_index_python.packages import get_package_share_directory

            local = (
                Path(get_package_share_directory("songling_navigation"))
                / "maps/xidian_hangzhou/map.yaml"
            )
        return cls.load(local)

    @classmethod
    def demo(cls):
        pixels = np.full((320, 480), 254, np.uint8)
        pixels[:3] = pixels[-3:] = 0
        pixels[:, :3] = pixels[:, -3:] = 0
        pixels[100:220, 215:245] = 0
        return cls(
            Image.fromarray(pixels), {"resolution": 0.1, "origin": [-8.0, -16.0, 0.0]}
        )

    def metadata(self):
        result = dict(
            width=self.width,
            height=self.height,
            resolution=self.resolution,
            origin=self.origin,
            frame_id="map",
            negate=self.negate,
            free_thresh=self.free_thresh,
            occupied_thresh=self.occupied_thresh,
            mode="trinary",
        )
        result.update(copy.deepcopy(self.context))
        if self.display_image is not None:
            result["has_basemap"] = True
        return result

    def png(self):
        output = io.BytesIO()
        (self.display_image if self.display_image is not None else self.image).save(
            output, format="PNG"
        )
        return output.getvalue()

    def fingerprint(self):
        """Stable identity for browser drafts without changing saved map metadata."""
        digest = hashlib.sha256()
        digest.update(
            str((self.width, self.height, self.resolution, self.origin)).encode()
        )
        digest.update(self.image.tobytes())
        if self.display_image is not None:
            digest.update(self.display_image.tobytes())
        return digest.hexdigest()

    def world_to_grid(self, x, y):
        x, y = finite(x) - self.origin[0], finite(y) - self.origin[1]
        c, s = math.cos(self.origin[2]), math.sin(self.origin[2])
        return ((c * x + s * y) / self.resolution, (-s * x + c * y) / self.resolution)

    def grid_to_world(self, x, y):
        c, s = math.cos(self.origin[2]), math.sin(self.origin[2])
        x, y = x * self.resolution, y * self.resolution
        return [self.origin[0] + c * x - s * y, self.origin[1] + s * x + c * y]

    def empty_project(self):
        return dict(
            schema_version=1,
            map=self.metadata(),
            clearance_m=0.65,
            drivable=[],
            forbidden=[],
            waypoints=[],
        )

    def validate(self, project):
        if not isinstance(project, dict):
            raise ValueError("标注项目必须是 JSON 对象")
        p = copy.deepcopy(project)
        if p.get("schema_version") != 1 or p.get("map") != self.metadata():
            raise ValueError("项目版本或地图元数据不匹配，请重新载入地图")
        p["clearance_m"] = finite(p["clearance_m"])
        if not 0 <= p["clearance_m"] <= 5:
            raise ValueError("安全边距应在 0–5 米之间")
        for kind in ("drivable", "forbidden"):
            if not isinstance(p[kind], list) or len(p[kind]) > 200:
                raise ValueError("每种区域最多 200 个多边形")
            for polygon in p[kind]:
                if not 3 <= len(polygon) <= 500:
                    raise ValueError("多边形需要 3–500 个顶点")
                points = []
                for point in polygon:
                    if len(point) != 2:
                        raise ValueError("顶点必须为 [x, y]")
                    gx, gy = self.world_to_grid(*point)
                    if not (
                        -1e-7 <= gx <= self.width + 1e-7
                        and -1e-7 <= gy <= self.height + 1e-7
                    ):
                        raise ValueError("区域顶点超出地图")
                    points.append(
                        [min(self.width, max(0.0, gx)), min(self.height, max(0.0, gy))]
                    )
                contour = np.asarray(points, dtype=np.float32)
                if abs(cv2.contourArea(contour)) < 1:
                    raise ValueError("多边形面积太小")
        if not isinstance(p["waypoints"], list) or len(p["waypoints"]) > 200:
            raise ValueError("最多 200 个航点")
        ids = set()
        for wp in p["waypoints"]:
            wp["id"] = str(wp["id"])[:80]
            if wp["id"] in ids:
                raise ValueError("航点 ID 重复")
            ids.add(wp["id"])
            wp["name"] = str(wp.get("name", wp["id"]))[:80]
            for key in ("x", "y", "yaw"):
                wp[key] = finite(wp[key])
            gx, gy = self.world_to_grid(wp["x"], wp["y"])
            if not (0 <= gx < self.width and 0 <= gy < self.height):
                raise ValueError("航点超出地图")
        return p

    def rasterize(self, project):
        p = self.validate(project)
        allowed = np.zeros(self.base.shape, np.uint8)
        for kind, value in (("drivable", 1), ("forbidden", 0)):
            for polygon in p[kind]:
                points = np.asarray([self.world_to_grid(*v) for v in polygon])
                cv2.fillPoly(
                    allowed,
                    [
                        np.floor(
                            np.clip(points, [0, 0], [self.width, self.height]) + 1e-8
                        ).astype(np.int32)
                    ],
                    value,
                )
        # Unknown and occupied source cells always remain blocked.
        allowed[self.base != 0] = 0
        padded = np.pad(allowed, 1)
        distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[
            1:-1, 1:-1
        ]
        # Account for the diagonal from each sampled cell centre to its edge.
        safe = (allowed > 0) & (
            distance * self.resolution
            > p["clearance_m"] + self.resolution * math.sqrt(2) / 2
        )
        return np.where(safe, 0, 100).astype(np.int8)

    def is_free(self, grid, x, y):
        gx, gy = self.world_to_grid(x, y)
        return (
            0 <= gx < self.width
            and 0 <= gy < self.height
            and grid[int(gy), int(gx)] == 0
        )

    def navigation_map(self, project):
        """Nav2 costmaps are axis aligned; conservatively resample rotated inputs."""
        grid = self.rasterize(project)
        if abs(math.remainder(self.origin[2], 2 * math.pi)) < 1e-9:
            return self, grid
        corners = np.asarray(
            [
                self.grid_to_world(x, y)
                for x, y in [
                    (0, 0),
                    (self.width, 0),
                    (self.width, self.height),
                    (0, self.height),
                ]
            ]
        )
        origin = np.floor(corners.min(axis=0) / self.resolution) * self.resolution
        size = np.ceil((corners.max(axis=0) - origin) / self.resolution).astype(int)
        width, height = map(int, size)
        if width * height > MAX_NAV_CELLS:
            raise ValueError("旋转后的导航地图超过 800 万栅格，请裁剪原图")
        x = origin[0] + (np.arange(width) + 0.5) * self.resolution
        y = origin[1] + (np.arange(height) + 0.5) * self.resolution
        xs, ys = np.meshgrid(x - self.origin[0], y - self.origin[1])
        c, s = math.cos(self.origin[2]), math.sin(self.origin[2])
        gx = np.floor((c * xs + s * ys) / self.resolution).astype(int)
        gy = np.floor((-s * xs + c * ys) / self.resolution).astype(int)
        valid = (gx >= 0) & (gy >= 0) & (gx < self.width) & (gy < self.height)
        # Require the source neighbours to be free too, so the whole target cell
        # is contained in free source cells rather than just its centre.
        safe = cv2.erode(
            (grid == 0).astype(np.uint8),
            np.ones((3, 3), np.uint8),
            borderType=cv2.BORDER_CONSTANT,
            borderValue=0,
        )
        output = np.full((height, width), 100, np.int8)
        output[valid] = np.where(safe[gy[valid], gx[valid]], 0, 100)
        model = MapModel(
            Image.fromarray(np.flipud(np.where(output == 0, 254, 0)).astype(np.uint8)),
            dict(resolution=self.resolution, origin=[*origin.tolist(), 0.0]),
            max_cells=MAX_NAV_CELLS,
        )
        return model, output

    def navigation_preview(self, project):
        """Sample the published navigation grid in the original image geometry."""
        nav, grid = self.navigation_map(project)
        if nav is self:
            return grid
        xs, ys = np.meshgrid(np.arange(self.width) + 0.5, np.arange(self.height) + 0.5)
        c, s, res = math.cos(self.origin[2]), math.sin(self.origin[2]), self.resolution
        wx = self.origin[0] + res * (c * xs - s * ys)
        wy = self.origin[1] + res * (s * xs + c * ys)
        gx = np.floor((wx - nav.origin[0]) / res).astype(int)
        gy = np.floor((wy - nav.origin[1]) / res).astype(int)
        valid = (gx >= 0) & (gy >= 0) & (gx < nav.width) & (gy < nav.height)
        output = np.full(self.base.shape, 100, np.int8)
        output[valid] = grid[gy[valid], gx[valid]]
        return output


def image_from_upload(data, color=False):
    raw = base64.b64decode(data, validate=True)
    with Image.open(io.BytesIO(raw)) as img:
        if img.width * img.height > MAX_CELLS:
            raise ValueError("地图最多支持 400 万栅格")
        return img.convert("RGB" if color else "L")


def pgm_bytes(grid):
    pixels = np.flipud(np.where(grid == 0, 254, np.where(grid == 100, 0, 205))).astype(
        np.uint8
    )
    return f"P5\n{pixels.shape[1]} {pixels.shape[0]}\n255\n".encode() + pixels.tobytes()
