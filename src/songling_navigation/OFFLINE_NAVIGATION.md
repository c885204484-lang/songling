# 离线地图标注与 Nav2 导航

这套工作台在本机运行，不请求高德、CDN 或其他外部服务。它与原有高德语义掩码功能分开，使用工程现有的宇树激光雷达 `/scan`，适用于先离线画区域、再验证 Nav2 路径和避障。

离线实车 launch 将点云转扫描的角度间隔设为 `0.005 rad`，匹配局部代价地图的 `0.1 m` 栅格；原来的 `0.025 rad` 在较远处会留下清除射线之间的空隙，旧回波可能残留。激光有效回波继续标记障碍，静态禁行区、车身尺寸和碰撞检测保持启用。`observation_persistence: 0` 仅限制观测缓存，不会让已经写入的障碍格自动过期。

控制器失败后，行为树先清理局部缓存，再从当前位置重新规划剩余目标，才重试跟踪。不能仅重发原来的长路径：Humble RPP 的内部路径已经随行驶被裁剪，重发会重置裁剪进度；默认前 `10 m` 的最近点搜索可能找不到车辆周围局部窗口内的点，继而报 `Resulting plan has 0 poses in it`。正常跟踪仍复用有效路径，不因此恢复周期性重规划。

清图后先等待 `1 s`（Humble Wait 节点使用整数秒），给局部地图重建及新扫描留出时间，再规划并跟踪。行为树服务超时由 `20 ms` 改为 `200 ms`；Humble 在配置导航器时读取此参数，运行中修改参数后还需重新配置 Nav2 才会生效。该值只调整服务响应等待，不修改 CAN、激光或里程计失效门槛。碰撞恢复仍失败时，任务显示“已暂停”，保留进度供用户决定继续。

点击简洁页面的“开始导航”，先显示“继续刚才任务”“从航点 1 重新执行”“仅到终点”以及取消选项。继续任务使用服务器的 `mission.json` 检查点，按 Nav2 `number_of_poses_remaining` 推进原始目标序列；不按离小车最近的航点推断，避免 8 字交叉误跳航点。取消、失败、仅规划和页面刷新不会清空检查点，成功到达才结束任务。服务重启后只恢复待继续状态，不自动发车。原终点及其朝向保存在任务中，继续时会在弹窗显示；新选择的终点用于从头执行或直接到终点。地图约束或航点改变时禁止继续旧任务。旧版未记录进度的任务必须由用户确认下一目标。

`POST /api/resume` 接受 `task_id`，可选显式 `from_index`（从 0 开始）；恢复请求与普通导航通过同一套底盘、定位、地图和激光检查。`runtime.mission` 提供进度摘要。控制器再次报碰撞时，`diagnostics/collision-latest.json` 保存清图前最近三帧局部栅格、对应 map 变换、激光点及预测轨迹，避免清理后丢失触发证据。USB 断连后有效反馈未恢复时仍拒绝继续。

原生回归使用本机 Nav2 的射线清除算法及行为树控制节点，不发送车辆命令：先 `source /opt/ros/humble/setup.bash`，再运行 `cmake -S src/songling_navigation/test/native -B /tmp/songling-native-regression`、`cmake --build /tmp/songling-native-regression -j2` 和 `ctest --test-dir /tmp/songling-native-regression --output-on-failure`。扫描测试使用独立 ROS 域 94；恢复测试覆盖正常路径复用、失败后重规划，以及规划失败时不继续跟踪。

## 默认场地：杭州研究院新园区

