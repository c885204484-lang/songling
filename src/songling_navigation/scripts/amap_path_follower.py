#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
import math
import requests

from sensor_msgs.msg import NavSatFix
from tf2_ros import Buffer, TransformListener
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path
from robot_localization.srv import FromLL
from nav2_msgs.action import FollowPath
from action_msgs.msg import GoalStatus

# ==========================================
# 坐标系转换工具：GCJ-02 (高德) <-> WGS-84 (RTK)
# ==========================================
x_pi = 3.14159265358979324 * 3000.0 / 180.0
pi = 3.1415926535897932384626
a = 6378245.0  
ee = 0.00669342162296594323  

def out_of_china(lng, lat):
    return not (lng > 73.66 and lng < 135.05 and lat > 3.86 and lat < 53.55)

def _transformlat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * pi) + 20.0 * math.sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * pi) + 40.0 * math.sin(lat / 3.0 * pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * pi) + 320 * math.sin(lat * pi / 30.0)) * 2.0 / 3.0
    return ret

def _transformlng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(math.fabs(lng))
    ret += (20.0 * math.sin(6.0 * lng * pi) + 20.0 * math.sin(2.0 * lng * pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * pi) + 40.0 * math.sin(lng / 3.0 * pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * pi) + 300.0 * math.sin(lng / 30.0 * pi)) * 2.0 / 3.0
    return ret

def gcj02_to_wgs84(lng, lat):
    if out_of_china(lng, lat): return lng, lat
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * pi)
    mglat = lat + dlat
    mglng = lng + dlng
    return [lng * 2 - mglng, lat * 2 - mglat]

def wgs84_to_gcj02(lng, lat):
    if out_of_china(lng, lat): return lng, lat
    dlat = _transformlat(lng - 105.0, lat - 35.0)
    dlng = _transformlng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * pi)
    mglat = lat + dlat
    mglng = lng + dlng
    return [mglng, mglat]

# ==========================================
# 核心 ROS2 节点
# ==========================================
class AmapPathFollower(Node):
    def __init__(self, end_lon, end_lat):
        super().__init__('amap_path_follower')
        self.cb_group = ReentrantCallbackGroup()
        self.from_ll_client = self.create_client(FromLL, '/fromLL', callback_group=self.cb_group)
        self.follow_path_client = ActionClient(self, FollowPath, 'follow_path', callback_group=self.cb_group)

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.path_pub = self.create_publisher(Path, '/amap_plan', 10)
        
        self.end_lon = end_lon
        self.end_lat = end_lat
        
        self.nav_triggered = False  # 🛡️ 修复 Bug 1：防止并发多开
        self.raw_amap_map_pts = []
        self.current_wp_idx = 0
        self.progress_timer = None

# 🌟 新增：GPS 稳定计数器
        self.gps_stable_count = 0
        
        while not self.from_ll_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('⏳ 等待 /fromLL 坐标转换服务上线...')
            
        self.gps_sub = self.create_subscription(
            NavSatFix, '/gps/fix', self.gps_callback, 10, callback_group=self.cb_group)
        self.get_logger().info('📡 基础服务已就绪！正在等待接收 RTK 定位信号...')

    def gps_callback(self, msg):
        # 严格拦截多余的触发
        if self.nav_triggered or msg.latitude == 0.0:
            return

