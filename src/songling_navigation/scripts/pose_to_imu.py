#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import Imu

# 👇 必须新增这两个导入，否则会报错找不到库
import math
import tf_transformations

class PoseToImuNode(Node):
    def __init__(self):
        super().__init__('pose_to_imu_node')
        
        # 订阅 RTK 的位姿话题
        self.subscription = self.create_subscription(
            PoseStamped,
            '/gps/pose', 
            self.pose_callback,
            10)
            
        # 发布 navsat_transform 需要的 IMU 话题
        self.publisher = self.create_publisher(Imu, '/rtk/imu', 10)
        self.get_logger().info("🔄 RTK Pose -> IMU 转换节点已启动！正在监听 /gps/pose...")

    def pose_callback(self, msg):
        imu_msg = Imu()
        
        # 1. 照抄时间戳和坐标系
        imu_msg.header = msg.header
        # 强制将 frame_id 统一，防止 TF 报错，或者直接用 msg.header.frame_id (即 navsat_link)
        # imu_msg.header.frame_id = 'navsat_link' 
        
        # 2. 先把 RTK 传来的四元数转回欧拉角 (Yaw)
        quaternion = (
            msg.pose.orientation.x,
            msg.pose.orientation.y,
            msg.pose.orientation.z,
            msg.pose.orientation.w
        )
        _, _, rtk_yaw = tf_transformations.euler_from_quaternion(quaternion)
        
        # 3. 🌟 核心转换：将 RTK 航向转为 ROS ENU 航向
        # 假设 RTK 是：0度正北，顺时针增加。
        # ROS 需要是：0度正东，逆时针增加。
        # 转换公式： ros_yaw = pi/2 - rtk_yaw (并将其限制在 -pi 到 pi 之间)
        ros_yaw = (math.pi / 2.0) - rtk_yaw
        
        if ros_yaw > math.pi:
            ros_yaw -= 2.0 * math.pi
        elif ros_yaw < -math.pi:
            ros_yaw += 2.0 * math.pi
            
        # 4. 将转换后的正确 Yaw 重新打包成四元数，并直接赋值给 imu_msg
        new_quat = tf_transformations.quaternion_from_euler(0, 0, ros_yaw)
        imu_msg.orientation.x = new_quat[0]
        imu_msg.orientation.y = new_quat[1]
        imu_msg.orientation.z = new_quat[2]
        imu_msg.orientation.w = new_quat[3]
        
        # ⚠️ 注意：原来在这里的那句 imu_msg.orientation = msg.pose.orientation 已经被彻底删除了！

        # 5. 填入微小的协方差，告诉滤波器：我们非常信任这个双天线航向！
        imu_msg.orientation_covariance = [
            0.01, 0.0, 0.0,
            0.0, 0.01, 0.0,
            0.0, 0.0, 0.01
        ]
        
        # 6. 把角速度和加速度标记为“无效”（因为我们只有航向，没有加速度计数据）
        # 按照 ROS REP-145 规范，将协方差矩阵的第一个元素设为 -1 代表忽略该数据
        imu_msg.angular_velocity_covariance[0] = -1.0 
        imu_msg.linear_acceleration_covariance[0] = -1.0
        
        # 发送包装好的 IMU 数据！
        self.publisher.publish(imu_msg)

def main(args=None):
    rclpy.init(args=args)
    node = PoseToImuNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()