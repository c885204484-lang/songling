"""Fit and apply a planar map registration without changing source pixels."""

import copy
from datetime import datetime, timezone
import math

import numpy as np

from .maps import MapModel, finite


def fit_registration(model, payload):
    points = payload.get("points")
    if not isinstance(points, list) or not 3 <= len(points) <= 30:
        raise ValueError("需要 3–30 个对应点，至少 3 个用于配准")
    pairs = []
    for index, point in enumerate(points):
        if not isinstance(point, dict):
            raise ValueError("对应点格式无效")
        source, target = point.get("map"), point.get("robot")
        if (
            not isinstance(source, list)
            or not isinstance(target, list)
            or len(source) != 2
            or len(target) != 2
        ):
            raise ValueError("每个对应点需要地图 [x,y] 和 ROS [x,y]")
        source, target = [finite(v) for v in source], [finite(v) for v in target]
        if any(abs(v) > 1e8 for v in source + target):
            raise ValueError("对应点坐标过大，请使用米制 ROS map 坐标")
        gx, gy = model.world_to_grid(*source)
        if not (0 <= gx <= model.width and 0 <= gy <= model.height):
            raise ValueError("配准点超出当前地图")
        role = point.get("role", "fit")
        if role not in ("fit", "check"):
            raise ValueError("点类型应为配准点或检查点")
        pairs.append(
            dict(
                name=str(point.get("name", f"P{index + 1}"))[:40],
                map=source,
                robot=target,
                role=role,
                simulated=point.get("simulated") is True,
                captured_at=str(point.get("captured_at", ""))[:80],
                source=str(point.get("source", "manual"))[:20],
            )
        )
    fitted = [p for p in pairs if p["role"] == "fit"]
    if len(fitted) < 3:
        raise ValueError("至少需要 3 个配准点；检查点不参与拟合")
    source = np.asarray([p["map"] for p in fitted])
    target = np.asarray([p["robot"] for p in fitted])
    source_center, target_center = source.mean(axis=0), target.mean(axis=0)
    a, b = source - source_center, target - target_center
    for values in (a, b):
        singular = np.linalg.svd(values, compute_uv=False)
        if singular[0] < 1.0 or singular[1] / singular[0] < 0.02:
            raise ValueError("点位过近或接近共线，请选择分散且不在同一直线上的地面点")
    u, _, vt = np.linalg.svd(a.T @ b)
    rotation = vt.T @ u.T
    if np.linalg.det(rotation) < 0:
        vt[-1] *= -1
        rotation = vt.T @ u.T
    estimated_scale = float(np.sum(b * (a @ rotation.T)) / np.sum(a * a))
    if not 0.5 <= estimated_scale <= 2.0:
        raise ValueError("对应点推算的比例超出 0.5–2，请检查点位、坐标单位或底图比例尺")
    scale = estimated_scale if payload.get("fit_scale") is True else 1.0
    translation = target_center - scale * (rotation @ source_center)
    yaw = math.atan2(rotation[1, 0], rotation[0, 0])
    for point in pairs:
        predicted = scale * (rotation @ point["map"]) + translation
        point["predicted"] = predicted.tolist()
        point["error_m"] = float(np.linalg.norm(predicted - point["robot"]))
    fit_errors = [p["error_m"] for p in pairs if p["role"] == "fit"]
    check_errors = [p["error_m"] for p in pairs if p["role"] == "check"]
    tolerance = finite(payload.get("max_error_m", 0.75))
    if not 0.05 <= tolerance <= 5:
        raise ValueError("允许误差应在 0.05–5 米之间")
    return dict(
        scale=scale,
        estimated_scale=estimated_scale,
        yaw=yaw,
        translation=translation.tolist(),
        points=pairs,
        fit_rms_m=float(np.sqrt(np.mean(np.square(fit_errors)))),
        fit_max_m=max(fit_errors),
        check_max_m=max(check_errors) if check_errors else None,
        max_error_m=tolerance,
        fit_count=len(fit_errors),
        check_count=len(check_errors),
        passed=bool(check_errors) and max(fit_errors + check_errors) <= tolerance,
        simulated=any(p["simulated"] for p in pairs),
    )


def registered_document(model, project, report, source_revision):
    """Move image geometry, polygons, and waypoint headings by the same similarity."""
    scale, yaw = report["scale"], report["yaw"]
    tx, ty = report["translation"]
    c, s = math.cos(yaw), math.sin(yaw)

    def transform(point):
        x, y = point
        return [scale * (c * x - s * y) + tx, scale * (s * x + c * y) + ty]

    metadata = model.metadata()
    metadata["origin"] = [
        *transform(model.origin[:2]),
        math.remainder(model.origin[2] + yaw, 2 * math.pi),
    ]
    metadata["resolution"] = model.resolution * scale
    geo = copy.deepcopy(model.context.get("georeference", {}))
    geo.update(
        map_crs="ros_map",
        navigation_aligned=not report["simulated"],
        registration=dict(
            method=report.get("method", "similarity_2d" if scale != 1 else "rigid_2d"),
            target_frame="map",
            fixed_frame_confirmed=True,
            saved_at=datetime.now(timezone.utc).isoformat(),
            source_revision=source_revision,
            source_geometry=dict(origin=model.origin, resolution=model.resolution),
            **{k: copy.deepcopy(v) for k, v in report.items() if k != "method"},
        ),
    )
    metadata["georeference"] = geo
    result_model = MapModel(model.image, metadata, model.display_image)
    result = copy.deepcopy(project)
    result["map"] = result_model.metadata()
    for kind in ("drivable", "forbidden"):
        result[kind] = [
            [transform(point) for point in polygon] for polygon in result[kind]
        ]
    for waypoint in result["waypoints"]:
        waypoint["x"], waypoint["y"] = transform([waypoint["x"], waypoint["y"]])
        waypoint["yaw"] = math.remainder(waypoint["yaw"] + yaw, 2 * math.pi)
    return result_model, result_model.validate(result)
