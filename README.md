# 松灵无人车 ROS 2 工作空间

这是一个面向 **AgileX Hunter SE** 无人车的 ROS 2 工作空间。项目将底盘、双天线 RTK、宇树激光雷达、RGB-D 相机与 YOLO 感知接入 ROS 2，并通过 `robot_localization` 与 Nav2 提供建图、定位和导航能力。

工作空间中的 `build/`、`install/` 与 `log/` 是 `colcon` 的构建产物；日常开发主要阅读和修改 `src/`。

## 先从哪里读

建议按下面的顺序了解系统：

1. `src/songling_navigation/launch/`：系统装配入口，最能说明各模块如何连接。
2. `src/songling_navigation/config/`：坐标融合、点云转激光和 Nav2 的实际参数。
3. `src/songling_navigation/scripts/`：本项目编写的 GPS 航点、路径跟随、状态监控等逻辑。
4. 底盘、RTK、雷达和相机驱动：确认话题、坐标系和串口配置。
5. `point_lio_ros2`：需要激光建图时再阅读。

## 系统数据流

```text
Hunter 底盘 ──> /odom ─┐
RTK / GPS ──> /gps/fix ├─> robot_localization ─> /odometry/local、/odometry/global
雷达 IMU ──────────────┘
宇树 3D 雷达 ─> /unilidar/cloud ─> pointcloud_to_laserscan ─> /scan ─> Nav2
RGB-D 相机 ─> Astra 驱动 ─> yolo_ros ─> 检测、跟踪和 3D 检测话题
```

`songling_navigation/urdf/songling.urdf` 描述机器人坐标系；启动前应保证底盘、RTK、雷达和相机的实际安装外参与该文件及各驱动配置一致。

## `src` 目录说明

| 目录 | 作用 | 建议关注内容 |
| --- | --- | --- |
| `songling_navigation` | 本项目的导航集成包 | `launch/`、`config/`、`scripts/`、`urdf/`、`PCD/` |
| `hunter_ros2` | AgileX Hunter ROS 2 底盘驱动 | `hunter_base/launch/hunter_base.launch.py` |
| `ugv_sdk` | AgileX 底盘通信 SDK | 协议实现与 Hunter 示例 |
| `wheeltec_gps_driver` | 维特智能/G90 GNSS、NMEA 与轨迹驱动 | `launch/`、`config/`、`src/gps_path.cpp` |
| `wheeltec_dual_rtk_driver` | 双天线 RTK 的 Python 串口驱动 | `wheeltec_dual_rtk_driver.py`、`um982_serial.py` |
| `nmea_msgs` | NMEA 专用 ROS 消息定义 | `msg/` |
| `nmea_navsat_driver` | 通用 NMEA 串口、TCP/UDP 解析器 | `src/libnmea_navsat_driver/` |
| `unilidar_ros2` | 宇树激光雷达 ROS 2 驱动 | `launch/launch.py`、`src/unitree_lidar_ros2_node.cpp` |
| `unitree_lidar_sdk` | 宇树雷达底层 SDK | `include/`、`examples/` |
| `point_lio_ros2` | Point-LIO 激光-惯性里程计与建图 | `launch/mapping_unilidar_l2.launch.py`、`config/unilidar_l2.yaml` |
| `spark-fast-lio-main` | FAST-LIO 的另一套实现/实验依赖 | `spark_fast_lio/` |
| `ros2_astra_camera-ros2` | Orbbec Astra RGB-D 相机驱动 | `astra_camera/launch/astra.launch.py` |
| `yolov8_ros` | YOLO ROS 2 封装，包含检测、跟踪与 3D 检测 | `yolo_bringup/launch/songling_yolo.launch.py` |
| `pcd2pgm` | 将 PCD 点云地图转换为 Nav2 可用的 PGM 地图 | `launch/pcd2pgm_launch.py`、`config/pcd2pgm.yaml` |
| `archives` | 历史或备份资料，不参与运行 | 除非恢复依赖，否则无需修改 |

## 本项目核心包：`songling_navigation`

### 启动文件

| 文件 | 用途 |
| --- | --- |
| `gps_navigation.launch.py` | RTK 全局导航：启动底盘、RTK、雷达、URDF、点云转 `/scan`、局部/全局 EKF 和 Nav2。 |
| `gps_navigation_yolo.launch.py` | 在 RTK 导航基础上加入 Astra 相机和 YOLOv8 感知。 |
| `map_navigation.launch.py` | 基于已有栅格地图的导航入口；其中 AMCL 应发布 `map -> odom`，因此全局 EKF 与 `navsat_transform` 被注释以避免 TF 冲突。 |
| `mapping_l2.launch.yaml` | 使用 L2 雷达建图，实际启动 `spark_fast_lio` 并将 `/unilidar/cloud`、`/unilidar/imu` 接入其输入。 |

