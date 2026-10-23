import os
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    IncludeLaunchDescription,
    ExecuteProcess,
    LogInfo,
)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
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
        DeclareLaunchArgument('gps_port', default_value='/dev/ttyACM0',
                              description='GPS serial device'),
        DeclareLaunchArgument('gps_baud', default_value='115200',
                              description='GPS serial baud rate'),
        DeclareLaunchArgument('use_offline_map', default_value='False',
                              description='Use the local annotation workbench and constrained Nav2'),
        DeclareLaunchArgument('offline_map', default_value='', description='Original map YAML in the GPS map frame'),
        DeclareLaunchArgument('offline_store', default_value=os.path.expanduser('~/.local/share/songling/offline_maps/xidian_hangzhou_lvxuelu177')),
        DeclareLaunchArgument('offline_enable_motion', default_value='False'),
        DeclareLaunchArgument('offline_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('offline_port', default_value='8080'),
        DeclareLaunchArgument(
            'use_amap_mask',
            default_value='True',
            description='Publish the Amap semantic keepout mask for Nav2',
        ),
        DeclareLaunchArgument(
            'amap_mask_params',
            default_value=os.path.join(pkg_dir, 'config', 'amap_keepout_mask.yaml'),
            description='Parameter file for the Amap keepout mask node',
        ),
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
            launch_arguments={
                'port': LaunchConfiguration('gps_port'),
                'baud': LaunchConfiguration('gps_baud'),
            }.items()
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
        # 7.5. 高德语义掩码（水域/绿化/田径场/主干道禁行）
        # ==========================================
        LogInfo(msg="\n🌊 [7.5/8] 启动模块: 高德掩码地图 (Nav2 KeepoutFilter)..."),
        Node(
            package='songling_navigation',
            executable='amap_keepout_mask.py',
            name='amap_keepout_mask',
            output='screen',
            parameters=[
                LaunchConfiguration('amap_mask_params'),
                {'use_sim_time': False}
            ],
            condition=IfCondition(PythonExpression([
                "'", LaunchConfiguration('use_amap_mask'), "'.lower() == 'true' and '",
                LaunchConfiguration('use_offline_map'), "'.lower() != 'true'",
            ])),
        ),

        # ==========================================
        # 8. Nav2 大脑
        # ==========================================
        LogInfo(msg="\n🚀 [8/8] 启动模块: Nav2 自动驾驶导航大脑 (工厂模式)..."),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(
                os.path.join(get_package_share_directory('nav2_bringup'), 'launch', 'navigation_launch.py')
            ),
            condition=UnlessCondition(LaunchConfiguration('use_offline_map')),
            launch_arguments={
                'use_sim_time': 'False',
                'autostart': 'True',
                # 'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_mppi_chd.yaml')
                
                'params_file': os.path.join(pkg_dir, 'config', '2026-08-06-1.yaml')

                # 'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_GD.yaml')
                # 'params_file': os.path.join(pkg_dir, 'config', 'nav2_official_base_new_sph.yaml')
            }.items()
        ),

        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(pkg_dir, 'launch', 'offline_navigation.launch.py')),
            condition=IfCondition(LaunchConfiguration('use_offline_map')),
            launch_arguments={
                'map': LaunchConfiguration('offline_map'),
                'store': LaunchConfiguration('offline_store'),
                'enable_motion': LaunchConfiguration('offline_enable_motion'),
                'host': LaunchConfiguration('offline_host'),
                'port': LaunchConfiguration('offline_port'),
                'odom_topic': '/odometry/local',
                'demo': 'false',
            }.items(),
        ),
        
        LogInfo(msg="\n✅✅✅ [系统就绪] 所有核心组件调度完毕，等待各节点自检... ✅✅✅\n")
    ])
