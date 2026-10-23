#!/usr/bin/env python3
"""Publish an Amap-derived keepout mask for Nav2's KeepoutFilter.

The node:
  1. downloads an Amap static map of the operating area (GCJ-02);
  2. extracts water / green / sports field / major-road keepout regions;
  3. aligns the image to the robot map frame by sampling the standard
     robot_localization ``/fromLL`` service at a grid of control points and
     fitting a local affine (GCJ-02 -> WGS-84 -> map);
  4. publishes a Nav2-compatible OccupancyGrid mask plus the corresponding
     ``nav2_msgs/CostmapFilterInfo`` message.

No ``costmap_filter_info_server`` or mask map_server is required: this node
publishes both messages itself and republishes them so late subscribers (the
costmap filter) always receive the latest mask.
"""

from __future__ import annotations

import json
import math
import os
import time
from array import array

import numpy as np
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.time import Time
from nav_msgs.msg import OccupancyGrid
from nav2_msgs.msg import CostmapFilterInfo
from robot_localization.srv import FromLL
from sensor_msgs.msg import NavSatFix
from tf2_ros import Buffer, TransformListener

try:
    from songling_navigation import amap_keepout as ak
except ImportError:  # running straight from the source tree
    import sys

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from songling_navigation import amap_keepout as ak


