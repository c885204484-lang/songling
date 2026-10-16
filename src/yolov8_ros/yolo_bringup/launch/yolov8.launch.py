#!/usr/bin/env python3
from launch import LaunchDescription
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import LifecycleNode

def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('model', default_value='yolov8m.pt'),
        DeclareLaunchArgument('tracker', default_value='bytetrack.yaml'),
        DeclareLaunchArgument('device', default_value='cuda:0'),
        DeclareLaunchArgument('enable', default_value='True'),
        DeclareLaunchArgument('threshold', default_value='0.5'),
        DeclareLaunchArgument('input_image_topic', default_value='/camera/color/image_raw'),
        DeclareLaunchArgument('image_reliability', default_value='1'),
        DeclareLaunchArgument('namespace', default_value='yolo'),

        LifecycleNode(
            package='yolo_ros',
            executable='yolo_node',
            name='yolo_node',
            namespace=LaunchConfiguration('namespace'),
            parameters=[{
                'model': LaunchConfiguration('model'),
                'tracker': LaunchConfiguration('tracker'),
                'device': LaunchConfiguration('device'),
                'enable': LaunchConfiguration('enable'),
                'threshold': LaunchConfiguration('threshold'),
                'input_image_topic': LaunchConfiguration('input_image_topic'),
                'image_reliability': LaunchConfiguration('image_reliability'),
            }],
            remappings=[('image_raw', LaunchConfiguration('input_image_topic'))],
        ),

        LifecycleNode(
            package='yolo_ros',
            executable='tracking_node',
            name='tracking_node',
            namespace=LaunchConfiguration('namespace'),
            parameters=[{
                'tracker': LaunchConfiguration('tracker'),
                'input_image_topic': LaunchConfiguration('input_image_topic'),
            }],
            remappings=[('image_raw', LaunchConfiguration('input_image_topic'))],
        ),

        LifecycleNode(
            package='yolo_ros',
            executable='debug_node',
            name='debug_node',
            namespace=LaunchConfiguration('namespace'),
            parameters=[{
                'input_image_topic': LaunchConfiguration('input_image_topic'),
                'image_reliability': LaunchConfiguration('image_reliability'),
            }],
            remappings=[('image_raw', LaunchConfiguration('input_image_topic'))],
        ),
    ])