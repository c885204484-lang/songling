#!/usr/bin/env python3
from launch import LaunchDescription
from launch_ros.actions import Node
from launch_ros.actions import ComposableNodeContainer
from launch_ros.descriptions import ComposableNode

def generate_launch_description():
    return LaunchDescription([
        # ==========================================
        # 1. 核心检测节点 (YOLOv8 2D)
        # ==========================================
        Node(
            package='yolo_ros',
            executable='yolo_node',
            name='yolo_node',
            namespace='yolo',
            parameters=[{
                'model': 'yolov8m.pt',
                'device': 'cuda:0',
                'threshold': 0.4,
                'imgsz_width': 640,
                'imgsz_height': 480,
                'enable': True,
                'image_reliability': 1,
                'iou': 0.7,
                'max_det': 300,
                'half': False,
                'augment': False,
                'agnostic_nms': False,
                'retina_masks': False,
                'fuse_model': False,
                'yolo_encoding': 'bgr8',
            }],
            remappings=[('image_raw', '/camera/color/image_raw')],
        ),
        
        # ==========================================
        # 2. 3D 检测节点 (结合深度图算 3D 坐标)
        # ==========================================
        Node(
            package='yolo_ros',
            executable='detect_3d_node',
            name='detect_3d_node',
            namespace='yolo',
            parameters=[{
                'target_frame': 'camera_depth_optical_frame',   # 坐标系没问题
                'depth_image_units_divisor': 1000,
                'depth_image_reliability': 1,
                'depth_info_reliability': 1,
            }],
            remappings=[
                ('depth_image', '/camera/depth/image_raw'),
                ('depth_info', '/camera/depth/camera_info'),
                # 不映射 detections，自动订阅 /yolo/detections
            ],
        ),
        
        # ==========================================
        # 3. 调试可视化节点 (RViz 显示)
        # ==========================================
        Node(
            package='yolo_ros',
            executable='debug_node',
            name='debug_node',
            namespace='yolo',
            parameters=[{
                'image_reliability': 1,
                'show_distance': True,      
                'show_3d_boxes': True,      
            }],
            remappings=[
                ('image_raw', '/camera/color/image_raw'),
                ('detections', 'detections_3d'),   # 显示 3D 检测结果
            ],
        ),

        # ==========================================
        # 🌟 4. 新增：深度图转原始 3D 点云 (底盘避障的数据源)
        # ==========================================
        Node(
            package='depth_image_proc',
            executable='point_cloud_xyz_node',
            name='point_cloud_xyz_node',
            output='screen',
            remappings=[
                ('image_rect', '/camera/depth/image_raw'),           # 订阅相机的深度图
                ('camera_info', '/camera/depth/camera_info'),        # 订阅相机的内参
                ('points', '/camera/depth/points_raw')               # 输出高密度的原始点云
            ]
        ),

        # ==========================================
        # 🌟 5. 新增：Voxel Grid 体素滤波 (采用 ROS2 组件容器模式)
        # ==========================================
        ComposableNodeContainer(
            name='pcl_filter_container',
            namespace='',
            package='rclcpp_components',
            executable='component_container',
            composable_node_descriptions=[
                ComposableNode(
                    package='pcl_ros',
                    plugin='pcl_ros::VoxelGrid',  # 调用 C++ 插件而不是独立节点
                    name='voxel_grid_filter',
                    parameters=[{
                        'filter_field_name': 'z',
                        'filter_limit_min': 0.1,    
                        'filter_limit_max': 3.0,    
                        'filter_limit_negative': False,
                        'leaf_size': 0.05           
                    }],
                    remappings=[
                        ('input', '/camera/depth/points_raw'),               
                        ('output', '/camera/depth/points_filtered')          
                    ]
                )
            ],
            output='screen',
        ),
    ])