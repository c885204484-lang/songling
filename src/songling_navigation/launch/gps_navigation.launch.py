import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, ExecuteProcess, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_dir = get_package_share_directory('songling_navigation')
    
    # ==========================================
    # 🌟 新增核心：读取 URDF 机器人描述文件
    # ==========================================
    urdf_path = os.path.join(pkg_dir, 'urdf', 'songling.urdf')
    with open(urdf_path, 'r') as infp:
        robot_desc = infp.read()
    
    return LaunchDescription([
        # ==========================================
        # 1. 底盘
        # ==========================================
        LogInfo(msg="\n🟢 [1/8] 启动模块: AgileX Hunter SE 底盘驱动..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('hunter_base'), 'launch', 'hunter_base.launch.py')
            )
        ),
        
        # ==========================================
        # 2. GPS驱动
        # ==========================================
        LogInfo(msg="\n🛰️ [2/8] 启动模块: 轮趣双天线 RTK GPS..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('wheeltec_gps_driver'), 'launch',
                            'wheeltec_dual_rtk_driver_nmea.launch.py')
            ),
            launch_arguments={'port': '/dev/ttyACM0'}.items()
        ),
        
        # ==========================================
        # 3. 雷达
        # ==========================================
        LogInfo(msg="\n🛸 [3/8] 启动模块: 宇树 3D 激光雷达..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('unitree_lidar_ros2'), 'launch.py')
            )
        ),
        
        # ==========================================
        # 4. 机器人状态发布器 (替代原有的静态TF)
        # ==========================================
        LogInfo(msg="\n📐 [4/8] 启动模块: Robot State Publisher (加载 URDF 刚体蓝图)..."),
        Node(
            package='robot_state_publisher',
            executable='robot_state_publisher',
            name='robot_state_publisher',
            output='screen',
            parameters=[{'robot_description': robot_desc}]
        ),
        # ==========================================
        # 4.5. 启动格式转换插头 (将 /gps/pose 转为 /rtk/imu)
        # ==========================================
        LogInfo(msg="\n🔄 [4.5/8] 启动模块: RTK航向转IMU适配器..."),
        Node(
            package='songling_navigation',      
            executable='pose_to_imu.py',     
            name='pose_to_imu_node',
            output='screen'
        ),

        # ==========================================
        # 5. NavSatTransform (GPS投影)
        # ==========================================
        LogInfo(msg="\n🌍 [5/8] 启动模块: NavSatTransform (GPS经纬度转平面坐标)..."),
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
                ('imu', '/rtk/imu'),
                ('gps/fix', '/gps/fix'),
                ('odometry/filtered', '/odometry/global'),
                ('odometry/gps', '/odometry/gps'),
                ('odometry/filtered', '/odometry/local'),
            ]
        ),
        
        # 将3D压缩到2D
        LogInfo(msg="\n🔪 [5.5/8] 启动模块: 3D点云转2D激光护盾切片..."),
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
        LogInfo(msg="\n🧠 [6/8] 启动模块: 局部 EKF 滤波器 (里程计+IMU)..."),
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
        LogInfo(msg="\n🌐 [7/8] 启动模块: 全局 EKF 滤波器 (融合GPS)..."),
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
        # 8. Nav2 大脑
        # ==========================================
        LogInfo(msg="\n🚀 [8/8] 启动模块: Nav2 自动驾驶导航大脑 (工厂模式)..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('nav2_bringup'), 'launch', 'navigation_launch.py')
            ),
            launch_arguments={
                'use_sim_time': 'False',
                'autostart': 'True',
                # 'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_mppi_chd.yaml')
                
                'params_file': os.path.join(pkg_dir, 'config', '2026-08-06-1.yaml')

                # 'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_GD.yaml')
                # 'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_new_sph.yaml')
            }.items()
        ),
        
        LogInfo(msg="\n✅✅✅ [系统就绪] 所有核心组件调度完毕，等待各节点自检... ✅✅✅\n")
    ])