#!/usr/bin/env python3
"""Amap static-map keepout mask helpers.

The Amap Web Service works in GCJ-02, while robot_localization's /fromLL
service expects WGS-84.  This module keeps that conversion in one place and
turns the semantic classes extracted from an Amap static image (water, lawns,
sports field, major roads) into a grid expressed in the robot's map frame.

It deliberately has no ROS dependency so the segmentation and the map-frame
rasterisation can be exercised offline (see ``python3 -m ... --help``).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import cv2
import numpy as np
import requests
from PIL import Image

AMAP_STATIC_URL = "https://restapi.amap.com/v3/staticmap"

# Default operating area: Zhejiang Sports Vocational College campus (GCJ-02).
DEFAULT_CENTER_LAT_GCJ = 30.2544
DEFAULT_CENTER_LON_GCJ = 120.2941

CLASS_WATER = 1
CLASS_GREEN = 2
CLASS_TRACK = 3
CLASS_ROAD = 4

CLASS_NAMES = {
    CLASS_WATER: "water",
    CLASS_GREEN: "green",
    CLASS_TRACK: "track",
    CLASS_ROAD: "major_road",
}

CLASS_COLORS = {
    CLASS_WATER: (30, 90, 255),
    CLASS_GREEN: (40, 170, 60),
    CLASS_TRACK: (255, 120, 20),
    CLASS_ROAD: (230, 0, 230),
}

# ---------------------------------------------------------------------------
# GCJ-02 <-> WGS-84
# ---------------------------------------------------------------------------

_A = 6378245.0
_EE = 0.00669342162296594323
_PI = math.pi


def _transform_lat_scalar(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat
    ret += 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320.0 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng_scalar(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat
    ret += 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def _out_of_china(lng, lat):
    return ~((lng > 73.66) & (lng < 135.05) & (lat > 3.86) & (lat < 53.55))


def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat
    ret += 0.2 * np.sqrt(np.abs(lng))
    ret += (20.0 * np.sin(6.0 * lng * _PI) + 20.0 * np.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * np.sin(lat * _PI) + 40.0 * np.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * np.sin(lat / 12.0 * _PI) + 320.0 * np.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat
    ret += 0.1 * np.sqrt(np.abs(lng))
    ret += (20.0 * np.sin(6.0 * lng * _PI) + 20.0 * np.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * np.sin(lng * _PI) + 40.0 * np.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * np.sin(lng / 12.0 * _PI) + 300.0 * np.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02_array(lon, lat):
    """Convert WGS-84 arrays to GCJ-02 arrays (no offset outside China)."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlng = _transform_lng(lon - 105.0, lat - 35.0)
    radlat = np.radians(lat)
    magic = 1.0 - _EE * np.sin(radlat) ** 2
    sqrtmagic = np.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * np.cos(radlat) * _PI)
    out_lon = lon + dlng
    out_lat = lat + dlat
    outside = _out_of_china(lon, lat)
    return np.where(outside, lon, out_lon), np.where(outside, lat, out_lat)