### 配置与脚本

- `config/ekf_odom.yaml`、`config/ekf_map.yaml`：`robot_localization` 的局部和全局 EKF 参数。
- `config/navsat_transform.yaml`：经纬度到局部平面坐标的投影和融合参数。
- `config/pc_to_scan.yaml`：从 3D 点云切出 Nav2 避障所需的 2D `/scan`。
- `config/nav2_*.yaml`、`nav2_params.yaml`：Nav2 行为树、代价地图、局部规划器等参数的不同调优版本。
- `scripts/gps_waypoint_sender2_chd.py`：GPS 航点发送逻辑。
- `scripts/amap_path_follower.py`：高德路径的跟随逻辑。
- `scripts/pose_to_imu.py`：将 RTK 位姿/航向转换为 `robot_localization` 可使用的 IMU 输入。
- `scripts/navigation_monitor.py`：导航运行状态监控。
- `PCD/final_map.yaml`：已有地图的元数据；对应的 PGM/PCD 文件体积较大，不应随意复制或提交。

## 构建

在已安装 ROS 2 及项目依赖的 Linux 机器人计算机上执行：

```bash
cd ~/songling_ws
source /opt/ros/<distro>/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

`<distro>` 必须替换为机器实际安装的 ROS 2 发行版。YOLO 包还依赖 Python/Ultralytics 环境，具体安装方法见 `src/yolov8_ros/README.md`；不同传感器驱动也可能需要厂商 SDK、USB/串口权限和 udev 规则。

## 常用启动方式

每个新终端都先加载环境：

```bash
cd ~/songling_ws
source /opt/ros/<distro>/setup.bash
source install/setup.bash
```

随后按任务选择一个入口：

```bash
# RTK 全局导航
ros2 launch songling_navigation gps_navigation.launch.py

# RTK 全局导航 + Astra 相机 + YOLO
ros2 launch songling_navigation gps_navigation_yolo.launch.py

# 地图定位所需的传感器、URDF、点云切片与局部 EKF
# 注意：其中的 Nav2/AMCL 段目前处于注释状态，见下方说明
ros2 launch songling_navigation map_navigation.launch.py

# L2 雷达建图
ros2 launch songling_navigation mapping_l2.launch.yaml
```

## 运行前检查

1. 确认底盘 CAN/串口、RTK 串口和雷达 USB 设备均已连接，且当前用户具备访问权限。
2. 检查启动文件中的设备路径：`gps_navigation.launch.py` 默认使用 `/dev/ttyACM0`，YOLO 版本使用 `/dev/wheeltec_gnss`。
3. 检查 RTK、雷达、相机与车体之间的外参，以及 `songling.urdf` 的坐标系命名。
4. 仅运行一种全局定位来源：RTK+全局 EKF 或 AMCL 地图定位。二者同时发布 `map -> odom` 会造成 TF 冲突。
5. `map_navigation.launch.py` 当前将 Nav2、AMCL 相关启动段注释掉了，所以它只会启动传感器、坐标发布、点云切片和局部 EKF。若要恢复完整地图导航，先确认地图、参数、TF 树无冲突后再启用该段。
6. 该启动文件中的地图和 Nav2 参数路径仍以 `/home/nvidia/songling_ws/...` 写死；启用前应替换为本机实际路径，或改为从包共享目录取得路径。

## 开发约定

- 修改 Python、launch、YAML 或 URDF 后执行 `colcon build --symlink-install` 并重新 `source install/setup.bash`。
- 新增 ROS 包放在 `src/`；不要手动编辑 `build/`、`install/` 与 `log/`。
- 修改传感器话题或坐标系时，沿着启动文件检查 remapping、EKF 配置、URDF 与 Nav2 配置，确保它们一致。
- 先在离线 rosbag 或架空状态下验证控制、路径和参数，再上车测试。

## 当前项目的边界

`src/` 不是单一来源仓库，而是一个集成工作空间：既有本项目的 `songling_navigation`，也有厂商驱动、SDK 和上游开源包。日常功能开发应优先落在 `songling_navigation`；只有在需要修复协议、驱动或上游算法时，才修改对应依赖包，并单独记录其来源和改动原因。
