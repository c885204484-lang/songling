import os
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription, ExecuteProcess, LogInfo
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory

def generate_launch_description():
    pkg_dir = get_package_share_directory('songling_navigation')
    
    # ==========================================
    # 🌟 新增核心：读取 URDF 机器人描述文件及地图路径
    # ==========================================
    urdf_path = os.path.join(pkg_dir, 'urdf', 'songling.urdf')
    with open(urdf_path, 'r') as infp:
        robot_desc = infp.read()
        
    # 定义刚才转换好的地图和调优后的参数路径
    map_yaml_path = '/home/nvidia/songling_ws/src/songling_navigation/PCD/final_map.yaml'
    nav2_params_path = '/home/nvidia/songling_ws/src/songling_navigation/config/nav2_params.yaml'

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
        
        # # ==========================================
        # # 2. GPS驱动 (仅采集数据，不参与TF计算)
        # # ==========================================
        # LogInfo(msg="\n🛰️ [2/8] 启动模块: 轮趣双天线 RTK GPS..."),
        # IncludeLaunchDescription(
        #     PythonLaunchDescriptionSource(
        #         os.path.join(get_package_share_directory('wheeltec_gps_driver'), 'launch',
        #                     'wheeltec_dual_rtk_driver_nmea.launch.py')
        #     ),
        #     launch_arguments={'port': '/dev/wheeltec_gnss'}.items()
        # ),
        
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
        # 4. 机器人状态发布器 (加载URDF)
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
        # 5. 将3D压缩到2D (为AMCL和避障提供 /scan)
        # ==========================================
        LogInfo(msg="\n🔪 [5/8] 启动模块: 3D点云转2D激光护盾切片..."),
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
        # 6. 局部EKF (只提供 odom -> base_link)
        # ==========================================
        LogInfo(msg="\n🧠 [6/8] 启动模块: 局部 EKF 滤波器 (里程计+IMU 平滑化)..."),
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
        # 🚨 已屏蔽: 全局EKF 与 NavSatTransform
        # 理由: 采用 AMCL 激光定位时，AMCL 会接管发布 map->odom。
        # 若开启全局EKF，会导致 TF 树冲突，车体定位撕裂！
        # ==========================================
        
        # # ==========================================
        # # 8. Nav2 大脑 (预留/修改项)
        # # ==========================================
        # LogInfo(msg="\n🚀 [准备替换] 启动模块: 原有 Nav2 导航..."),
        # IncludeLaunchDescription(
        #     PythonLaunchDescriptionSource(
        #         os.path.join(get_package_share_directory('nav2_bringup'), 'launch', 'bringup_launch.py')
        #     ),
        #     launch_arguments={
        #         'map': map_yaml_path,                 # 传入你开头的地图路径
        #         'use_sim_time': 'False',
        #         'autostart': 'True',
        #         'params_file': nav2_params_path       # 传入你开头的参数路径
        #     }.items()
        # ),

        #         # ==========================================
        # # 9. 启动 Astra Pro 
        # # ==========================================
        # LogInfo(msg="\n👁️ [9/9] 启动模块: Astra Pro 视觉感知与 YOLOv8 3D检测..."),
        # IncludeLaunchDescription(
        #     PythonLaunchDescriptionSource(
        #         # 请根据实际存放位置确认包名，此处假设与主启动文件同包
        #         os.path.join(get_package_share_directory('astra_camera'), 'launch', 'astra.launch.py')
        #     )
        # ),

        # # ==========================================
        # # 10. 启动 YOLOv8
        # # ==========================================
        # LogInfo(msg="\n👁️ [9/9] 启动模块: Astra Pro 视觉感知与 YOLOv8 3D检测..."),
        # IncludeLaunchDescription(
        #     PythonLaunchDescriptionSource(
        #         # 请根据实际存放位置确认包名，此处假设与主启动文件同包
        #         os.path.join(get_package_share_directory('yolo_bringup'), 'launch', 'songling_yolo.launch.py')
        #     )
        # ),
        # LogInfo(msg="\n✅✅✅ [系统就绪] 所有核心组件调度完毕，等待各节点自检... ✅✅✅\n")
    ])