"""Georeferenced Amap pixels -> WGS84 -> the live navsat map frame."""

import math
import copy
from datetime import datetime, timezone
import cv2
import numpy as np

from songling_navigation.amap_keepout import AmapStaticImage, wgs84_to_gcj02_array
from .registration import fit_registration
from .maps import MapModel, MAX_CELLS


def geographic_samples(model):
    geo = model.context.get("georeference", {})
    if geo.get("source_crs") != "GCJ-02" or "registration" in geo:
        raise ValueError("自动投影需要带经纬度的原始高德底图；已转换的地图请载入原快照")
    try:
        lon, lat = geo["center_gcj02"]
        zoom, scale = int(geo["zoom"]), int(geo["scale"])
        if not (math.isfinite(lon) and math.isfinite(lat) and abs(lon) <= 180
                and abs(lat) < 85 and 1 <= zoom <= 22 and scale in (1, 2)):
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise ValueError("底图缺少有效的经纬度、缩放级别或像素倍率") from None
    image = AmapStaticImage(np.zeros((model.height, model.width, 3), np.uint8),
                           lat, lon, zoom, model.width, scale)
    pixels = [(x * model.width, y * model.height)
              for y in (.1, .5, .9) for x in (.1, .5, .9)]
    px, py = np.asarray(pixels).T
    # Invert the forward GCJ transform iteratively; the usual one-step inverse
    # can leave metre-level round-trip errors near a road boundary.
    lon_w, lat_w = image.pixel_to_wgs84(px, py)
    # Recover the exact desired GCJ coordinates from the image's Mercator grid.
    world = 256 * 2 ** zoom
    cx, cy = image._world_center()
    target_lon = (cx + (px - model.width / 2) / scale) / world * 360 - 180
    target_lat = np.degrees(np.arctan(np.sinh(math.pi * (
        1 - 2 * (cy + (py - model.height / 2) / scale) / world))))
    for _ in range(5):
        lon_g, lat_g = wgs84_to_gcj02_array(lon_w, lat_w)
        lon_w += target_lon - lon_g
        lat_w += target_lat - lat_g
    return [dict(map=model.grid_to_world(x, model.height - y),
                 lon=float(lo), lat=float(la), role="check" if i % 2 else "fit")
            for i, ((x, y), lo, la) in enumerate(zip(pixels, lon_w, lat_w))]


def projection_report(model, samples, targets):
    if len(targets) != len(samples):
        raise ValueError("定位投影接口返回的点数不完整")
    points = [dict(map=p["map"], robot=t, role=p["role"], source="fromLL")
              for p, t in zip(samples, targets)]
    report = fit_registration(model, dict(points=points, fit_scale=True, max_error_m=.75))
    # GCJ and the ellipsoid do not preserve exactly the same scale on both axes.
    # Fit an affine projection, then resample the image onto a true metric grid.
    fitted = [p for p in points if p['role'] == 'fit']
    a = np.array([[*p['map'], 1] for p in fitted])
    b = np.array([p['robot'] for p in fitted])
    matrix = np.linalg.lstsq(a, b, rcond=None)[0].T
    determinant = np.linalg.det(matrix[:, :2])
    if not .25 <= determinant <= 4:
        raise ValueError("定位投影比例或方向异常")
    errors = []
    for point in points:
        predicted = matrix @ [*point['map'], 1]
        point.update(predicted=predicted.tolist(), error_m=float(np.linalg.norm(predicted-point['robot'])))
        errors.append(point['error_m'])
    fit_errors = [p['error_m'] for p in points if p['role'] == 'fit']
    check_errors = [p['error_m'] for p in points if p['role'] == 'check']
    report.update(affine=matrix.tolist(), points=points,
                  fit_max_m=max(fit_errors), check_max_m=max(check_errors),
                  fit_rms_m=float(np.sqrt(np.mean(np.square(fit_errors)))),
                  passed=max(errors) <= .75)
    if not report["passed"]:
        raise ValueError("底图与定位投影不能在 0.75 米内统一，请检查底图元数据或地图范围")
    report.update(method="geodetic_fromll", accuracy_verified=False,
                  geographic_samples=samples,
                  accuracy_note="误差仅代表投影近似一致性，不代表卫星影像或 GPS 实测精度")
    return report


def projected_document(model, project, report, revision):
    """Resample affine projection into a north-up square-metre ROS grid."""
    from PIL import Image
    matrix = np.array(report['affine'])
    def transform(point):
        return (matrix @ [*point, 1]).tolist()
    corners = np.array([transform(model.grid_to_world(x, y))
                        for x, y in ((0, 0), (model.width, 0),
                                     (0, model.height), (model.width, model.height))])
    lower, upper = corners.min(axis=0), corners.max(axis=0)
    resolution = model.resolution * math.sqrt(np.linalg.det(matrix[:, :2]))
    width, height = np.ceil((upper-lower)/resolution).astype(int)
    if width * height > MAX_CELLS:
        raise ValueError("自动投影后地图超出栅格上限")
    def pixel(u, v):
        x, y = transform(model.grid_to_world(u+.5, model.height-v-.5))
        return np.array([(x-lower[0])/resolution-.5, height-(y-lower[1])/resolution-.5])
    p0 = pixel(0, 0)
    warp = np.column_stack((pixel(1, 0)-p0, pixel(0, 1)-p0, p0))
    size = (int(width), int(height))
    # Any blocked source pixel contributing to a target pixel remains blocked.
    blocked = cv2.warpAffine((np.flipud(model.base) != 0).astype(np.float32),
                            warp, size, flags=cv2.INTER_LINEAR, borderValue=1) > 0
    pixels = np.where(blocked, 0, 254).astype(np.uint8)
    display = None
    if model.display_image is not None:
        display = Image.fromarray(cv2.warpAffine(np.asarray(model.display_image),
                                  warp, size, flags=cv2.INTER_LINEAR, borderValue=(20, 28, 36)))
    metadata = model.metadata()
    metadata.update(width=int(width), height=int(height), resolution=resolution,
                    origin=[*lower.tolist(), 0], negate=0, free_thresh=.25, occupied_thresh=.65)
    geo = copy.deepcopy(model.context['georeference'])
    geo.update(map_crs='ros_map', navigation_aligned=True,
               registration=dict(**copy.deepcopy(report), target_frame='map',
                   source_revision=revision, saved_at=datetime.now(timezone.utc).isoformat(),
                   source_geometry=dict(origin=model.origin, resolution=model.resolution)))
    metadata['georeference'] = geo
    aligned = MapModel(Image.fromarray(pixels), metadata, display)
    result = copy.deepcopy(project)
    result['map'] = aligned.metadata()
    for kind in ('drivable', 'forbidden'):
        result[kind] = [[transform(point) for point in poly] for poly in result[kind]]
    for point in result['waypoints']:
        point['x'], point['y'] = transform([point['x'], point['y']])
        direction = matrix[:, :2] @ [math.cos(point['yaw']), math.sin(point['yaw'])]
        point['yaw'] = math.atan2(direction[1], direction[0])
    return aligned, aligned.validate(result)
