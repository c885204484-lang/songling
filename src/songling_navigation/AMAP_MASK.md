# 高德语义掩码地图（Nav2 KeepoutFilter）

用高德静态图的语义信息生成一张“禁行掩码”，接入 Nav2，让规划器自动避开
水域、草坪/绿化带、田径场和外侧主干道；校内的白色步道**保留可通行**。

## 结论先说

- 高德静态图（GCJ-02）+ `robot_localization` 的 `/fromLL`（WGS-84）在运行时
  拟合成 `map` 系下的仿射，掩码不需要手工对齐。
- 图心默认取启动时 `/gps/fix` 的 WGS-84 位置并转成 GCJ，所以换场地/换校区
  不用改中心点；`center_mode: fixed` 保留给离线预览和测试。
- 掩码以 `nav_msgs/OccupancyGrid` 发布：`100=禁行`、`0=可通行`、`-1=未知`。
- 同时发布 `nav2_msgs/CostmapFilterInfo`（`type=0`，keepout），Nav2 的
  `KeepoutFilter` 直接消费，不需要额外的 mask map_server。
- 已做过的验证：离线分割、静态锚点、假 `/fromLL` 服务、Nav2 global_costmap
  集成（filter 正常激活，测试窗口内标记出 360,899 个致命栅格）。
- **未做**：实车 RTK 跑车验证（当前没有 GPS/底盘在线）。

## 启动

```bash
cd ~/songling/songling_ws
source /opt/ros/humble/setup.bash
colcon build --packages-select songling_navigation
source install/setup.bash

# 正常整车启动（掩码节点会自动拉起）
ros2 launch songling_navigation gps_navigation.launch.py

# 临时关闭掩码（导航其余部分不受影响）
ros2 launch songling_navigation gps_navigation.launch.py use_amap_mask:=False
```

掩码节点会等待 `/fromLL` 和 `/gps/fix`（默认 5 个有效 fix），所以
**navsat_transform 和 RTK 必须先就绪**。节点启动后日志里会出现：

```
using live GPS centre WGS-84 (30.254400, 120.294100) -> Amap GCJ (30.251980, 120.298583)
Amap image 2048x2048 @ 0.516 m/px, class pixels={...}
geo/map affine fitted from 25 controls, max residual 0.00x m
mask ready (fromLL): 1200x1200 @ 0.5 m, origin=(-300.0, -300.0), keepout=... cells
mask snapshot saved to .../PCD/amap_mask
```

RViz 里添加 `Map`，topic 选 `/amap_keepout_mask`，即可看到禁行区。
`100` 显示为占用，`0` 为自由。

### 输出文件（`PCD/amap_mask/`）

| 文件 | 用途 |
| --- | --- |
| `amap_keepout_mask.pgm/.yaml` | Nav2 标准掩码（0=禁行，254=自由，205=未知，PGM 顶行对应 map 最大 y） |
| `amap_keepout_map_preview.png` | map 系下的彩色预览（蓝=水，绿=绿化，橙=田径场，品红=主干道） |
| `amap_keepout_segmentation.png` | 高德原图上的分割叠加，换区域/换季节先看这张 |
| `amap_keepout_meta.json` | 中心点、仿射系数、残差、网格 origin/resolution、类别像素数 |

## 离线预览（不启动 ROS、不连车）

```bash
cd ~/songling/songling_ws/src/songling_navigation
python3 -m songling_navigation.amap_keepout \
  --key <高德Web服务Key> \
  --out-dir /tmp/amap_keepout
```

只看分割叠加图就够了。若还想看 map 系网格（**仅测试**，需要手工锚点）：

```bash
python3 -m songling_navigation.amap_keepout \
  --key <KEY> --out-dir /tmp/amap_keepout_map \
  --roi-radius 300 --resolution 0.5 \
  --anchor-lat 30.256819505176207 --anchor-lon 120.28961741903687 \
  --anchor-x 0 --anchor-y 0 --anchor-yaw-deg 0
```

