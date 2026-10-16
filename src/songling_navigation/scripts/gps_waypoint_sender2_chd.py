#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
import math  
import time  

from geographic_msgs.msg import GeoPoint
from robot_localization.srv import FromLL
from nav2_msgs.action import NavigateToPose, BackUp  
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Point  # 🌟 核心修复：必须导入 Point 消息类型

# 用于查询小车当前位置的 TF 库
from tf2_ros import Buffer, TransformListener 

class GpsWaypointSender(Node):
    def __init__(self, waypoints):
        super().__init__('gps_waypoint_sender')
        
        # 客户端初始化
        self.from_ll_client = self.create_client(FromLL, '/fromLL')
        self.nav_to_pose_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.backup_client = ActionClient(self, BackUp, 'backup')  
        
        # 初始化 TF 监听器，用于获取小车实时坐标
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # 任务队列初始化
        self.waypoints = waypoints
        self.current_wp_index = 0
        self.total_wps = len(waypoints)
        
        # 卡死监测专用的状态变量
        self.last_dist = 999.0
        self.stuck_time = 0.0
        self.last_feedback_time = time.time()
        self.is_healing = False
        self.current_goal_handle = None
        
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
        
        # ==========================================
        # 动态计算顺滑的车头朝向
        # ==========================================
        try:
            # 获取当前小车在 map 坐标系下的位置
            t = self.tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
            current_x = t.transform.translation.x
            current_y = t.transform.translation.y
            
            # 计算两点连线的夹角（弧度）
            yaw = math.atan2(y - current_y, x - current_x)
            self.get_logger().info(f'🧭 动态计算目标朝向: {math.degrees(yaw):.1f}° (小车将沿直线停靠)')
            
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

        self.current_goal_handle = goal_handle  
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

        # ==========================================
        # 卡死检测逻辑 (与原打印逻辑互不干扰)
        # ==========================================
        if self.is_healing:
            return  

        current_dist = feedback.distance_remaining
        now = time.time()
        
        # 如果 5秒内距离变化小于 0.05 米 (5厘米)，视为卡死
        if abs(self.last_dist - current_dist) < 0.20:
            self.stuck_time += (now - self.last_feedback_time)
        else:
            self.stuck_time = 0.0
            
        self.last_dist = current_dist
        self.last_feedback_time = now
        
        # 超过 5 秒未移动，触发强制倒车
        if self.stuck_time > 15.0:
            self.get_logger().warn('⚠️ 检测到小车长时间未移动 (疑为掉头死锁)，触发倒车自愈！')
            self.trigger_self_healing()
            self.stuck_time = 0.0

    # ==========================================
    # 自愈执行系列函数
    # ==========================================
    def trigger_self_healing(self):
        self.is_healing = True
        
        # 1. 取消当前因为卡死而无解的导航任务
        if self.current_goal_handle:
            self.current_goal_handle.cancel_goal_async()
            
        # 2. 🌟 核心修复：构造符合格式的 Point 消息子项
        backup_goal = BackUp.Goal()
        backup_goal.target = Point()   # 实例化一个 Point 对象
        backup_goal.target.x = 1.0     # 强制后退距离定义在 x 轴上（单位：米）
        backup_goal.target.y = 0.0
        backup_goal.target.z = 0.0
        backup_goal.speed = 0.15       # 倒车速度 0.15 m/s
        
        self.get_logger().info('🔌 正在连接倒车行为服务器...')
        self.backup_client.wait_for_server()
        
        send_backup_future = self.backup_client.send_goal_async(backup_goal)
        send_backup_future.add_done_callback(self.backup_response_callback)

    def backup_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('⛔ 自愈动作被拒绝！')
            self.is_healing = False
            return
            
        goal_handle.get_result_async().add_done_callback(self.backup_result_callback)

    def backup_result_callback(self, future):
        self.get_logger().info('✅ 倒车自愈完成，打破死锁位置！正在重新下发目标点...')
        self.is_healing = False
        self.last_dist = 999.0
        self.stuck_time = 0.0
        
        # 重新调用导航函数，它会自动向现在的 current_wp_index 下发同样的坐标
        self.start_navigation()
    # ==========================================

    def get_result_callback(self, future):
        status = future.result().status
        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info(f'🏁 完美！小车已成功到达第 {self.current_wp_index + 1} 个目标点！')
            
            self.current_wp_index += 1
            self.start_navigation()
            
        elif status == GoalStatus.STATUS_CANCELED:
            if getattr(self, 'is_healing', False):
                self.get_logger().info('🔄 原导航进程已暂停，交由自愈模块接管...')
            else:
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
    
    target_waypoints = [
       {'lat': 30.25438822816667, 'lon': 120.29409356266666},  # 十字路口 
    #    {'lat': 30.254348924333332, 'lon': 120.29465838716666}, # A8 湖边
    #    {'lat': 30.254405673833332, 'lon': 120.29409430816666}, # 十字路口 
       {'lat': 30.254458796833333, 'lon': 120.29339422566666}, # 307 实验室门口  
    #    {'lat': 30.254405673833332, 'lon': 120.29409430816666}, # 十字路口 
    #    {'lat': 30.254961930833332, 'lon': 120.29411244066667}, # A2 大门口
    ]
    
    node = GpsWaypointSender(target_waypoints)
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