def gcj02_to_wgs84_array(lon, lat):
    """Convert GCJ-02 arrays to WGS-84 arrays."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlng = _transform_lng(lon - 105.0, lat - 35.0)
    radlat = np.radians(lat)
    magic = 1.0 - _EE * np.sin(radlat) ** 2
    sqrtmagic = np.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1.0 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * np.cos(radlat) * _PI)
    mglat = lat + dlat
    mglng = lon + dlng
    out_lon = lon * 2.0 - mglng
    out_lat = lat * 2.0 - mglat
    outside = _out_of_china(lon, lat)
    return np.where(outside, lon, out_lon), np.where(outside, lat, out_lat)


def wgs84_to_gcj02(lon: float, lat: float) -> tuple[float, float]:
    lo, la = wgs84_to_gcj02_array(np.array([lon]), np.array([lat]))
    return float(lo[0]), float(la[0])


def gcj02_to_wgs84(lon: float, lat: float) -> tuple[float, float]:
    lo, la = gcj02_to_wgs84_array(np.array([lon]), np.array([lat]))
    return float(lo[0]), float(la[0])


# ---------------------------------------------------------------------------
# Amap static map
# ---------------------------------------------------------------------------


@dataclass
class AmapStaticImage:
    """An Amap static image plus the metadata needed to georeference it."""

    rgb: np.ndarray
    center_lat: float  # GCJ-02
    center_lon: float  # GCJ-02
    zoom: int
    size: int
    scale: int

    @property
    def width(self) -> int:
        return int(self.rgb.shape[1])

    @property
    def height(self) -> int:
        return int(self.rgb.shape[0])

    @property
    def m_per_px(self) -> float:
        return 156543.03392 * math.cos(math.radians(self.center_lat)) / (
            (2 ** self.zoom) * self.scale
        )

    def _world_center(self) -> tuple[float, float]:
        world = 256.0 * (2 ** self.zoom)
        cx = (self.center_lon + 180.0) / 360.0 * world
        cy = (
            1.0
            - math.asinh(math.tan(math.radians(self.center_lat))) / math.pi
        ) / 2.0 * world
        return cx, cy

    def pixel_to_wgs84(self, px, py):
        """Image pixel coordinates -> WGS-84 lon/lat arrays."""
        world = 256.0 * (2 ** self.zoom)
        cx, cy = self._world_center()
        lx = cx + (np.asarray(px, dtype=np.float64) - self.width / 2.0) / self.scale
        ly = cy + (np.asarray(py, dtype=np.float64) - self.height / 2.0) / self.scale
        lon_g = lx / world * 360.0 - 180.0
        lat_g = np.degrees(np.arctan(np.sinh(math.pi * (1.0 - 2.0 * ly / world))))
        return gcj02_to_wgs84_array(lon_g, lat_g)

    def wgs84_to_pixel(self, lon, lat):
        """WGS-84 lon/lat arrays -> image pixel coordinates."""
        lon_g, lat_g = wgs84_to_gcj02_array(lon, lat)
        world = 256.0 * (2 ** self.zoom)
        cx, cy = self._world_center()
        lx = (lon_g + 180.0) / 360.0 * world
        ly = (
            1.0
            - np.arcsinh(np.tan(np.radians(lat_g))) / math.pi
        ) / 2.0 * world
        px = (lx - cx) * self.scale + self.width / 2.0
        py = (ly - cy) * self.scale + self.height / 2.0
        return px, py


def _cache_path(cache_dir: str, center_lat: float, center_lon: float,
                zoom: int, size: int, scale: int) -> str:
    name = f"amap_{center_lat:.6f}_{center_lon:.6f}_z{zoom}_{size}x{scale}.png"
    return os.path.join(os.path.expanduser(cache_dir), name)


def fetch_static_image(
    key: str,
    center_lat: float = DEFAULT_CENTER_LAT_GCJ,
    center_lon: float = DEFAULT_CENTER_LON_GCJ,
    zoom: int = 17,
    size: int = 1024,
    scale: int = 2,
    cache_dir: str | None = "~/.cache/songling/amap_mask",
    cache_ttl_hours: float = 24.0,
    force_refresh: bool = False,
    timeout: tuple[float, float] = (10.0, 30.0),
) -> AmapStaticImage:
    """Download (or reuse a cached) Amap static image.

    ``center_lat/lon`` are GCJ-02 because that is what the Amap Web Service
    expects.  The returned image is ``size*scale`` square.
    """
    if not key:
        raise ValueError("Amap key is empty")
    # The static-map Web Service caps zoom at 17; higher values silently return
    # the z17 image, which would make the pixel scale wrong.
    if not 1 <= zoom <= 17:
        raise ValueError("Amap static map zoom must be between 1 and 17")
    if not 1 <= size <= 1024 or scale not in (1, 2):
        raise ValueError("size must be 1..1024 and scale must be 1 or 2")

    cache_file = None
    if cache_dir:
        cache_file = _cache_path(cache_dir, center_lat, center_lon, zoom, size, scale)
    if cache_file and not force_refresh and os.path.isfile(cache_file):
        age_h = (time.time() - os.path.getmtime(cache_file)) / 3600.0
        if age_h <= cache_ttl_hours:
            try:
                img = Image.open(cache_file).convert("RGB")
                if img.size == (size * scale, size * scale):
                    return AmapStaticImage(
                        np.asarray(img), center_lat, center_lon, zoom, size, scale
                    )
            except Exception:
                pass

    params = {
        "location": f"{center_lon:.6f},{center_lat:.6f}",
        "zoom": str(zoom),
        "size": f"{size}*{size}",
        "scale": str(scale),
        "key": key,
    }
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            resp = requests.get(
                AMAP_STATIC_URL,
                params=params,
                timeout=timeout,
                headers={"User-Agent": "songling-nav/1.0"},
            )
            ctype = resp.headers.get("Content-Type", "")
            if resp.status_code != 200 or not ctype.startswith("image"):
                detail = resp.text[:200]
                try:
                    info = resp.json()
                    detail = f"{info.get('info')} ({info.get('infocode')})"
                except Exception:
                    pass
                raise RuntimeError(f"Amap static map failed: HTTP {resp.status_code} {detail}")
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            expected = (size * scale, size * scale)
            if img.size != expected:
                raise RuntimeError(
                    f"Amap returned {img.size}, expected {expected}; "
                    "check the size/scale parameters"
                )
            if cache_file:
                os.makedirs(os.path.dirname(cache_file), exist_ok=True)
                tmp = cache_file + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                os.replace(tmp, cache_file)
            return AmapStaticImage(np.asarray(img), center_lat, center_lon, zoom, size, scale)
        except Exception as exc:  # noqa: BLE001 - retry network/API errors
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Amap static map request failed after retries: {last_error}")


# ---------------------------------------------------------------------------
# Semantic segmentation
# ---------------------------------------------------------------------------


def _fill_small_holes(mask: np.ndarray, max_area_px: float) -> np.ndarray:
    """Fill only holes smaller than ``max_area_px`` (keeps paths/openings)."""
    contours, hierarchy = cv2.findContours(
        mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    out = mask.copy()
    if hierarchy is None:
        return out
    for idx, contour in enumerate(contours):
        if hierarchy[0][idx][3] != -1 and cv2.contourArea(contour) <= max_area_px:
            cv2.drawContours(out, [contour], -1, 1, -1)
    return out


def _filter_components(
    mask: np.ndarray,
    min_area_px: float,
    max_aspect: float | None = None,
    max_height_px: float | None = None,
) -> np.ndarray:
    """Drop tiny blobs and thin horizontal label strips."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    out = np.zeros_like(mask)
    for idx in range(1, n):
        area = float(stats[idx, cv2.CC_STAT_AREA])
        width = float(stats[idx, cv2.CC_STAT_WIDTH])
        height = float(stats[idx, cv2.CC_STAT_HEIGHT])
        if area < min_area_px:
            continue
        if max_aspect is not None and max_height_px is not None:
            short = max(min(width, height), 1.0)
            if height <= max_height_px and max(width, height) / short > max_aspect:
                continue
        out[labels == idx] = 1
    return out


