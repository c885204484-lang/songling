#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from nav_msgs.msg import Path
from tf2_ros import Buffer, TransformListener
import math

class NavigationMonitor(Node):
    def __init__(self):
        super().__init__('navigation_monitor')
        
        # 初始化 TF 监听器，用于获取小车在 map 中的实时物理位置与朝向
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # 1. 监听底层控制指令 (诊断转圈、不走直线的原因)
        self.cmd_vel_sub = self.create_subscription(
            Twist, '/cmd_vel', self.cmd_vel_callback, 10)
        
        # 2. 监听 Nav2 实际吃到的全局路径 (诊断路径裁剪或丢失)
        self.plan_sub = self.create_subscription(
            Path, '/received_global_plan', self.plan_callback, 10)
            
        self.current_path_poses = []
        
        # 定时器：每秒钟计算并打印一次小车距离下一个目标点“该怎么走”
        self.guidance_timer = self.create_timer(1.0, self.guidance_callback)
        
        self.get_logger().info('🔍 增强版导航行为与导引监视器已启动，正在实时审计控制指令与运动轨迹...')

    def cmd_vel_callback(self, msg: Twist):
        linear_x = msg.linear.x
        angular_z = msg.angular.z
        
        # 诊断逻辑 1：检测是否触发了“原地转圈/极限打舵”死锁
        if abs(linear_x) < 0.05 and abs(angular_z) > 0.2:
            self.get_logger().warn(
                f'🌀 [转圈死锁警报] 线速度几乎为零 ({linear_x:.2f} m/s)，但角速度极高 ({angular_z:.2f} rad/s)！'
                f' -> 原因：纯跟踪控制器判定车身严重偏离路线，正在强行打死方向盘原地纠偏！'
            )

    def plan_callback(self, msg: Path):
        self.current_path_poses = msg.poses
        if len(msg.poses) == 0:
            self.get_logger().error('❌ [路径断开警报] Nav2 持有的有效路径点数为 0！路径已被强制裁剪或中止！')

    def guidance_callback(self):
        """核心新增：计算小车离下一个前瞻点还有多远，需要怎么走"""
        if not self.current_path_poses:
            return
            
        try:
            # 1. 获取小车当前在 map 下的绝对坐标 (x, y) 和绝对航向角 (Yaw)
            t = self.tf_buffer.lookup_transform('map', 'base_link', rclpy.time.Time())
            curr_x = t.transform.translation.x
            curr_y = t.transform.translation.y
            
            q = t.transform.rotation
            siny_cosp = 2 * (q.w * q.z + q.x * q.y)
            cosy_cosp = 1 - 2 * (q.y * q.y + q.z * q.z)
            curr_yaw = math.atan2(siny_cosp, cosy_cosp)
            
            # 2. 在当前路径中寻找一个距离小车前方约 1.0 米左右的点作为即时引导目标
            target_pose = None
            for pose in self.current_path_poses:
                px = pose.pose.position.x
                py = pose.pose.position.y
                dist = math.hypot(px - curr_x, py - curr_y)
                # 寻找第一个距离大于 0.8 米的点
                if dist > 0.8:
                    target_pose = pose
                    break
            
            # 如果路径很短，找不到大于0.8米的，就取路径上的最后一个点（终点）
            if target_pose is None and len(self.current_path_poses) > 0:
                target_pose = self.current_path_poses[-1]
                
            if target_pose:
                tx = target_pose.pose.position.x
                ty = target_pose.pose.position.y
                
                # 计算直线距离
                distance = math.hypot(tx - curr_x, ty - curr_y)
                
                # 计算目标点相对于车头正前方的夹角
                angle_to_target = math.atan2(ty - curr_y, tx - curr_x)
                rel_angle = angle_to_target - curr_yaw
                # 将角度归一化到 [-pi, pi]
                rel_angle = (rel_angle + math.pi) % (2 * math.pi) - math.pi
                rel_angle_deg = math.degrees(rel_angle)
                
                # 生成通俗易懂的“行驶导引建议”
                if abs(rel_angle_deg) < 10.0:
                    guidance = "🟢 路线正前方，直接直行"
                elif rel_angle_deg >= 10.0:
                    guidance = f"↗️ 目标在左侧，需向左偏航 {abs(rel_angle_deg):.1f}°"
                else:
                    guidance = f"↘️ 目标在右侧，需向右偏航 {abs(rel_angle_deg):.1f}°"
                    
                self.get_logger().info(
                    f'🧭 [实时导引] 距前瞻点: {distance:.2f}米 | 建议: {guidance} (车头相对偏差: {rel_angle_deg:+.1f}°)'
                )
        except Exception as e:
            # 刚启动时 TF 树可能还没完全就绪，静默跳过
            pass

def main(args=None):
    rclpy.init(args=args)
    node = NavigationMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info('🛑 诊断监视器已退出。')
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()

if __name__ == '__main__':
    main()