class AmapKeepoutMask(Node):
    def __init__(self) -> None:
        super().__init__("amap_keepout_mask")
        self.cb_group = ReentrantCallbackGroup()
        self._read_parameters()

        qos = QoSProfile(
            depth=1,
            history=HistoryPolicy.KEEP_LAST,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.mask_pub = self.create_publisher(OccupancyGrid, self.mask_topic, qos)
        self.info_pub = self.create_publisher(
            CostmapFilterInfo, self.filter_info_topic, qos
        )
        self.fromll_client = self.create_client(
            FromLL, self.fromll_service, callback_group=self.cb_group
        )
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.image: ak.AmapStaticImage | None = None
        self.keep: np.ndarray | None = None
        self.class_ids: np.ndarray | None = None
        self.geo: ak.AffineGeo | None = None
        self.grid: ak.GridMask | None = None
        self.mask_array: array | None = None
        self.center_gcj: tuple[float, float] | None = None  # (lat, lon)
        self.center_wgs: tuple[float, float] | None = None  # (lat, lon)
        self.last_fix: tuple[float, float] | None = None  # (lat, lon), WGS-84
        self.fix_count = 0
        self.published = False
        self.busy = False
        self.next_fetch_time = 0.0
        self.next_fit_time = 0.0
        self.last_wait_log = 0.0
        self.republish_timer = None

        self.gps_sub = self.create_subscription(
            NavSatFix, self.gps_topic, self._gps_cb, 10, callback_group=self.cb_group
        )
        if self.use_static_anchor and self.center_mode != "fixed":
            self.get_logger().warn(
                "use_static_anchor=true; forcing center_mode=fixed"
            )
            self.center_mode = "fixed"
        if self.center_mode == "fixed":
            self.get_logger().info(
                f"Amap keepout mask: fixed centre GCJ "
                f"({self.center_lat_fixed:.6f}, {self.center_lon_fixed:.6f}), "
                f"classes={self.classes}, topic={self.mask_topic}"
            )
        else:
            self.get_logger().info(
                f"Amap keepout mask: centre from {self.gps_topic} "
                f"(WGS-84 -> GCJ), classes={self.classes}, topic={self.mask_topic}"
            )
        if not self.amap_key:
            self.get_logger().error(
                "amap_key is empty; set it in config/amap_keepout_mask.yaml"
            )
        self.step_timer = self.create_timer(1.0, self.step, callback_group=self.cb_group)

    # ------------------------------------------------------------------ params
    def _read_parameters(self) -> None:
        self.amap_key = self._param("amap_key", "")
        self.center_lat_fixed = float(
            self._param("center_lat_gcj", ak.DEFAULT_CENTER_LAT_GCJ)
        )
        self.center_lon_fixed = float(
            self._param("center_lon_gcj", ak.DEFAULT_CENTER_LON_GCJ)
        )
        self.center_mode = str(self._param("center_mode", "gps")).strip().lower()
        if self.center_mode not in ("gps", "fixed"):
            self.get_logger().warn(
                f"unknown center_mode '{self.center_mode}', using 'gps'"
            )
            self.center_mode = "gps"
        self.gps_topic = str(self._param("gps_topic", "/gps/fix"))
        self.gps_min_fixes = int(self._param("gps_min_fixes", 5))
        self.zoom = int(self._param("zoom", 17))
        self.size = int(self._param("size", 1024))
        self.scale = int(self._param("scale", 2))
        self.roi_radius = float(self._param("roi_radius", 300.0))
        self.resolution = float(self._param("resolution", 0.5))
        self.classes = list(self._param("classes", ["water", "green", "track", "major_road"]))
        self.water_min_area = float(self._param("water_min_area_m2", 100.0))
        self.green_min_area = float(self._param("green_min_area_m2", 20.0))
        self.track_min_area = float(self._param("track_min_area_m2", 50.0))
        self.road_min_area = float(self._param("road_min_area_m2", 50.0))
        self.road_close_m = float(self._param("road_close_m", 14.0))
        self.dilate_m = float(self._param("dilate_m", 0.3))
        self.mask_topic = str(self._param("mask_topic", "/amap_keepout_mask"))
        self.filter_info_topic = str(
            self._param("filter_info_topic", "/costmap_filter_info")
        )
        self.fromll_service = str(self._param("fromll_service", "/fromLL"))
        self.frame_id = str(self._param("frame_id", "map"))
        self.output_dir = str(
            self._param(
                "output_dir",
                "/home/nvidia/songling/songling_ws/src/songling_navigation/PCD/amap_mask",
            )
        )
        self.save_snapshot = bool(self._param("save_snapshot", True))
        self.publish_period_s = float(self._param("publish_period_s", 0.0))
        self.use_static_anchor = bool(self._param("use_static_anchor", False))
        self.anchor_lat = float(self._param("anchor_lat", 0.0))
        self.anchor_lon = float(self._param("anchor_lon", 0.0))
        self.anchor_x = float(self._param("anchor_x", 0.0))
        self.anchor_y = float(self._param("anchor_y", 0.0))
        self.anchor_yaw_deg = float(self._param("anchor_yaw_deg", 0.0))
        self.center_on_robot = bool(self._param("center_on_robot", False))
        self.cache_dir = str(self._param("cache_dir", "~/.cache/songling/amap_mask"))
        self.cache_ttl_hours = float(self._param("cache_ttl_hours", 24.0))
        self.force_refresh = bool(self._param("force_refresh", False))
        self.max_affine_residual_m = float(self._param("max_affine_residual_m", 3.0))
        self.control_half_size_m = float(self._param("control_half_size_m", 300.0))
        self.max_grid_cells = int(self._param("max_grid_cells", 10_000_000))

    def _param(self, name: str, default):
        self.declare_parameter(name, default)
        return self.get_parameter(name).value

    def _gps_cb(self, msg: NavSatFix) -> None:
        # The RTK driver publishes WGS-84.  Ignore no-fix/zero placeholders.
        if msg.status.status < 0:
            return
        if abs(msg.latitude) < 1e-6 or abs(msg.longitude) < 1e-6:
            return
        self.last_fix = (float(msg.latitude), float(msg.longitude))
        self.fix_count += 1

    def _resolve_center(self) -> bool:
        """Pick the Amap GCJ centre from the live GPS or the fixed config."""
        if self.center_mode == "fixed":
            self.center_gcj = (self.center_lat_fixed, self.center_lon_fixed)
            wgs_lon, wgs_lat = ak.gcj02_to_wgs84(
                self.center_lon_fixed, self.center_lat_fixed
            )
            self.center_wgs = (wgs_lat, wgs_lon)  # (lat, lon), like the GPS path
            self.get_logger().info(
                f"using fixed Amap centre GCJ ({self.center_gcj[0]:.6f}, "
                f"{self.center_gcj[1]:.6f})"
            )
            return True

        if self.last_fix is None or self.fix_count < self.gps_min_fixes:
            now = time.monotonic()
            if now - self.last_wait_log > 5.0:
                self.last_wait_log = now
                self.get_logger().info(
                    f"waiting for {self.gps_min_fixes} valid fixes on "
                    f"{self.gps_topic} before choosing the Amap centre..."
                )
            return False

        lat, lon = self.last_fix
        gcj_lon, gcj_lat = ak.wgs84_to_gcj02(lon, lat)
        self.center_wgs = (lat, lon)
        self.center_gcj = (gcj_lat, gcj_lon)
        self.get_logger().info(
            f"using live GPS centre WGS-84 ({lat:.6f}, {lon:.6f}) -> "
            f"Amap GCJ ({gcj_lat:.6f}, {gcj_lon:.6f})"
        )
        return True

    # -------------------------------------------------------------------- step
    async def step(self) -> None:
        if self.busy or self.published:
            return
        self.busy = True
        try:
            if self.center_gcj is None and not self._resolve_center():
                return

            if self.image is None:
                if time.monotonic() < self.next_fetch_time:
                    return
                try:
                    self._load_source()
                except Exception as exc:  # noqa: BLE001 - retry later
                    self.next_fetch_time = time.monotonic() + 30.0
                    self.get_logger().error(f"failed to build Amap source mask: {exc}")
                    return

            if self.use_static_anchor:
                geo = ak.affine_from_anchor(
                    self.anchor_lat,
                    self.anchor_lon,
                    self.anchor_x,
                    self.anchor_y,
                    self.anchor_yaw_deg,
                )
                self._publish_mask(geo, residual=None, source="static_anchor")
                return

            if time.monotonic() < self.next_fit_time:
                return
            if not self.fromll_client.service_is_ready():
                now = time.monotonic()
                if now - self.last_wait_log > 10.0:
                    self.last_wait_log = now
                    self.get_logger().info(
                        f"waiting for {self.fromll_service} to align the mask..."
                    )
                return

            result = await self._fit_affine_from_ros()
            if result is None:
                self.next_fit_time = time.monotonic() + 15.0
                return
            geo, residual = result
            self._publish_mask(geo, residual=residual, source="fromLL")
        finally:
            self.busy = False

    # ------------------------------------------------------------------ source
    def _load_source(self) -> None:
        self.get_logger().info("downloading / segmenting the Amap static map...")
        started = time.time()
        image = ak.fetch_static_image(
            self.amap_key,
            self.center_gcj[0],
            self.center_gcj[1],
            self.zoom,
            self.size,
            self.scale,
            cache_dir=self.cache_dir,
            cache_ttl_hours=self.cache_ttl_hours,
            force_refresh=self.force_refresh,
        )
        keep, class_ids = ak.segment_keepout(
            image.rgb,
            image.m_per_px,
            classes=self.classes,
            water_min_area_m2=self.water_min_area,
            green_min_area_m2=self.green_min_area,
            track_min_area_m2=self.track_min_area,
            road_min_area_m2=self.road_min_area,
            road_close_m=self.road_close_m,
            dilate_m=self.dilate_m,
        )
        self.image = image
        self.keep = keep
        self.class_ids = class_ids
        counts = {
            name: int(np.count_nonzero(class_ids == class_id))
            for class_id, name in ak.CLASS_NAMES.items()
        }
        self.get_logger().info(
            f"Amap image {image.width}x{image.height} @ {image.m_per_px:.3f} m/px, "
            f"class pixels={counts}, took {time.time() - started:.1f}s"
        )
        if self.save_snapshot:
            out_dir = os.path.expanduser(self.output_dir)
            try:
                ak.save_segmentation_preview(
                    image,
                    class_ids,
                    os.path.join(out_dir, "amap_keepout_segmentation.png"),
                )
            except Exception as exc:  # noqa: BLE001 - snapshot is best effort
                self.get_logger().warn(f"could not save segmentation preview: {exc}")

    # ------------------------------------------------------------------- align
    async def _fit_affine_from_ros(self) -> tuple[ak.AffineGeo, float] | None:
        points = ak.control_points_wgs84(
            self.center_wgs[0],
            self.center_wgs[1],
            half_size_m=self.control_half_size_m,
            count=5,
        )
        lons: list[float] = []
        lats: list[float] = []
        xs: list[float] = []
        ys: list[float] = []
        for lon, lat in points:
            request = FromLL.Request()
            request.ll_point.longitude = float(lon)
            request.ll_point.latitude = float(lat)
            request.ll_point.altitude = 0.0
            try:
                response = await self.fromll_client.call_async(request)
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f"{self.fromll_service} call failed: {exc}")
                return None
            if response is None:
                return None
            lons.append(float(lon))
            lats.append(float(lat))
            xs.append(float(response.map_point.x))
            ys.append(float(response.map_point.y))

        geo = ak.affine_from_control_points(lons, lats, xs, ys)
        residual = float(np.max(geo.residuals(lons, lats, xs, ys)))
        if not math.isfinite(residual) or residual > self.max_affine_residual_m:
            self.get_logger().error(
                f"geo/map affine residual {residual:.2f} m exceeds "
                f"{self.max_affine_residual_m:.2f} m; is /fromLL using WGS-84?"
            )
            return None
        self.get_logger().info(
            f"geo/map affine fitted from {len(points)} controls, "
            f"max residual {residual:.3f} m"
        )
        return geo, residual

    # ------------------------------------------------------------------ publish
    def _publish_mask(
        self,
        geo: ak.AffineGeo,
        residual: float | None,
        source: str,
    ) -> None:
        assert self.image is not None and self.keep is not None and self.class_ids is not None
        cx, cy = geo.lonlat_to_map(self.center_wgs[1], self.center_wgs[0])
        cx, cy = float(cx), float(cy)
        if self.center_on_robot:
            try:
                transform = self.tf_buffer.lookup_transform(
                    self.frame_id, "base_link", Time()
                )
                cx = float(transform.transform.translation.x)
                cy = float(transform.transform.translation.y)
                self.get_logger().info(
                    f"ROI centred on robot at ({cx:.1f}, {cy:.1f}) in {self.frame_id}"
                )
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(
                    f"center_on_robot requested but TF {self.frame_id}->base_link "
                    f"is unavailable ({exc}); using the Amap centre"
                )

        grid = ak.render_mask_grid(
            self.image,
            self.keep,
            self.class_ids,
            geo,
            (cx, cy),
            self.roi_radius,
            self.resolution,
            max_cells=self.max_grid_cells,
        )
        self.geo = geo
        self.grid = grid
        self.mask_array = array("b", grid.data.astype(np.int8).tobytes())
        self.published = True

        self.get_logger().info(
            f"mask ready ({source}): {grid.width}x{grid.height} @ "
            f"{grid.resolution} m, origin=({grid.origin_x:.1f}, "
            f"{grid.origin_y:.1f}), keepout={grid.keepout_cells} cells; "
            f"publishing on {self.mask_topic}"
        )
        if self.save_snapshot:
            self._save_snapshot(residual=residual, source=source)
        # Both topics are transient-local, so one shot is enough for a filter
        # that starts later.  A positive publish_period_s additionally sends a
        # mask heartbeat (no info resend, which would make the filter re-subscribe).
        self.publish_info()
        self.publish_mask()

        self.step_timer.cancel()
        if self.publish_period_s > 0:
            self.republish_timer = self.create_timer(
                self.publish_period_s, self.publish_mask, callback_group=self.cb_group
            )

    def publish_info(self) -> None:
        now = self.get_clock().now().to_msg()
        info = CostmapFilterInfo()
        info.header.stamp = now
        info.header.frame_id = self.frame_id
        info.type = 0  # keepout
        info.filter_mask_topic = self.mask_topic
        info.base = 0.0
        info.multiplier = 1.0
        self.info_pub.publish(info)

    def publish_mask(self) -> None:
        if self.grid is None or self.mask_array is None:
            return
        now = self.get_clock().now().to_msg()
        grid_msg = OccupancyGrid()
        grid_msg.header.stamp = now
        grid_msg.header.frame_id = self.frame_id
        grid_msg.info.resolution = float(self.grid.resolution)
        grid_msg.info.width = int(self.grid.width)
        grid_msg.info.height = int(self.grid.height)
        grid_msg.info.origin.position.x = float(self.grid.origin_x)
        grid_msg.info.origin.position.y = float(self.grid.origin_y)
        grid_msg.info.origin.position.z = 0.0
        grid_msg.info.origin.orientation.w = 1.0
        grid_msg.data = self.mask_array
        self.mask_pub.publish(grid_msg)

    # ----------------------------------------------------------------- snapshot
    def _save_snapshot(self, residual: float | None, source: str) -> None:
        assert self.grid is not None and self.image is not None
        out_dir = os.path.expanduser(self.output_dir)
        try:
            os.makedirs(out_dir, exist_ok=True)
            pgm, yaml_path = self.grid.save_pgm_yaml(out_dir)
            preview = self.grid.save_preview_png(out_dir)
            ak.save_segmentation_preview(
                self.image,
                self.class_ids,
                os.path.join(out_dir, "amap_keepout_segmentation.png"),
            )
            counts = {
                name: int(np.count_nonzero(self.class_ids == class_id))
                for class_id, name in ak.CLASS_NAMES.items()
            }
            meta = {
                "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "source": source,
                "center_mode": self.center_mode,
                "amap_center_gcj": [self.center_gcj[1], self.center_gcj[0]],
                "center_wgs84": [self.center_wgs[1], self.center_wgs[0]],
                "zoom": self.zoom,
                "size": self.size,
                "scale": self.scale,
                "m_per_px": self.image.m_per_px,
                "classes": self.classes,
                "class_pixels": counts,
                "affine_wgs84_to_map": self.geo.as_dict() if self.geo else None,
                "max_residual_m": residual,
                "frame_id": self.frame_id,
                "resolution": self.grid.resolution,
                "origin": [self.grid.origin_x, self.grid.origin_y],
                "grid_size": [self.grid.width, self.grid.height],
                "keepout_cells": self.grid.keepout_cells,
                "pgm": pgm,
                "yaml": yaml_path,
                "map_preview": preview,
            }
            with open(
                os.path.join(out_dir, "amap_keepout_meta.json"), "w", encoding="utf-8"
            ) as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            self.get_logger().info(f"mask snapshot saved to {out_dir}")
        except Exception as exc:  # noqa: BLE001 - never fail navigation for a snapshot
            self.get_logger().warn(f"could not save mask snapshot: {exc}")


def main(args=None) -> None:
    rclpy.init(args=args)
    node = AmapKeepoutMask()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