def _odd_kernel(px: float) -> np.ndarray:
    k = max(1, int(round(px)))
    if k % 2 == 0:
        k += 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))


def segment_keepout(
    rgb: np.ndarray,
    m_per_px: float,
    classes: Sequence[str] = ("water", "green", "track", "major_road"),
    water_min_area_m2: float = 100.0,
    green_min_area_m2: float = 20.0,
    track_min_area_m2: float = 50.0,
    road_min_area_m2: float = 50.0,
    road_close_m: float = 14.0,
    dilate_m: float = 0.3,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract a keepout boolean mask and a class-id image.

    Only large semantic areas are kept; campus walkways (thin white lines) are
    intentionally *not* classified, because they are the robot's drivable
    paths.  The yellow-cased public roads are filled and marked.
    """
    if m_per_px <= 0:
        raise ValueError("m_per_px must be positive")
    img = np.asarray(rgb, dtype=np.int16)
    if img.ndim != 3 or img.shape[2] != 3:
        raise ValueError("rgb must be HxWx3")
    r, g, b = img[:, :, 0], img[:, :, 1], img[:, :, 2]
    px_per_m = 1.0 / m_per_px
    classes = set(classes)
    class_ids = np.zeros(img.shape[:2], dtype=np.uint8)

    def min_px(area_m2: float) -> int:
        return max(1, int(round(area_m2 * px_per_m * px_per_m)))

    if "water" in classes:
        mask = ((b - r > 45) & (b - g > 20) & (b > 200) & (r > 120)).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        mask = _fill_small_holes(mask, 3000)
        mask = _filter_components(
            mask, min_px(water_min_area_m2), max_aspect=5.0, max_height_px=60
        )
        class_ids[mask.astype(bool)] = CLASS_WATER

    if "green" in classes:
        mask = ((g - r > 18) & (g - b > 20) & (g > 150)).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        mask = _fill_small_holes(mask, 500)
        mask = _filter_components(mask, min_px(green_min_area_m2))
        class_ids[mask.astype(bool)] = CLASS_GREEN

    if "track" in classes:
        mask = ((r > 215) & (r - g > 25) & (r - b > 30)).astype(np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        mask = _fill_small_holes(mask, 5000)
        mask = _filter_components(mask, min_px(track_min_area_m2))
        class_ids[mask.astype(bool)] = CLASS_TRACK

    if "major_road" in classes:
        # Amap draws public roads with a yellow casing and a cream fill; close
        # the casing so the road interior (not just its outline) is keepout.
        mask = ((r > 225) & (g > 170) & (r - b > 90)).astype(np.uint8)
        kernel = _odd_kernel(road_close_m * px_per_m)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = _fill_small_holes(mask, 20000)
        mask = _filter_components(mask, min_px(road_min_area_m2))
        mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
        class_ids[mask.astype(bool)] = CLASS_ROAD

    keep = class_ids > 0
    if dilate_m > 0:
        keep_u8 = cv2.dilate(
            keep.astype(np.uint8), _odd_kernel(dilate_m * px_per_m)
        )
        keep = keep_u8.astype(bool)
    return keep, class_ids


# ---------------------------------------------------------------------------
# Geo <-> map affine
# ---------------------------------------------------------------------------


@dataclass
class AffineGeo:
    """x = a*lon + b*lat + c, y = d*lon + e*lat + f (lon/lat in WGS-84)."""

    a: float
    b: float
    c: float
    d: float
    e: float
    f: float

    def lonlat_to_map(self, lon, lat):
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
        return self.a * lon + self.b * lat + self.c, self.d * lon + self.e * lat + self.f

    def map_to_lonlat(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        det = self.a * self.e - self.b * self.d
        if abs(det) < 1e-18:
            raise ValueError("degenerate geo/map affine")
        dx = x - self.c
        dy = y - self.f
        return (self.e * dx - self.b * dy) / det, (-self.d * dx + self.a * dy) / det

    def residuals(self, lon, lat, x, y):
        mx, my = self.lonlat_to_map(lon, lat)
        return np.hypot(mx - np.asarray(x), my - np.asarray(y))

    def as_dict(self) -> dict:
        return {
            "a": self.a,
            "b": self.b,
            "c": self.c,
            "d": self.d,
            "e": self.e,
            "f": self.f,
        }


def affine_from_control_points(
    lon: Sequence[float], lat: Sequence[float],
    x: Sequence[float], y: Sequence[float],
) -> AffineGeo:
    """Least-squares affine fit WGS-84 lon/lat -> map x/y."""
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if len(lon) < 3:
        raise ValueError("at least three control points are required")
    design = np.column_stack([lon, lat, np.ones_like(lon)])
    coef, *_ = np.linalg.lstsq(design, np.column_stack([x, y]), rcond=None)
    return AffineGeo(
        a=float(coef[0, 0]), b=float(coef[1, 0]), c=float(coef[2, 0]),
        d=float(coef[0, 1]), e=float(coef[1, 1]), f=float(coef[2, 1]),
    )


def affine_from_anchor(
    anchor_lat: float,
    anchor_lon: float,
    anchor_x: float = 0.0,
    anchor_y: float = 0.0,
    yaw_deg: float = 0.0,
) -> AffineGeo:
    """Build a similarity from a WGS-84 anchor and map x-axis bearing.

    ``yaw_deg`` is the bearing of map +x measured counter-clockwise from east
    (0 = east, 90 = north).
    """
    m_lon = 111320.0 * math.cos(math.radians(anchor_lat))
    m_lat = 110540.0
    theta = math.radians(yaw_deg)
    a = math.cos(theta) * m_lon
    b = -math.sin(theta) * m_lat
    d = math.sin(theta) * m_lon
    e = math.cos(theta) * m_lat
    c = anchor_x - a * anchor_lon - b * anchor_lat
    f = anchor_y - d * anchor_lon - e * anchor_lat
    return AffineGeo(a=a, b=b, c=c, d=d, e=e, f=f)


def control_points_wgs84(
    center_lat: float,
    center_lon: float,
    half_size_m: float = 200.0,
    count: int = 5,
) -> list[tuple[float, float]]:
    """A count x count WGS-84 grid around a centre, in true metres."""
    m_lon = 111320.0 * math.cos(math.radians(center_lat))
    m_lat = 110540.0
    pts: list[tuple[float, float]] = []
    denom = max(count - 1, 1)
    for i in range(count):
        north = -half_size_m + 2.0 * half_size_m * i / denom
        for j in range(count):
            east = -half_size_m + 2.0 * half_size_m * j / denom
            pts.append((center_lon + east / m_lon, center_lat + north / m_lat))
    return pts


# ---------------------------------------------------------------------------
# Map-frame grid
# ---------------------------------------------------------------------------


@dataclass
class GridMask:
    """Keepout grid in the map frame; row 0 is the bottom (minimum y)."""

    data: np.ndarray  # int8, 0 free, 100 keepout, -1 unknown
    class_data: np.ndarray  # uint8 class ids, 0 free
    origin_x: float
    origin_y: float
    resolution: float

    @property
    def width(self) -> int:
        return int(self.data.shape[1])

    @property
    def height(self) -> int:
        return int(self.data.shape[0])

    @property
    def keepout_cells(self) -> int:
        return int(np.count_nonzero(self.data == 100))

    def save_pgm_yaml(self, out_dir: str, name: str = "amap_keepout_mask") -> tuple[str, str]:
        os.makedirs(out_dir, exist_ok=True)
        pgm_path = os.path.join(out_dir, name + ".pgm")
        yaml_path = os.path.join(out_dir, name + ".yaml")
        img = np.full((self.height, self.width), 205, dtype=np.uint8)
        img[self.data == 0] = 254
        img[self.data == 100] = 0
        Image.fromarray(np.flipud(img), mode="L").save(pgm_path)
        with open(yaml_path, "w", encoding="utf-8") as f:
            f.write(f"image: {os.path.basename(pgm_path)}\n")
            f.write("mode: trinary\n")
            f.write(f"resolution: {self.resolution:.6f}\n")
            f.write(
                f"origin: [{self.origin_x:.6f}, {self.origin_y:.6f}, 0.0]\n"
            )
            f.write("negate: 0\n")
            f.write("occupied_thresh: 0.65\n")
            f.write("free_thresh: 0.25\n")
        return pgm_path, yaml_path

    def preview_rgb(self) -> np.ndarray:
        out = np.full((self.height, self.width, 3), 245, dtype=np.uint8)
        out[self.data == -1] = (190, 190, 190)
        out[self.data == 0] = (250, 250, 250)
        for class_id, color in CLASS_COLORS.items():
            out[self.class_data == class_id] = color
        return np.flipud(out)

    def save_preview_png(self, out_dir: str, name: str = "amap_keepout_map_preview") -> str:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, name + ".png")
        Image.fromarray(self.preview_rgb()).save(path)
        return path


def render_mask_grid(
    image: AmapStaticImage,
    keep: np.ndarray,
    class_ids: np.ndarray,
    geo: AffineGeo,
    center_map_xy: tuple[float, float],
    half_size_m: float,
    resolution: float,
    max_cells: int = 20_000_000,
) -> GridMask:
    """Inverse-warp the keepout image onto a map-frame grid."""
    if resolution <= 0 or half_size_m <= 0:
        raise ValueError("resolution and half_size_m must be positive")
    width = int(math.ceil(2.0 * half_size_m / resolution))
    height = width
    if width * height > max_cells:
        raise ValueError(
            f"mask grid {width}x{height} exceeds max_cells={max_cells}; "
            "increase resolution or reduce roi_radius"
        )
    origin_x = center_map_xy[0] - width * resolution / 2.0
    origin_y = center_map_xy[1] - height * resolution / 2.0
    xs = origin_x + (np.arange(width, dtype=np.float64) + 0.5) * resolution
    ys = origin_y + (np.arange(height, dtype=np.float64) + 0.5) * resolution
    xx, yy = np.meshgrid(xs, ys)
    lon, lat = geo.map_to_lonlat(xx, yy)
    px, py = image.wgs84_to_pixel(lon, lat)
    valid = (
        (px >= 0)
        & (px < image.width)
        & (py >= 0)
        & (py < image.height)
    )
    ix = np.clip(px.astype(np.int32), 0, image.width - 1)
    iy = np.clip(py.astype(np.int32), 0, image.height - 1)
    sampled_keep = keep[iy, ix]
    sampled_class = class_ids[iy, ix]
    data = np.full((height, width), -1, dtype=np.int8)
    data[valid] = 0
    data[valid & sampled_keep] = 100
    class_data = np.where(valid, sampled_class, 0).astype(np.uint8)
    return GridMask(data, class_data, origin_x, origin_y, resolution)


# ---------------------------------------------------------------------------
# Preview / CLI
# ---------------------------------------------------------------------------


def save_segmentation_preview(
    image: AmapStaticImage,
    class_ids: np.ndarray,
    out_path: str,
    alpha: float = 0.55,
) -> str:
    rgb = image.rgb.astype(np.float32)
    overlay = rgb.copy()
    for class_id, color in CLASS_COLORS.items():
        m = class_ids == class_id
        if np.any(m):
            overlay[m] = (
                rgb[m] * (1.0 - alpha) + np.asarray(color, dtype=np.float32) * alpha
            )
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    Image.fromarray(overlay.astype(np.uint8)).save(out_path)
    return out_path


def _parse_classes(value: str) -> list[str]:
    return [c.strip() for c in value.split(",") if c.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract an Amap keepout mask (water/green/track/major road)."
    )
    parser.add_argument("--key", default=os.environ.get("AMAP_KEY", ""),
                        help="Amap Web Service key (or set AMAP_KEY)")
    parser.add_argument("--center-lat", type=float, default=DEFAULT_CENTER_LAT_GCJ,
                        help="GCJ-02 latitude of the image centre")
    parser.add_argument("--center-lon", type=float, default=DEFAULT_CENTER_LON_GCJ,
                        help="GCJ-02 longitude of the image centre")
    parser.add_argument("--zoom", type=int, default=17)
    parser.add_argument("--size", type=int, default=1024)
    parser.add_argument("--scale", type=int, default=2)
    parser.add_argument("--classes", type=_parse_classes,
                        default=["water", "green", "track", "major_road"])
    parser.add_argument("--water-min-area", type=float, default=100.0)
    parser.add_argument("--green-min-area", type=float, default=20.0)
    parser.add_argument("--track-min-area", type=float, default=50.0)
    parser.add_argument("--road-min-area", type=float, default=50.0)
    parser.add_argument("--road-close-m", type=float, default=14.0)
    parser.add_argument("--dilate-m", type=float, default=0.3)
    parser.add_argument("--out-dir", default="/tmp/amap_keepout")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--roi-radius", type=float, default=120.0)
    parser.add_argument("--resolution", type=float, default=0.25)
    # Optional static anchor (WGS-84 -> map) for offline map-frame output.
    parser.add_argument("--anchor-lat", type=float, default=None)
    parser.add_argument("--anchor-lon", type=float, default=None)
    parser.add_argument("--anchor-x", type=float, default=0.0)
    parser.add_argument("--anchor-y", type=float, default=0.0)
    parser.add_argument("--anchor-yaw-deg", type=float, default=0.0)
    args = parser.parse_args(argv)

    if not args.key:
        parser.error("--key or AMAP_KEY is required")

    image = fetch_static_image(
        args.key,
        args.center_lat,
        args.center_lon,
        args.zoom,
        args.size,
        args.scale,
        cache_dir=None if args.no_cache else "~/.cache/songling/amap_mask",
        force_refresh=args.force_refresh,
    )
    keep, class_ids = segment_keepout(
        image.rgb,
        image.m_per_px,
        args.classes,
        args.water_min_area,
        args.green_min_area,
        args.track_min_area,
        args.road_min_area,
        args.road_close_m,
        args.dilate_m,
    )
    os.makedirs(args.out_dir, exist_ok=True)
    preview = save_segmentation_preview(
        image, class_ids, os.path.join(args.out_dir, "amap_keepout_segmentation.png")
    )
    counts = {
        name: int(np.count_nonzero(class_ids == cid))
        for cid, name in CLASS_NAMES.items()
    }
    summary = {
        "image_size": [image.width, image.height],
        "m_per_px": image.m_per_px,
        "center_gcj": [args.center_lon, args.center_lat],
        "class_pixels": counts,
        "keepout_fraction": float(keep.mean()),
        "segmentation_preview": preview,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.anchor_lat is not None and args.anchor_lon is not None:
        geo = affine_from_anchor(
            args.anchor_lat, args.anchor_lon, args.anchor_x, args.anchor_y,
            args.anchor_yaw_deg,
        )
        center_wgs = gcj02_to_wgs84(args.center_lon, args.center_lat)
        cx, cy = geo.lonlat_to_map(*center_wgs)
        grid = render_mask_grid(
            image, keep, class_ids, geo, (float(cx), float(cy)),
            args.roi_radius, args.resolution,
        )
        pgm, yaml_path = grid.save_pgm_yaml(args.out_dir)
        grid_preview = grid.save_preview_png(args.out_dir)
        meta = {
            **summary,
            "anchor": {
                "lat": args.anchor_lat,
                "lon": args.anchor_lon,
                "x": args.anchor_x,
                "y": args.anchor_y,
                "yaw_deg": args.anchor_yaw_deg,
            },
            "affine": geo.as_dict(),
            "origin": [grid.origin_x, grid.origin_y],
            "resolution": grid.resolution,
            "grid_size": [grid.width, grid.height],
            "keepout_cells": grid.keepout_cells,
            "pgm": pgm,
            "yaml": yaml_path,
            "map_preview": grid_preview,
        }
        with open(os.path.join(args.out_dir, "amap_keepout_meta.json"), "w",
                  encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        print(json.dumps(meta, ensure_ascii=False, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
