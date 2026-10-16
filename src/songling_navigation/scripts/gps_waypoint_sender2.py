#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
import math  # 🌟 新增：用于数学计算
from rclpy.duration import Duration
from geographic_msgs.msg import GeoPoint
from robot_localization.srv import FromLL
from nav2_msgs.action import NavigateToPose
from action_msgs.msg import GoalStatus

# 🌟 新增：用于查询小车当前位置的 TF 库
from tf2_ros import Buffer, TransformListener 

class GpsWaypointSender(Node):
    def __init__(self, waypoints):
        super().__init__('gps_waypoint_sender')
        
        self.from_ll_client = self.create_client(FromLL, '/fromLL')
        self.nav_to_pose_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        
        # 🌟 初始化 TF 监听器，用于获取小车实时坐标
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # 任务队列初始化
        self.waypoints = waypoints
        self.current_wp_index = 0
        self.total_wps = len(waypoints)
        
        # 用于控制反馈日志的打印频率，防止刷屏
        self.feedback_print_counter = 0 
        
        while not self.from_ll_client.wait_for_service(timeout_sec=1.0):
            self.get_logger().info('⏳ 等待 /fromLL 坐标转换服务上线...')
            
        self.get_logger().info(f'✅ GPS 导航节点已初始化完成！共收到 {self.total_wps} 个目标点。')

    def start_navigation(self):
        """控制任务进度的核心发车函数"""
        if self.current_wp_index < self.total_wps:
            target_lat = self.waypoints[self.current_wp_index]['lat']
            target_lon = self.waypoints[self.current_wp_index]['lon']
            
            self.get_logger().info(f'\n=============================================')
            self.get_logger().info(f'🚀 开始执行任务：前往第 {self.current_wp_index + 1}/{self.total_wps} 个点')
            self.get_logger().info(f'=============================================')
            
            self.send_gps_goal(target_lat, target_lon)
        else:
            self.get_logger().info('🏆 恭喜！所有 GPS 目标点均已圆满完成！')
            rclpy.shutdown()

    def send_gps_goal(self, target_lat, target_lon):
        self.get_logger().info(f'📍 [阶段 1/4] 坐标转换请求: [{target_lat}, {target_lon}]')
        
        req = FromLL.Request()
        req.ll_point.latitude = target_lat
        req.ll_point.longitude = target_lon
        req.ll_point.altitude = 0.0  
        
        future = self.from_ll_client.call_async(req)
        future.add_done_callback(self.from_ll_response_callback)

    def from_ll_response_callback(self, future):
        try:
            response = future.result()
            map_point = response.map_point
            self.get_logger().info(f'🎯 [阶段 2/4] 坐标转换成功: X={map_point.x:.2f}m, Y={map_point.y:.2f}m')
            
            self._send_nav2_goal(map_point.x, map_point.y)
            
        except Exception as e:
            self.get_logger().error(f'❌ 坐标转换失败: {e}')
            rclpy.shutdown()

    def _send_nav2_goal(self, x, y):
        self.get_logger().info('🔌 [阶段 3/4] 正在连接 Nav2 大脑...')
        self.nav_to_pose_client.wait_for_server()
        
        goal_msg = NavigateToPose.Goal()
        goal_msg.pose.header.frame_id = 'map'
        goal_msg.pose.header.stamp = self.get_clock().now().to_msg()
        
        goal_msg.pose.pose.position.x = x
        goal_msg.pose.pose.position.y = y
        goal_msg.pose.pose.position.z = 0.0
        
        # # ==========================================
        # # 🌟 核心修改：强制死等 map 出现，绝不抢跑！
        # # ==========================================
        # self.get_logger().info('⏳ 正在等待 map -> base_link 坐标系建立...')
        # try:
        #     # 动态等待 TF 树连通，最多等 10 秒
        #     trans = self.tf_buffer.lookup_transform(
        #         'map', 
        #         'base_link', 
        #         rclpy.time.Time(),
        #         timeout=rclpy.duration.Duration(seconds=10.0)
        #     )
        #     current_x = trans.transform.translation.x
        #     current_y = trans.transform.translation.y
            
        #     # 计算顺滑朝向
        #     yaw = math.atan2(y - current_y, x - current_x)
        #     self.get_logger().info(f'🧭 动态计算目标朝向: {math.degrees(yaw):.1f}°')
            
        #     goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
        #     goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        # except Exception as e:
        #     self.get_logger().error(f'❌ 致命错误：等待 10 秒后仍未找到 map 坐标系！原因: {e}')
        #     return
        # # ==========================================

        # ==========================================
        # 🌟 核心修复：动态计算顺滑的车头朝向
        # ==========================================
        try:
            # 删掉你加的等待 10 秒的代码，直接用瞬间查询！
            # 获取当前小车在 map 坐标系下的位置
            t = self.tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
            current_x = t.transform.translation.x
            current_y = t.transform.translation.y
            
            # 计算两点连线的夹角（弧度）
            yaw = math.atan2(y - current_y, x - current_x)
            self.get_logger().info(f'🧭 动态计算目标朝向: {math.degrees(yaw):.1f}°')
            
            # 偏航角(yaw)转四元数
            goal_msg.pose.pose.orientation.x = 0.0
            goal_msg.pose.pose.orientation.y = 0.0
            goal_msg.pose.pose.orientation.z = math.sin(yaw / 2.0)
            goal_msg.pose.pose.orientation.w = math.cos(yaw / 2.0)
        except Exception as e:
            self.get_logger().warn(f'⚠️ 无法获取 TF 坐标计算角度，采用默认朝向。原因: {e}')
            goal_msg.pose.pose.orientation.w = 1.0
        # ==========================================
        self.get_logger().info('🚀 [阶段 4/4] 目标已发送，等待 Nav2 规划...')
        
        self.feedback_print_counter = 0 
        
        send_goal_future = self.nav_to_pose_client.send_goal_async(
            goal_msg, 
            feedback_callback=self.feedback_callback
        )
        send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('⛔ [严重错误] 目标被 Nav2 拒绝！原因可能是目标在障碍物内或无法规划路线。')
            rclpy.shutdown()
            return

        self.get_logger().info('✅ 目标已被 Nav2 接受！全局路径规划成功，开始下发底盘控制指令...')
        
        get_result_future = goal_handle.get_result_async()
        get_result_future.add_done_callback(self.get_result_callback)

    def feedback_callback(self, feedback_msg):
        feedback = feedback_msg.feedback
        self.feedback_print_counter += 1
        
        if self.feedback_print_counter % 10 == 0:
            dist = feedback.distance_remaining
            time_left = feedback.estimated_time_remaining.sec
            recoveries = feedback.number_of_recoveries
            
            log_str = f'🏃 [点 {self.current_wp_index + 1}] 距目标: {dist:.2f}米 | 预计剩余: {time_left}秒'
            if recoveries > 0:
                log_str += f' | ⚠️ 触发恢复行为: {recoveries}次'
                
            self.get_logger().info(log_str)

    def get_result_callback(self, future):
        status = future.result().status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f'🏁 完美！小车已成功到达第 {self.current_wp_index + 1} 个目标点！')
            
            self.current_wp_index += 1
            self.start_navigation()
            
        elif status == GoalStatus.STATUS_CANCELED:
            self.get_logger().warn('🛑 导航被外部强行取消！')
            rclpy.shutdown()
        elif status == GoalStatus.STATUS_ABORTED:
            self.get_logger().error('💥 [导航崩溃] Nav2 强行终止了任务！(可能卡死了)')
            rclpy.shutdown()
        else:
            self.get_logger().error(f'⚠️ 未知异常中止，状态码: {status}')
            rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    
