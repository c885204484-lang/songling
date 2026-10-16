import os
import launch
import launch_ros
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node

def generate_launch_description():
    return LaunchDescription([
        # 1. 声明环境参数
        DeclareLaunchArgument('use_sim_time', default_value='false'),
        DeclareLaunchArgument('odom_frame', default_value='odom'),
        DeclareLaunchArgument('base_frame', default_value='base_link'),
        DeclareLaunchArgument('odom_topic_name', default_value='odom'),
        DeclareLaunchArgument('simulated_robot', default_value='false'),
        DeclareLaunchArgument('control_rate', default_value='50'),

        # 2. 启动底盘核心节点
        Node(
            package='hunter_base',
            executable='hunter_base_node',
            output='screen',
            emulate_tty=True,
            parameters=[{
                'use_sim_time': launch.substitutions.LaunchConfiguration('use_sim_time'),
                # 核心改动：直接把串口路径和常用的波特率塞给底盘节点
                'port_name': 'can0',          
                'baud_rate': 460800,  
                'robot_model': 'hunter2',
                'odom_frame': launch.substitutions.LaunchConfiguration('odom_frame'),
                'base_frame': launch.substitutions.LaunchConfiguration('base_frame'),
                'odom_topic_name': launch.substitutions.LaunchConfiguration('odom_topic_name'),
                'simulated_robot': launch.substitutions.LaunchConfiguration('simulated_robot'),
                'control_rate': launch.substitutions.LaunchConfiguration('control_rate'),
                
            }],
            # 👇 终极杀招：强制把底盘的 tf 输出重定向到 /tf_dev_null（垃圾桶）
            remappings=[
                ('/tf', '/tf_dev_null')]
        )
    ])