# 🌟 核心修复：不要在第一帧 GPS 就立刻规划，等待 EKF 航向角收敛
        # 假设 GPS 频率是 10Hz，等待 30 帧大约就是 3 秒钟
        self.gps_stable_count += 1
        if self.gps_stable_count < 30:
            if self.gps_stable_count % 10 == 0:
                self.get_logger().info(f'⏳ 正在等待 EKF 航向角收敛稳定 ({self.gps_stable_count}/30)...')
            return
        
        self.nav_triggered = True 
            
        self.get_logger().info(f'✅ 成功捕获起点 (WGS-84): [{msg.longitude:.6f}, {msg.latitude:.6f}]')
        
        gcj_lon, gcj_lat = wgs84_to_gcj02(msg.longitude, msg.latitude)
        self.start_lon = gcj_lon
        self.start_lat = gcj_lat
        
        # 立即启动导航主线程
        self.timer = self.create_timer(0.1, self.execute_navigation, callback_group=self.cb_group)

    async def execute_navigation(self):
        self.timer.cancel()
        
        wgs84_waypoints = self.fetch_amap_route()
        if not wgs84_waypoints: return
        
        self.get_logger().info(f'📍 [阶段 2] 开始批量转换 {len(wgs84_waypoints)} 个坐标系...')
        map_xy_pts = []
        for lon, lat in wgs84_waypoints:
            req = FromLL.Request()
            req.ll_point.longitude, req.ll_point.latitude = lon, lat
            req.ll_point.altitude = 0.0
            response = await self.from_ll_client.call_async(req)
            map_xy_pts.append((response.map_point.x, response.map_point.y))

        self.raw_amap_map_pts = list(map_xy_pts)

        # ==========================================
        # 🌟 修复 Bug 2：重写智能裁剪与长牵引桥
        # ==========================================
        current_x, current_y, current_yaw = 0.0, 0.0, 0.0
        try:
            t = self.tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
            current_x = t.transform.translation.x
            current_y = t.transform.translation.y
            q = t.transform.rotation
            current_yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            
            valid_idx = 0
            for i, (px, py) in enumerate(map_xy_pts):
                angle_diff = (math.atan2(py - current_y, px - current_x) - current_yaw + math.pi) % (2 * math.pi) - math.pi
                if math.hypot(px - current_x, py - current_y) > 2.0 and abs(angle_diff) < (math.pi / 2.5):
                    valid_idx = i
                    break
            
            map_xy_pts = map_xy_pts[valid_idx:]
            self.get_logger().info(f'✂️ 裁剪掉前 {valid_idx} 个死角或后方航点。')

            # 强势植入：生成一段绝对顺应当前车头的 1.5 米实体直道桥
            bridge_pts = []
            for i in range(5):
                bx = current_x + (i * 0.3) * math.cos(current_yaw)
                by = current_y + (i * 0.3) * math.sin(current_yaw)
                bridge_pts.append((bx, by))
                
            map_xy_pts = bridge_pts + map_xy_pts  # 缝合路线
            self.get_logger().info(f'🌉 1.5米前向牵引直道铺设完成，初始偏差角强制归零！')
        except Exception as e:
            self.get_logger().warn(f'⚠️ TF 获取失败: {e}')
            
        path_msg = self.densify_and_build_path(map_xy_pts, step=0.3)
        self.get_logger().info(f'🎯 [阶段 3] 轨迹加密平滑完成，共 {len(path_msg.poses)} 个点。')

        # 仅打印前 10 个和关键相对坐标，防止刷屏
        self.get_logger().info('====== 轨迹点相对坐标 (base_link) 审计 [采样前10点] ======')
        for i, pose in enumerate(path_msg.poses[:10]):
            gx, gy = pose.pose.position.x, pose.pose.position.y
            dx, dy = gx - current_x, gy - current_y
            rel_x = dx * math.cos(current_yaw) + dy * math.sin(current_yaw)
            rel_y = -dx * math.sin(current_yaw) + dy * math.cos(current_yaw)
            self.get_logger().info(f'航点 [{i:03d}] | 相对车身: 前后X={rel_x:.2f}m, 左右Y={rel_y:.2f}m')
        self.get_logger().info('====================================================')
        
        self.path_pub.publish(path_msg)
        self.progress_timer = self.create_timer(0.5, self.check_navigation_progress, callback_group=self.cb_group)

        await self.send_follow_path_goal(path_msg)

    def fetch_amap_route(self):
        AMAP_KEY = "ab24c47a195f096bd52f910f9ed3a14e"
        url = f"https://restapi.amap.com/v5/direction/bicycling?origin={self.start_lon},{self.start_lat}&destination={self.end_lon},{self.end_lat}&key={AMAP_KEY}&show_fields=polyline"
        
        try:
            response = requests.get(url, timeout=5.0).json()
            if response.get('status') == '1' and response['route'].get('paths'):
                wgs84_pts = []
                for step in response['route']['paths'][0].get('steps', []):
                    for pt in step.get('polyline', '').split(';'):
                        if ',' in pt:
                            lon, lat = map(float, pt.split(','))
                            wgs_lon, wgs_lat = gcj02_to_wgs84(lon, lat)
                            wgs84_pts.append((wgs_lon, wgs_lat))
                self.get_logger().info(f'🌐 [阶段 1] 高德规划成功！提取航点 {len(wgs84_pts)} 个。')
                return wgs84_pts
            return None
        except Exception as e:
            self.get_logger().error(f"❌ 网络请求异常: {e}")
            return None

    def densify_and_build_path(self, xy_pts, step=0.3):
        # 🌟 修复 Bug 2：绝对必须先插值加密，再平滑，否则会抹平长直角！
        # 1. 线性加密
        dense_pts = []
        for i in range(len(xy_pts) - 1):
            x1, y1 = xy_pts[i]
            x2, y2 = xy_pts[i+1]
            dist = math.hypot(x2 - x1, y2 - y1)
            dense_pts.append((x1, y1))
            if dist > step:
                num = int(dist / step)
                for j in range(1, num):
                    dense_pts.append((x1 + (x2-x1)*j/num, y1 + (y2-y1)*j/num))
        dense_pts.append(xy_pts[-1])

        # 2. 对高密度轨迹进行迭代滑动平滑 (生成贝塞尔般柔和的切入曲线)
        smooth_iters = 8
        for _ in range(smooth_iters):
            if len(dense_pts) < 3: break
            temp_pts = [dense_pts[0]]
            for i in range(1, len(dense_pts) - 1):
                px, py = dense_pts[i-1]
                cx, cy = dense_pts[i]
                nx, ny = dense_pts[i+1]
                temp_pts.append(((px + 2*cx + nx)/4.0, (py + 2*cy + ny)/4.0))
            temp_pts.append(dense_pts[-1])
            dense_pts = temp_pts
        
        path_msg = Path()
        path_msg.header.frame_id = 'map'
        path_msg.header.stamp = self.get_clock().now().to_msg()
        
        for i in range(len(dense_pts)):
            x, y = dense_pts[i]
            pose = PoseStamped()
            pose.header = path_msg.header
            pose.pose.position.x = float(x)
            pose.pose.position.y = float(y)
            pose.pose.position.z = 0.0

            # 航向角切线赋值
            if i < len(dense_pts) - 1:
                yaw = math.atan2(dense_pts[i+1][1] - y, dense_pts[i+1][0] - x)
            else:
                yaw = math.atan2(y - dense_pts[i-1][1], x - dense_pts[i-1][0]) if i > 0 else 0.0

            pose.pose.orientation.z = math.sin(yaw / 2.0)
            pose.pose.orientation.w = math.cos(yaw / 2.0)
            path_msg.poses.append(pose)
            
        return path_msg

    def check_navigation_progress(self):
        if not self.raw_amap_map_pts or self.current_wp_idx >= len(self.raw_amap_map_pts): return
        try:
            t = self.tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
            curr_x, curr_y = t.transform.translation.x, t.transform.translation.y
            while self.current_wp_idx < len(self.raw_amap_map_pts):
                wx, wy = self.raw_amap_map_pts[self.current_wp_idx]
                if math.hypot(wx - curr_x, wy - curr_y) < 1.2:
                    self.get_logger().info(f'🏁 小车已到达/通过第 [{self.current_wp_idx}] 航段')
                    self.current_wp_idx += 1
                else:
                    break
        except Exception: pass

    async def send_follow_path_goal(self, path_msg):
        self.get_logger().info('🔌 连接 Nav2 FollowPath 动作服务器...')
        self.follow_path_client.wait_for_server()
        
        goal_msg = FollowPath.Goal()
        goal_msg.path = path_msg
        goal_msg.controller_id = 'FollowPath' 
        
        self.get_logger().info('🚀 路线已下发！起飞...')
        goal_handle = await self.follow_path_client.send_goal_async(goal_msg)
        
        if not goal_handle.accepted:
            self.get_logger().error('⛔ 目标被拒绝！')
            return
            
        result = await goal_handle.get_result_async()
        if self.progress_timer: self.progress_timer.cancel()
            
        if result.status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('🏁 完美到达！')
        else:
            self.get_logger().error(f'⚠️ 中断，状态码: {result.status}')
        
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    END_LON, END_LAT = "120.298613", "30.251176"
    node = AmapPathFollower(END_LON, END_LAT)
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()

if __name__ == '__main__':
    main()