这里的 `--center-lat/lon` 是 **GCJ-02**，`--anchor-lat/lon` 是 **WGS-84**，
两者不要混用。上面的锚点只是把校区中心当成 map (0,0) 的测试值，实车不需要。

单独跑 ROS 节点做静态锚点冒烟测试（不依赖 `/fromLL`）：

```bash
ros2 run songling_navigation amap_keepout_mask.py --ros-args \
  -p amap_key:=<KEY> -p use_static_anchor:=true \
  -p anchor_lat:=30.256819505176207 -p anchor_lon:=120.28961741903687 \
  -p output_dir:=/tmp/amap_ros
```

## 工作原理

1. 图心：默认取启动时 `/gps/fix` 的 WGS-84 位置（RTK 输出），用
   `wgs84_to_gcj02` 转成高德 GCJ-02 再取图；`center_mode: fixed` 时用
   `center_lat_gcj/lon_gcj`（离线预览/测试）。高德静态图 `zoom=17`（上限），
   `size=1024`、`scale=2`，返回 2048×2048，地面分辨率约 **0.516 m/px**。
2. 颜色分割（阈值针对高德普通样式调过）：
   - 水：浅蓝（`B-R>45, B-G>20, B>200, R>120`）
   - 绿化：草坪（`G-R>18, G-B>20, G>150`）
   - 田径场：粉红跑道（`R>215, R-G>25, R-B>30`）
   - 主干道：黄色路缘（闭运算 14m 填实路面）
   - 校内白色步道**不分类**，所以不会被封死。
3. 配准：以图像中心为基准生成 5×5 个控制点（±300m），逐个调用 `/fromLL`，
   最小二乘拟合 `WGS84 lon/lat -> map x/y` 仿射。残差超过
   `max_affine_residual_m`（默认 3m）就拒绝发布并重试，避免拿错坐标硬发。
4. 反算栅格：对 map 系每个 0.5m 栅格中心反算经纬度、再反算源图像素，
   最近邻采样得到 `100/0`。`roi_radius=300m` 覆盖整个校区。
5. 发布：`/costmap_filter_info` + `/amap_keepout_mask` 都是
   `transient_local`，默认**只发一次**；晚启动的 filter 也能拿到历史样本
   （已用 Nav2 实测）。需要心跳时把 `publish_period_s` 设为 30。
6. Nav2 侧：`config/2026-08-06-1.yaml` 的 `global_costmap` 增加

   ```yaml
   filters: ["amap_keepout_filter"]
   amap_keepout_filter:
     plugin: "nav2_costmap_2d::KeepoutFilter"
     filter_info_topic: "/costmap_filter_info"
   ```

   filter 在 obstacle/inflation 之后执行，把掩码 100 的栅格置为致命。

## 调参（`config/amap_keepout_mask.yaml`）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `center_mode` | `gps` | `gps`=用启动时 `/gps/fix` 的 WGS-84→GCJ 图心；`fixed`=用下面的固定中心 |
| `gps_topic` | `/gps/fix` | 用于选图心的 RTK 话题（必须是 WGS-84） |
| `gps_min_fixes` | 5 | 等够多少个有效 fix 再取图心 |
| `center_lat_gcj/lon_gcj` | 30.2544 / 120.2941 | **仅 fixed 模式**使用；默认是体育职院 GCJ 中心 |
| `zoom` | 17 | 高德静态图上限；改大不会更清晰，反而会让比例错 |
| `roi_radius` | 300.0 | map 系覆盖半径；小了会切掉湖/田径场 |
| `resolution` | 0.5 | 源图原生约 0.52m/px，0.5 足够 |
| `classes` | 水/绿化/田径场/主干道 | 去掉 `major_road` 可放行外侧大路（不建议） |
| `road_close_m` | 14.0 | 黄色路缘闭运算核；路面没填满就加大 |
| `dilate_m` | 0.3 | 掩码外扩，给车宽留余量 |
| `water_min_area_m2` 等 | 100/20/50/50 | 过滤掉图标、路名等小色块 |
| `publish_period_s` | 0.0 | 0=只发一次（transient local）；30=每 30s 心跳 |
| `max_affine_residual_m` | 3.0 | `/fromLL` 配准残差门限 |