# 十字路口
# latitude: 30.25438822816667     longitude: 120.29409356266666
# 307 实验室门口
# latitude: 30.254458796833333   longitude: 120.29339422566666
# A2 大门口
# latitude: 30.254961930833332   longitude: 120.29411244066667
# A8 湖边
# latitude: 30.254348924333332   longitude: 120.29465838716666
# 南门 路口
# latitude: 30.254301978166666   longitude: 120.29436407316666
# 南门
# latitude: 30.253612568333335   longitude: 120.29432326116667
    
    target_waypoints = [
        # {'lat': 30.254961930833332, 'lon': 120.29411244066667},  # A2 大门口

        # {'lat': 30.25438822816667, 'lon': 120.29409356266666},  # 十字路口 
        
        # {'lat': 30.254348924333332, 'lon': 120.29465838716666},  # A8 湖边
        
        # {'lat': 30.254405673833332, 'lon': 120.29409430816666},  # 十字路口 
        
        {'lat': 30.254458796833333, 'lon': 120.29339422566666},  # 307 实验室门口  

        # {'lat': 30.254301978166666, 'lon': 120.29436407316666},  # 南门路口 
        
        # {'lat': 30.253612568333335, 'lon': 120.29432326116667},  # 南门

        # {'lat': 30.254301978166666, 'lon': 120.29436407316666},  # 南门路口 

        # {'lat': 30.25438822816667, 'lon': 120.29409356266666},  # 十字路口 

        # {'lat': 30.254961930833332, 'lon': 120.29411244066667},  # A2 大门口
    ]
    
    node = GpsWaypointSender(target_waypoints)

    # ==========================================
    # 🌟 核心修改：发车前预热，吸入 TF 缓存
    # ==========================================
    node.get_logger().info('⏳ 正在预热 TF 坐标树，请稍候 3 秒...')
    import time
    start_time = time.time()
    # 循环执行 3 秒的 spin_once，让 tf_listener 充分接收底层发来的坐标数据
    while time.time() - start_time < 3.0:
        rclpy.spin_once(node, timeout_sec=0.1)
    # ==========================================
    
    node.start_navigation()
    
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('🛑 收到键盘中断，程序退出。')
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()

if __name__ == '__main__':
    main()