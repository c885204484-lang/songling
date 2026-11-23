"""Select map-only Nav2 costmaps without weakening map collision checks."""

import copy


def nav2_sensor_config(config, use_lidar):
    result = copy.deepcopy(config)
    if not use_lidar:
        for name in ("local_costmap", "global_costmap"):
            params = result[name][name]["ros__parameters"]
            params["plugins"] = [p for p in params["plugins"] if p != "obstacle_layer"]
            params.pop("obstacle_layer", None)
    return result