常见排查：

- **filter 没反应**：`ros2 node list | grep costmap` 找到 costmap 节点，
  `ros2 param get <节点> filters` 应包含 `amap_keepout_filter`；
  日志里应有 `KeepoutFilter: Received filter info/mask`。
- **掩码整体偏了**：看日志里的
  `live GPS centre WGS-84 (...) -> Amap GCJ (...)` 是否符合预期。若 `/gps/fix`
  实际输出的是 GCJ 而不是 WGS-84，图心会整体偏约 500m；RTK 驱动应是 WGS-84。
  再确认 `/fromLL` 的 datum 没变：`navsat_transform` 是
  `wait_for_datum: false`，map (0,0) 就是它启动后收到的**第一个 GPS fix**；
  如果车换地方起步或重启过 navsat，掩码节点要跟着重启。
- **湖/草坪没被标**：打开 `amap_keepout_segmentation.png` 看颜色是否覆盖；
  高德换样式或季节变化时阈值可能要微调。
- **校内路被标了**：那是把白色步道误判成了道路；检查 `classes` 是否只开了
  `major_road`，以及 `road_close_m` 是否过大（把邻近白路也闭运算连上了）。

## 注意事项 / 下一步

- 掩码在启动时按当时的 GPS 图心构建一次。车换到离起点超过 `roi_radius`
  （默认 300m）的新场地，重启节点（或加大 `roi_radius`）；`/fromLL` 的 datum
  变了也要重启。启动时最好把车停在作业场地内。
- 本节点**自己发布** `/costmap_filter_info`。不要再把
  `costmap_filter_info_server` 配到同一个 topic，否则 filter 会反复重订阅。
- 当前只做 keepout。限速区（`SpeedFilter`，mask 值 1–99）还没做，下一步可以在
  同一张 mask 上给路口/人流区编码速度。
- 手动画临时禁行区（施工、活动）还没做 UI；后续可加 GeoJSON 多边形输入或
  RViz 画多边形工具。
- 高德静态图有免费配额；节点默认把图缓存在 `~/.cache/songling/amap_mask`，
  TTL 24h，避免反复消耗配额。
- 高德分割是启发式，换场地/换图样式后务必先看 `amap_keepout_segmentation.png`
  和 map 预览，再实车跑。

## 验证记录（2026-10-20）

- 离线（fixed，体育职院图心）：2048×2048、0.516 m/px；类像素 water 153,073 /
  green 77,911 / track 41,525 / major_road 246,289；1200×1200@0.5 网格
  禁行 223,770 格。
- GPS 自适应（假 `/gps/fix` = WGS-84 30.254400,120.294100）：图心自动转成
  GCJ 30.251980,120.298583，取到科技园图；类像素 water 246,065 / green
  148,901 / track 11,915 / major_road 119,711；1200×1200@0.5 网格禁行
  123,034 格。
- 假 `/fromLL`：25 个控制点，最大残差约 `1e-8 m`，输出与静态锚点一致。
- Nav2 集成：`global_costmap` 生命周期 configure/activate 成功；
  `KeepoutFilter: Received filter info/mask`；测试窗口 1200×1200@0.25，
  致命栅格 360,899。
- 未验证：实车 RTK 起步、真实 `/fromLL` datum 下的现场对齐（需上车跑一次，
  在 RViz 里把 `/amap_keepout_mask` 和 `/scan`/地图叠在一起看湖岸是否吻合）。
