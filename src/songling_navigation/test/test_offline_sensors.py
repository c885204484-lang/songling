from pathlib import Path

import yaml

from songling_navigation.offline_nav.sensors import nav2_sensor_config


CONFIG = Path(__file__).parents[1] / "config"


def test_map_only_costmaps_keep_static_boundaries_and_collision_checks():
    original = yaml.safe_load((CONFIG / "offline_nav2.yaml").read_text())
    result = nav2_sensor_config(original, False)
    for name in ("local_costmap", "global_costmap"):
        params = result[name][name]["ros__parameters"]
        assert params["plugins"] == ["static_layer", "inflation_layer"]
        assert "obstacle_layer" not in params
        if name == "global_costmap":
            assert params["filters"] == ["keepout_filter"]
            assert params["keepout_filter"]["enabled"]
        else:
            assert params.get("filters", []) == []
            assert params["static_layer"]["map_topic"] == "/offline_nav/footprint_map"
        assert "obstacle_layer" in original[name][name]["ros__parameters"]["plugins"]
    assert result["controller_server"]["ros__parameters"]["FollowPath"]["use_collision_detection"]
    assert nav2_sensor_config(original, True) == original


def test_no_lidar_localization_observes_rotation_without_unitree_imu():
    local = yaml.safe_load((CONFIG / "ekf_odom_no_lidar.yaml").read_text())["/**"]["ros__parameters"]
    global_ = yaml.safe_load((CONFIG / "ekf_map_no_lidar.yaml").read_text())["/**"]["ros__parameters"]
    assert local["odom0"] == "/odom"
    assert local["imu0"] == "/rtk/imu"
    assert local["imu0_config"][5]
    assert local["imu0_relative"]
    assert not any("/unilidar" in str(v) for p in (local, global_) for v in p.values())
    assert global_["imu1"] == "/rtk/imu"
    assert global_["imu1_config"][5]