默认地图已切换为 **西安电子科技大学杭州研究院，旅学路177号新园区** 的真实卫星底图。地址已与[研究院官方页面](https://hyyzp.xidian.edu.cn/portal/index)及高德 POI 核对；不会加载钱农东路8号过渡园区。

底图文件位于 `maps/xidian_hangzhou/`，覆盖约 **825 × 825 米**，1600 × 1600 像素，约 **0.516 米/像素**。`basemap.png` 为缓存的高德卫星影像，`street.png` 为同范围普通地图，`map.yaml` 保存米制分辨率及中心 WGS-84/GCJ-02 参考，`source.json` 记录来源。网页启动和操作无需联网；服务密钥不进入网页或地图包。卫星影像的实际拍摄日期未由提供方标注。

彩色底图与导航栅格分别保存。底图只提供真实场地参考，不会把影像亮暗、文字或屋顶颜色当成障碍栅格；`occupancy.pgm` 是空白标注画布。默认无可行驶区、无预设航点，必须按现场道路手动圈出可行驶区与禁行区，未圈区域一律禁行。

园区坐标原点为底图中心，x 向东、y 向北。它尚未和实车 RTK/SLAM 的 map 坐标配准：允许离线编辑及仿真，实车模式会拒绝直接应用未配准参考底图。已配准的 ROS 地图仍可通过 `--map` 或导入使用。

## 启动

园区整车启动 `gps_navigation.launch.py use_offline_map:=True` 默认使用无雷达模式，也可显式加 `use_lidar:=False`。该模式不启动宇树雷达及点云切片，Nav2 仅使用静态地图、禁行掩码和膨胀层，不等待 `/scan`；定位使用底盘轮速及双天线 RTK 航向，局部滤波根据连续航向观测估计角速度，不依赖雷达 IMU。底盘反馈、定位、里程计、路径偏离和地图边界检查继续生效。无雷达模式不检测临时出现的行人或障碍物，需将固定障碍标注到地图中。

`/map` 和全局禁行掩码表示带 0.65 米车身余量的安全车心区域；速度门控也用该区域检查预测车心轨迹。局部控制器保留完整车身碰撞检查，但静态层改用 `/offline_nav/footprint_map`：该图包含原图障碍、未知区、可行驶区边界和全部禁行标注，不再预加一次车身余量。局部层不再叠加同一份已扩边的全局禁行掩码，避免转角处重复计算车身。物理车身碰撞检查、0.65 米安全距离及定位检查均保留。

单独启动 `offline_navigation.launch.py` 时加 `use_lidar:=false`；直接运行工作台时加 `--ros-args -p use_lidar:=false`，并确保外部 Nav2 同样关闭雷达障碍层。独立仿真默认保留雷达模式；恢复整车雷达模式加 `use_lidar:=True`。

在工作区根目录执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select songling_navigation
source install/setup.bash

# 仅网页编辑：不启动 ROS 节点，不连接底盘
ros2 run songling_navigation offline_map_editor

# 使用自己的 ROS 地图（YAML 引用的 PGM/PNG 需存在）
ros2 run songling_navigation offline_map_editor \
  --map src/songling_navigation/PCD/final_map.yaml
```

浏览器访问 **http://127.0.0.1:8080**。也可直接从源代码启动，无需 colcon：

```bash
PYTHONPATH=src/songling_navigation python3 -m songling_navigation.offline_nav.server \
  --store /tmp/songling-map-test
```

编辑模式仅依赖 Python 标准库、NumPy、OpenCV、Pillow 和 PyYAML。ROS 集成模式使用 ROS 2 Humble 和已有 Nav2 软件包。

## 网页操作

1. 默认加载旅学路177号新园区真实卫星底图；或用“导入地图”选择原始 YAML、它引用的 PGM/PNG，以及可选的 `project.json`。恢复园区地图包时选择 **original.yaml + original.pgm + basemap.png**，保留彩色底图、坐标信息及原图障碍。
2. 选择“可行驶区域”，逐点点击、按 Enter 完成多边形。可绘制多个区域，它们取并集；可行驶区之外全部禁行。
3. 选择“禁行区域”，同样绘制多边形。禁行区优先，原始地图的障碍和未知区域也始终禁行。Esc 放弃未完成区域；“撤销”恢复上一次编辑；图层列表支持删除重画。
4. 点击添加航点，列表支持名称、航向修改和顺序调整。终点既可在地图上点击，也可输入 map 坐标和航向。
5. 设置边界安全距离，默认 **0.65 m**，包含现有车身外接圆半径与余量。导航模式要求至少 0.65 m；自由空间会向内收缩、禁行区向外扩张，栅格离散误差另作保守补偿。
6. “保存当前地图”持久化原图、地图参数和全部标注；“保存并预览导航掩码”显示实际禁行栅格。狭窄通道可能因车身余量而被关闭，检查预览后再导航。
7. “导出地图包”下载 ZIP，内含 `original.pgm/.yaml`、`project.json`、`keepout.pgm/.yaml`、`navigation.pgm/.yaml`。navigation 地图已经合并区域约束及原图障碍；keepout 使用相同的保守二值栅格。
8. ROS 模式下保存后点击“应用已保存地图到 Nav2”，等待约 1 秒，然后“仅规划”检查路径，或“开始导航”。执行任务时必须先取消，才能切换地图。航点任务调用 `NavigateThroughPoses`，逐点航向会参与规划。

保存路径默认 `~/.local/share/songling/offline_maps/xidian_hangzhou_lvxuelu177`，与旧示例地图目录分开；旧目录不会被覆盖。每次保存生成独立目录，`latest.json` 指向最近完整快照；网页重启后自动恢复。`--store` 可设置其他目录；不会改写输入地图。导出的 YAML 使用相对图片路径，移动目录后仍可加载。

网页左侧“地图保存位置”显示当前快照的绝对目录；该目录在运行服务的 Jetson / 小车上。“导出地图包”下载到浏览器所在电脑，两者位置不同。`project.json` 保存区域和航点，`basemap.png` 为彩色底图，`navigation.yaml` 配合 `navigation.pgm` 为合并约束后的导航地图。

## 当前小车位置作为起点与 ROS 连接

右侧“起点 · 小车当前位置”显示 `map → base_link` 的实时 X、Y 和朝向，地图上的绿色“小车 / 起点”随定位更新；“定位到当前起点”将视图居中到小车。`ComputePathToPose` 显式使用 `use_start=False`，由 Nav2 读取规划当时的小车位置；单点和航点导航同样从实时定位出发。起点无需手动填写，也不会被保存为固定航点。定位缺失、过期或落在禁行区时会拒绝导航。离线模式没有真实起点；仿真位置由模拟器提供。

点击顶部“连接 ROS”查看启动命令和当前接口状态，包括 ROS_DOMAIN_ID、定位 TF、有效激光数据、规划 / 导航 action 是否发现及运动开关。action 已发现只表示服务被 DDS 发现，能否接受任务仍由 Nav2 状态和地图检查决定。浏览器通过 HTTP 访问工作台，工作台进程通过 `--ros` 接入 ROS 2；编辑模式不能通过网页按钮直接变成已连接实车。

已有工程接实车时，先停止原编辑服务和原导航 launch，再执行下列命令（自动恢复默认目录的已保存地图，默认仅规划）：

```bash
cd ~/songling/songling_ws
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch songling_navigation gps_navigation.launch.py use_offline_map:=True
```

启动后刷新 `http://127.0.0.1:8080`。确认定位、激光及地图配准完成，保存并应用地图后选择终点、仅规划。启用行驶需设置 `offline_enable_motion:=True`。当前园区卫星底图尚未配准，实车模式会拒绝应用；连接 ROS 本身不会完成地图配准，也不能靠点选起点修正 RTK 坐标。

若只先体验 ROS 联动，在上面的 source 命令后改为运行 `ros2 launch songling_navigation offline_navigation.launch.py demo:=true enable_motion:=true`；两条 launch 只选一种。该命令同样读取已保存地图，但使用模拟小车，默认从 `(0,0)` 开始。跨设备运行 ROS 节点时使用相同 ROS_DOMAIN_ID 并允许 DDS 通信；只访问网页的电脑无需安装 ROS。

## 网页地图配准

顶部“地图配准”打开右侧配准面板，保留地图供选点。入口会先保存当前标注；正在规划或导航时需先取消任务。操作步骤：

1. 先固定定位模块的 map 原点及朝向（GPS 使用固定 datum），确认重启后坐标一致；配准页面不会修改定位配置。
2. 小车停稳，在地图选择车体 base_link 对应的地面位置，点击“读取当前小车位置并添加点”。后端读取有效且未过期的 map→base_link 定位；离线可手工输入已记录的 ROS map X、Y。
3. 采集至少 3 个分散、不共线的配准点，另采至少 1 个独立检查点，并在该点勾选“独立检查点”。对应点可删除后重新采集。检查点不参与拟合。
4. 默认只估计平移和旋转，保留原图分辨率；勾选“同时校正比例尺”后采用统一比例变换。点击计算，查看拟合 RMS、各点误差、独立检查误差、旋转、平移与估计比例。地图连线表示误差在原图坐标中的方向和大小。
5. 设定现场可接受误差（默认 0.75 米，应结合道路余量），所有配准点与检查点都通过后，确认定位坐标系已固定，点击“另存配准地图”。

保存生成一个新快照，保留源快照。原图和彩色底图的像素不变，统一转换地图 origin、resolution、区域顶点及航点位置和朝向；安全距离仍以真实米制值保留。`original.yaml` 的 georeference.registration 保存来源快照、转换参数、对应点与误差，导航 YAML 同样保留配准记录。结果自动载入，需重新应用到 Nav2，才会更新导航地图；不会自动启动车辆。仿真采集或仿真服务中生成的结果保留未完成实车配准标志，仅供仿真。

对应点草稿保存在当前浏览器的 localStorage，并按地图图像指纹、几何及数据目录区分；刷新可恢复，不等于服务器保存。改变点位、角色、比例选项或误差阈值后需重新计算。手工输入的坐标必须与当前定位的 map 坐标一致。地图配准不会提高卫星影像本身的分辨率或修正定位漂移。原图仍限制 400 万栅格，旋转后内部导航网格限制为 800 万栅格，以支持默认园区底图的任意平面旋转。

也可使用“经纬度自动对齐（无需采点）”：原始高德底图通过像素 Web Mercator 坐标、GCJ-02 → WGS84，再调用正在运行的 `navsat_transform_node` 的 `/fromLL` 接口，转换至当前 ROS map。该方式复用定位模块的原点、投影和朝向，无需移动小车采集多个对应点；适用于带完整 georeference 元数据的原始底图。转换使用 5 个分散采样点拟合仿射投影、4 个点验证投影近似，再将底图重采样为正北朝上的方形米制栅格并转换所有标注，各点残差必须在 0.75 米内。此残差仅验证数学投影一致性，不能代表卫星影像精度或 GPS 实测精度。结果记录 `method: geodetic_fromll`、`accuracy_verified: false`，保留原快照并同步转换标注，保存后仍需重新应用地图。GPS 定位必须维持同一个固定 datum；变更 datum 后需从原始快照重新转换。普通 GPS 或 RTK 浮点解的漂移不会因自动对齐而消失。

地图配准入口和强制现场精度配准门槛已移除。保留当前底图、坐标变换、配准来源和误差记录；历史 `accuracy_verified: false` 不再禁用导航按钮或阻止导航请求。规划和导航仍检查可行驶区、禁行区及安全边距，底盘急停/CAN 档位、激光避障、定位超时及路径偏离保护继续生效。不会自动发起导航。

若目前只确定一个现场角点，可通过配准 preview/save 接口传 `method: landmark_translation` 和一个 `points` 对应点，另存平移预览。此模式只平移底图、区域、航点及终点，保留原快照；始终记录 `passed: false`、`accuracy_verified: false`。实测目标坐标必须使用角点本身的位置，需将 RTK 天线到角点的车体偏移按车头方向旋转至 map 后再相加；不能把车旁柱子与天线当作同一点。预览不能替代完整的现场配准。

接口：`POST /api/registration/pose` 采集实时位姿；`POST /api/registration/preview` 计算但不保存；`POST /api/registration/save` 重新计算并检查后另存。自动投影在 preview/save 请求中传 `method: "geodetic_fromll"`，同时传当前 `revision` 和已保存的 `project`，无需 points。配准模块位于 `offline_nav/registration.py`，自动投影位于 `offline_nav/geodetic.py`，网页面板位于 `web/offline_nav/registration.js`。

## 不接实车的完整仿真

```bash
export ROS_DOMAIN_ID=87
ros2 launch songling_navigation offline_navigation.launch.py \
  demo:=true enable_motion:=true store:=/tmp/songling-offline-demo
```

此启动文件只拉起网页、Nav2、模拟小车和模拟激光，不启动硬件驱动。请在独立终端设置 `ROS_DOMAIN_ID=87` 后启动，以便与其他 ROS 系统隔离；所有观察命令也使用同一 domain。

默认使用真实园区底图，需先手工标注可行驶区和航点。若要运行固定的回归示例，可增加 `sample_map:=true` 并使用单独 `store` 目录；该示例才带有中央实体障碍和 `(26, 0)` 绕障终点。打开网页，保存并应用地图，点击“仅规划”检查绕行；再开始导航。用“仿真障碍”工具在路径上放障碍，橙色激光点会出现；Nav2 更新全局/局部代价地图并重新规划，速度门控在预计碰撞时停止输出。可用“清除仿真障碍”恢复。仿真会读取已保存的原图，应用新地图时也会同步更新模拟激光看到的实体墙面；手绘禁行区只作为导航约束。此仿真是二维运动学验证，不代表实车动力学测试。

如果指定 `map:=/path/map.yaml`，仿真起点默认为 map `(0,0,0)`，必须处于可行驶区。其他起点可单独启动 `offline_demo_robot --ros-args -p initial_x:=... -p initial_y:=... -p initial_yaw:=...`，不要重复启动两个模拟器。

## 接现有底盘与激光雷达

实车门控还检查所选 `odom_topic` 的消息时间、有限数值及速度协方差，并将前向速度与 `/hunter_status` 轮速比较。局部滤波只融合轮速和角速度，没有绝对位置/航向观测，其累计位姿协方差不能作为全局定位精度设置固定上限；系统仍拒绝非有限或负协方差，速度方差超过 0.25 时报告具体轴和数值。轮速中断时 EKF 仍可输出带新时间戳的预测值，因此仅有 TF 或“ROS 已连接”不足以允许运动。GPS 整车模式使用 `/odometry/local`；单独启动工作台接同一定位栈时也需加 `--ros-args -p odom_topic:=/odometry/local`。宇树驱动通过 IMU 消息发布角速度方差（可配置 `imu_angular_velocity_variance`，默认 0.0025 rad²/s²）；EKF YAML 中的 `imu0_*_covariance` 不是有效的覆盖参数。

每次导航等待本次任务的有效路径后才允许输出速度。Nav2 重规划时，先检查车辆是否已偏离旧路径；只有旧路径偏差不超过 0.75 米、定位新鲜、新路径起点距车辆不超过 0.75 米且终点与任务一致，才同步更新跟踪参考，并等待新的控制器速度指令。实际位置或未来 1.5 秒速度轨迹偏离当前参考路径超过 0.75 米会停车并取消任务；重规划不能清除已经发生的偏离或恢复已取消任务。界面显示同一条参考路径，失败后保留显示。底盘或里程计异常同样取消任务，数据恢复不会自动续跑。普通 GPS 漂移也可能触发此保护，应先改善定位，不能通过放松禁行区来绕过。该保护不能替代定位精度验证，也不能保证车辆在制动距离内绝对不越界。

先启动底盘、宇树激光雷达、工程已有 `pointcloud_to_laserscan` 以及定位模块，使以下接口可用：

| 接口 | 要求 |
| --- | --- |
| `/scan` | `sensor_msgs/LaserScan`，时间戳有效，建议 ≥ 10 Hz |
| `/odom` | `nav_msgs/Odometry`，与 TF 的 odom 一致；GPS 栈可将 `/odometry/local` 重映射到此话题 |
| `map → odom → base_link` | 定位持续更新；AMCL 或现有 GPS EKF 提供，不要同时让两者发布 map→odom |
| 雷达 frame → base_link | URDF/静态 TF 已接通 |
| `/cmd_vel` | Hunter 底盘接收 `geometry_msgs/Twist` |

离线 YAML 的 resolution、origin、yaw 必须与当前定位的 map 坐标一致；普通截图需要先完成米制标定和地图配准，不能将图片像素当作 GPS 坐标。此工作台不会自动把 GCJ-02 图片对齐到 RTK map 系。

```bash
# 默认仅允许规划
ros2 launch songling_navigation offline_navigation.launch.py \
  map:=/absolute/path/original.yaml

# 使用相同地图、已就绪的外部定位与雷达，启用导航速度输出
ros2 launch songling_navigation offline_navigation.launch.py \
  map:=/absolute/path/original.yaml enable_motion:=true
```

已有 GPS 整车启动文件也提供一键接入：

```bash
ros2 launch songling_navigation gps_navigation.launch.py \
  use_offline_map:=True offline_map:=/absolute/path/original.yaml \
  offline_enable_motion:=True
```

此模式保留工程已有的底盘、宇树雷达、点云切片、GPS 和 EKF 启动，自动使用离线工作台替代原 Nav2 与高德掩码，并将里程计设为 `/odometry/local`。必须先检查原图与本次 GPS datum 的 map 坐标是否一致。`offline_enable_motion` 默认为 False，先仅规划再启用运动。

`offline_navigation.launch.py` 本身负责整套 Nav2；单独使用它时停止其他 Nav2、原高德掩码发布器和其他 `/cmd_vel` 发布节点。不要同时运行两条导航 launch 命令。

网页默认绑定回环地址。需要局域网访问时可设置 `host:=0.0.0.0`，仅在受信任网络中使用；当前服务没有用户账号认证。远程浏览器优先使用 SSH 端口转发，保持回环绑定。

## 数据流与代码分区

```text
web/offline_nav/                     HTML / CSS / JS，无构建依赖
songling_navigation/offline_nav/
  maps.py                           地图导入、坐标变换、区域校验和栅格化
  store.py                          不可变快照、原子切换、标准地图 ZIP
  server.py                         HTTP API；不依赖 ROS 的编辑模式
  ros_bridge.py                     地图发布、Nav2 actions、遥测、最终速度门控
  demo.py                           独立运动学小车与激光扫描仿真
config/offline_nav2.yaml             静态图、激光障碍、膨胀层、双侧 KeepoutFilter
launch/offline_navigation.launch.py  独立启动，不自动连接硬件
behavior_trees/offline_*.xml         周期重规划、清图与等待恢复
test/test_offline_nav.py             区域、坐标、持久化和 API 回归验证
```

`/map` 和 `/offline_nav/keepout_mask` 都是应用后的保守导航网格，使用 transient-local QoS；`/offline_nav/filter_info` 提供 KeepoutFilter 描述。全局静态地图范围固定，局部为滚动窗口；两者都接入 `/scan`。Smac Hybrid-A* 使用前进 Dubins 运动模型和 1.9 m 最小转弯半径；RPP 控制器关闭原地旋转和倒车。单终点及多航点行为树每秒检查原路径，路径仍有效且目标未改变时继续复用，只有障碍使路径失效或剩余目标改变才重规划；多航点仍按顺序移除已通过点。避免在终点附近反复丢弃有效直线路径，改算满足终点姿态的回转。恢复动作保留清图和等待，动态障碍仍可触发绕行。末段提前 2 米减速，终点位置及朝向容差不变。

工作台为导航 XML 生成带内容哈希的不可变快照，并在导航 action 中指定该文件，避免 Nav2 继续使用同名 XML 的旧缓存。ROS 执行器使用两个工作线程；里程计、原始底盘反馈、GPS 和定位状态采集使用独立回调组，避免地图/控制回调占用时延迟接收。隔离域验证：人为阻塞控制回调 0.75 秒时，传感器接收仍保持更新；测试入口 `test/integration_offline_callback_groups.py` 必须使用非零 `ROS_DOMAIN_ID`，不会运行实际导航。

Nav2 原始速度只发布到 `/offline_nav/cmd_vel`；`ros_bridge.py` 在 20 Hz 将检查后的速度发布到 `/cmd_vel`。未启用运动、无导航任务、定位/激光/速度指令超时、预测轨迹越界或遇障均输出零速。门控按当前速度预测 1.5 秒，激光超时阈值 0.6 秒、定位 0.5 秒、指令 0.3 秒；参数需结合实车扫描频率、定位延迟及制动能力现场验收。

滤波里程计超过 0.5 秒未收到有效数据时立即保持零速；有效数据总年龄达到 1.5 秒时取消任务。恢复须连续收到 3 帧有效且间隔不超过 0.5 秒的数据，并等待新的控制器速度指令，不复用暂停前的指令。新鲜有效数据到达后，不能因“首次暂停已经超过 1 秒”而继续中止任务。数值异常、与底盘速度不一致、底盘故障或轨迹偏离仍立即取消。乱序旧里程计不会覆盖更新的数据。最近 10 次等待、恢复或超时事件及触发年龄保存在 `/api/state` 的 `runtime.odometry.events`，同时写入工作台日志；持续断流取消后不自动重启任务，并清除暂停中的状态。

实车使用 `/odometry/local` 时，工作台独立订阅 `/odom` 核验原始底盘输入。原始输入超过 0.5 秒未更新或数值/坐标系无效时立即停止并取消，不能由仍在外推的 EKF 输出解除；仅在原始输入正常而滤波输出短暂延迟时执行上述有限等待。`runtime.wheel_odometry` 记录原始输入新鲜度及原因。USB/CAN 掉线时页面显示“底盘原始里程计中断”和“等待底盘反馈”，避免将新鲜的外推输出当成底盘恢复。

网页地图读写与 ROS 状态使用独立锁；栅格生成、压缩、磁盘写入及网络下载均在文档锁之外执行。导航命令在保存期间排队，保持应用地图先于发送终点的顺序；取消使用单独优先队列，速度保护不等待保存或导出。空扫描、全部 NaN/无效距离、无效 TF 不会刷新传感器看门狗；合法的正无穷无回波扫描仍正常处理。

原地图 origin 可以包含 yaw。编辑坐标保留原图旋转；导出的导航图和发布给 Nav2 的网格会保守重采样到 yaw=0，避免轴对齐代价地图忽略旋转。重采样额外收缩一个源栅格的安全范围，网页掩码预览使用同一导航结果。`/offline_nav/source_map` 保留原始障碍、未知区域和旋转，供仿真同步实体地图。

网页“仅规划”调用 `ComputePathToPose`，“开始导航”调用 `NavigateToPose`，“按顺序导航”调用 `NavigateThroughPoses`。终点与航点必须在实际安全栅格内；保存不会悄悄改变正在执行的导航地图。取消立即关断速度门控，并等待 Nav2 action 结束后再允许新任务。

参考 Nav2 官方说明：[KeepoutFilter](https://docs.nav2.org/rolling/tutorials/general_tutorials/navigation2_with_keepout_filter/navigation2_with_keepout_filter/)。掩码在全局与局部代价地图中同时启用；静态层在普通膨胀层之前加入，二值掩码本身也预留了车身余量。

## 验证

```bash
source /opt/ros/humble/setup.bash
PYTHONPATH=src/songling_navigation:$PYTHONPATH python3 -m pytest \
  src/songling_navigation/test/test_offline_nav.py \
  src/songling_navigation/test/test_offline_velocity_gate.py -q
```

自动化验证和实际已完成的集成结果见文末记录。实车场地地图配准、制动距离和真实动态障碍验收需要有车、定位和雷达在线后完成。

完整集成脚本不会随普通 pytest 自动执行；先在独立 domain 启动新的仿真数据目录，并设置 **`sample_map:=true port:=8091`**，再执行：

```bash
PYTHONPATH=src/songling_navigation python3 \
  src/songling_navigation/test/integration_offline_nav.py
# 紧接前一脚本，检查行驶中突发障碍和多航点到达
python3 src/songling_navigation/test/integration_offline_reaction.py
```

第一条脚本要求使用默认示例地图，运行约 1–3 分钟。第二条脚本使用同一服务，起点为前一脚本结束位置。证据分别写入 `/tmp/songling-offline-evidence.json` 和 `/tmp/songling-offline-reaction-evidence.json`。

### 验证记录（2026-10-20）

- `colcon build --packages-select songling_navigation` 构建成功。
- 44 项自动化测试通过，包含区域优先级、未知区约束、安全距离、旋转坐标、Nav2 栅格保守重采样、快照恢复、ZIP 导入导出、网页 API、并发保存/导出、取消优先级、速度门控及无效传感器数据处理。
- WebKit 实际网页验证通过：多边形标注、航点添加、地图保存、掩码预览、终点坐标、导出及导入对话框；JavaScript 模块语法检查通过。
- Nav2 全局/局部代价地图与 KeepoutFilter 激活；禁行区终点被拒绝；初始绕行路径 192 个点全部落在安全栅格内。
- 在路径上放入新的激光障碍后，规划路径与障碍中心最小距离约 1.09 m；完整导航到达 `(26,0)` 周边，全部采样位置处于安全栅格。
- 行驶中突然加入障碍，门控约 0.16 s 后触发并停止模拟小车；移除障碍后，多航点任务继续并到达最后目标 `(30,0)` 周边。该时间仅反映本机仿真与轮询观测，不能作为实车制动指标。
- 取消任务后保持停止；任务执行期间切换地图被拒绝；GPS 整车模式下新旧 Nav2 与高德掩码的条件互斥检查通过。
- 并发仿真：导航中保存 200 个多边形、共 10 万个顶点，同时导出地图，小车仍到达终点；保存期间取消请求约 0.06 s 返回。大项目状态轮询最慢约 0.89 s；这些是本机观测值，不是实时性保证。
- 未进行实车道路验收：预期 GPS 串口 `/dev/ttyACM0` 未检测到，`can0`、`can1` 均为 down；真实地图配准、定位误差、雷达延迟及制动距离仍需现场验证。

### 新园区真实底图验证（2026-10-20）

- 默认场地为旅学路177号新园区，启动不再显示合成示例；示例仅通过 `--sample-map` / `sample_map:=true` 显式选择。
- 新园区坐标、名称、825米覆盖范围和1600×1600彩色影像已核对；默认不预画可行驶区或航点，终点由用户选点。
- 48 项地图、存储和导航保护测试通过，新增彩色底图保存、恢复、导入、导出及未配准底图的实车应用限制。
- 实际浏览器验证真实园区的多边形标注、航点、终点选择、保存、掩码预览与地图包导出。

## 简易触屏界面（独立入口）

原工作台仍通过 `/` 访问。新增的 `/simple` 使用同一服务和同一张当前地图，例如：

- 原工作台：`http://127.0.0.1:8080/`
- 简易 UI：`http://127.0.0.1:8080/simple`

简易 UI 按 188 × 122 mm 横屏设计，以可用视口自适应布局。建议浏览器全屏运行；物理尺寸不能确定像素分辨率，实际文字大小还受面板分辨率和系统缩放影响。

地图上方有“可行驶区域编辑”和“禁行区编辑”两个按钮。选择工具后逐点标记区域边界，再点击“完成多边形”。可绘制多个可行驶区域，圈外与禁行区均禁止自动导航；区域重叠时，禁行区优先。右侧“区域信息”可删除区域、调整边界安全距离和预览通行范围。编辑完成后点击右侧“应用地图”，保存并将最新约束应用到 Nav2。点击“途径点”可在地图上添加任务的中间目标。

右侧两个“导航到”按钮各有“设置”，支持自定义名称、X/Y 和航向，也能引用地图当前选中的终点。快捷点位和当前橙色终点（含朝向）保存在当前浏览器，按地图元数据区分，刷新后恢复；换浏览器或清除浏览器数据后需重新设置。快捷按钮仅请求 `/api/plan`，不会启动导航。“规划路径”和快捷目的地预览统一从当前位置依次经过全部蓝色航点，最后到达橙色终点；“开始导航”发送相同顺序的目标。侧栏显示路线顺序。“仅规划到终点（跳过航点）”用于单终点预览；红底白色粗体“停止”取消任务。航点朝向估算对最后一个航点采用其到终点的出站方向，使长直线末段以直行方向进场；其他航点仍采用相邻点的切线估算。

终点车头朝向可直接在右侧输入角度，或点击“同当前车头”；手动指定后，重新选取终点保留该朝向。点击“航点朝向”可逐点修改 X/Y 坐标和角度、沿用当前车头或按相邻航点走向估算。角度基于 map：0° 向东、90° 向北、±180° 向西、−90° 向南。地图标记显示方向箭头和角度。新航点默认使用上一点至当前点的方向，不再继承终点朝向；已有航点不会自动修改。

S 弯测试先选橙色终点，设置各航点经过时的切线朝向，保存并应用后点击“规划路径”。存在航点时，前端将按列表顺序追加橙色终点，通过 `/api/plan` 的 `poses` 数组调用 Nav2 `ComputePathThroughPoses`；开始导航则将同一列表发送给 `/api/route`（`NavigateThroughPoses`）。没有中间航点时使用单终点接口。加上终点最多 200 个目标；任意点落在禁行栅格时拒绝请求。“按走向估算”也会将橙色终点作为最后一个航点的后继位置。规划失败原因直接显示在右侧。Hunter SE 当前采用前进 Dubins 搜索及 1.9 米最小转弯半径，朝向设置仍需满足转弯空间和障碍约束。

保存时同时保存 `navigation_goal`（X/Y/朝向）。刷新优先载入新地图快照的终点；同一快照内的浏览器临时终点仍可保留。Humble Smac 初始化时将转弯半径按代价地图分辨率换算成栅格单位，地图后续改变分辨率时需要重新计算。工作台监听实际全局代价地图的分辨率，在空闲时通过异步参数服务重发当前半径、解析连接长度及角度分箱数，参数数值不变；同步成功前拒绝规划和导航，避免沿用启动时 0.1 m 栅格对应的转弯尺度。参考 [Humble Smac 初始化与动态参数回调](https://api.nav2.org/nav2-humble/html/smac__planner__hybrid_8cpp_source.html)。

底部状态栏显示 CAN 反馈、遥控档位、定位和运动启用状态。CAN 状态依据 `/hunter_status` 的有效反馈判断，不代表直接读取网口配置；遥控档位依据新鲜底盘反馈中的 `control_mode == 1` 显示为“自动 / CAN”。反馈超过 1 秒时显示未知，仿真单独标注。底盘故障码及详细阻止原因可在任务详情中查看。仅打开网页不会改变服务的运动启用参数。
