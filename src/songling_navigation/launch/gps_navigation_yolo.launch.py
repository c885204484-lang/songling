import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, ExecuteProcess, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_dir = get_package_share_directory('songling_navigation')
    
    # ==========================================
    # 🌟 核心：读取 URDF 机器人描述文件
    # ==========================================
    urdf_path = os.path.join(pkg_dir, 'urdf', 'songling.urdf')
    with open(urdf_path, 'r') as infp:
        robot_desc = infp.read()
    
    return LaunchDescription([
        # ==========================================
        # 1. 底盘
        # ==========================================
        LogInfo(msg="\n🟢 [1/10] 启动模块: AgileX Hunter SE 底盘驱动..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('hunter_base'), 'launch', 'hunter_base.launch.py')
            )
        ),
        
        # ==========================================
        # 2. GPS驱动
        # ==========================================
        LogInfo(msg="\n🛰️ [2/10] 启动模块: 轮趣双天线 RTK GPS..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('wheeltec_gps_driver'), 'launch',
                            'wheeltec_dual_rtk_driver_nmea.launch.py')
            ),
            launch_arguments={'port': '/dev/wheeltec_gnss'}.items()
        ),
        
        # ==========================================
        # 3. 雷达
        # ==========================================
        LogInfo(msg="\n🛸 [3/10] 启动模块: 宇树 3D 激光雷达..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('unitree_lidar_ros2'), 'launch.py')
            )
        ),
        
        # ==========================================
        # 4. 机器人状态发布器 (加载 URDF 刚体蓝图)
        # ==========================================
        LogInfo(msg="\n📐 [4/10] 启动模块: Robot State Publisher..."),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{'robot_description': robot_desc}]
        ),
        
        # ==========================================
        # 5. NavSatTransform (GPS投影)
        # ==========================================
        LogInfo(msg="\n🌍 [5/10] 启动模块: NavSatTransform (GPS经纬度转平面坐标)..."),
        Node(
            package='robot_localization',
            executable='navsat_transform_node',
            name='navsat_transform_node',
            output='screen',
            parameters=[
                os.path.join(pkg_dir, 'config', 'navsat_transform.yaml'),
                {'use_sim_time': False}
            ],
            remappings=[
                ('imu', '/unilidar/imu'),
                ('gps/fix', '/gps/fix'),
                ('odometry/filtered', '/odometry/global'),
                ('odometry/gps', '/odometry/gps'),
            ]
        ),
        
        # 修复：加上了注释符，防止 Python 报错崩溃
        # 将3D压缩到2D
        LogInfo(msg="\n🔪 [6/10] 启动模块: 3D点云转2D激光护盾切片..."),
        Node(
            package='pointcloud_to_laserscan',
            executable='pointcloud_to_laserscan_node',
            name='pointcloud_to_laserscan_node',
            remappings=[
                ('cloud_in', '/unilidar/cloud'),   
                ('scan', '/scan')                  
            ],
            parameters=[os.path.join(pkg_dir, 'config', 'pc_to_scan.yaml')]
        ),
        
        # ==========================================
        # 6. 局部EKF
        # ==========================================
        LogInfo(msg="\n🧠 [7/10] 启动模块: 局部 EKF 滤波器 (里程计+IMU)..."),
        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node_odom',
            output='screen',
            parameters=[
                os.path.join(pkg_dir, 'config', 'ekf_odom.yaml'),
                {'use_sim_time': False}
            ],
            remappings=[('odometry/filtered', '/odometry/local')],
        ),
        
        # ==========================================
        # 7. 全局EKF
        # ==========================================
        LogInfo(msg="\n🌐 [8/10] 启动模块: 全局 EKF 滤波器 (融合GPS)..."),
        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node_map',
            output='screen',
            parameters=[
                os.path.join(pkg_dir, 'config', 'ekf_map.yaml'),
                {'use_sim_time': False}
            ],
            remappings=[('odometry/filtered', '/odometry/global')],
        ),

        # ==========================================
        # 8. Nav2 大脑 (预留/修改项)
        # ==========================================
        LogInfo(msg="\n🚀 [准备替换] 启动模块: 原有 Nav2 导航..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('nav2_bringup'), 'launch', 'navigation_launch.py')
            ),
            launch_arguments={
                'use_sim_time': 'False',
                'autostart': 'True',
                'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_new.yaml')
            }.items()
        ),

        # ==========================================
        # 9. 启动 Astra Pro 
        # ==========================================
        LogInfo(msg="\n👁️ [9/10] 启动模块: Astra Pro 相机底层驱动..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('astra_camera'), 'launch', 'astra.launch.py')
            )
        ),

        # ==========================================
        # 10. 启动 YOLOv8 
        # ==========================================
        LogInfo(msg="\n🧠 [10/10] 启动模块: YOLOv8 3D目标检测网络..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('yolo_bringup'), 'launch', 'songling_yolo.launch.py')
            )
        ),
        
        LogInfo(msg="\n✅✅✅ [系统就绪] 感知与底盘链路调度完毕，等待各节点自检... ✅✅✅\n")
    ])