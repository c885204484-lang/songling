"""Offline editor and Nav2; use demo:=true for a hardware-free simulation."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def nodes(context):
    share = get_package_share_directory("songling_navigation")
    get = lambda key: LaunchConfiguration(key).perform(context)
    params = get("params_file")
    demo = get("demo").lower() == "true"
    motion = get("enable_motion").lower() == "true"
    map_path = get("map")
    args = [
        "--ros",
        "--host",
        get("host"),
        "--port",
        get("port"),
        "--store",
        get("store"),
    ]
    if map_path:
        args += ["--map", map_path]
    if demo:
        args += ["--demo"]
    if get("sample_map").lower() == "true":
        args += ["--sample-map"]
    if motion:
        args += ["--enable-motion"]
    overrides = {
        "use_sim_time": False,
        "odom_topic": get("odom_topic"),
        "default_nav_to_pose_bt_xml": os.path.join(
            share, "behavior_trees", "offline_to_pose.xml"
        ),
        "default_nav_through_poses_bt_xml": os.path.join(
            share, "behavior_trees", "offline_through_poses.xml"
        ),
    }
    specs = [
        ("nav2_controller", "controller_server"),
        ("nav2_planner", "planner_server"),
        ("nav2_behaviors", "behavior_server"),
        ("nav2_bt_navigator", "bt_navigator"),
    ]
    result = [
        Node(
            package="songling_navigation",
            executable="offline_map_editor",
            arguments=args,
            parameters=[{"odom_topic": get("odom_topic")}],
            output="screen",
        )
    ]
    for package, executable in specs:
        result.append(
            Node(
                package=package,
                executable=executable,
                name=executable,
                parameters=[params, overrides],
                output="screen",
                remappings=[("cmd_vel", "/offline_nav/cmd_vel")],
            )
        )
    result.append(
        Node(
            package="nav2_lifecycle_manager",
            executable="lifecycle_manager",
            name="offline_lifecycle_manager",
            output="screen",
            parameters=[
                {
                    "autostart": True,
                    "use_sim_time": False,
                    "node_names": [name for _, name in specs],
                }
            ],
        )
    )
    if demo:
        result.append(
            Node(
                package="songling_navigation",
                executable="offline_demo_robot",
                output="screen",
                parameters=[
                    {
                        "map_yaml": map_path,
                        "store": get("store"),
                        "sample_map": get("sample_map").lower() == "true",
                    }
                ],
            )
        )
    return result


def generate_launch_description():
    share = get_package_share_directory("songling_navigation")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "demo",
                default_value="false",
                description="Publish simulated TF, odom and /scan",
            ),
            DeclareLaunchArgument(
                "enable_motion",
                default_value="false",
                description="Allow final velocity gate output",
            ),
            DeclareLaunchArgument(
                "sample_map",
                default_value="false",
                description="Use the synthetic map for regression tests",
            ),
            DeclareLaunchArgument(
                "map", default_value="", description="Optional original ROS map YAML"
            ),
            DeclareLaunchArgument("host", default_value="127.0.0.1"),
            DeclareLaunchArgument("port", default_value="8080"),
            DeclareLaunchArgument("odom_topic", default_value="/odom"),
            DeclareLaunchArgument(
                "store",
                default_value=os.path.expanduser(
                    "~/.local/share/songling/offline_maps/xidian_hangzhou_lvxuelu177"
                ),
            ),
            DeclareLaunchArgument(
                "params_file",
                default_value=os.path.join(share, "config", "offline_nav2.yaml"),
            ),
            OpaqueFunction(function=nodes),
        ]
    )
