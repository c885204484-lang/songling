import cv2
import numpy as np
import os

# 配置地图路径
input_map = 'final_map.pgm'
output_map = 'final_map_clean.pgm'

def clean_ros_map(img_path, out_path):
    print(f"正在读取地图: {img_path} ...")
    # 1. 以灰度模式读取图像
    img = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print("错误: 找不到地图文件，请检查路径！")
        return

    # 2. 提取障碍物掩码 (ROS中障碍物通常接近黑色，即像素值 < 50)
    # 将黑色障碍物变成白色(255)，其余变成黑色(0)，方便后续处理
    _, obstacles = cv2.threshold(img, 50, 255, cv2.THRESH_BINARY_INV)

    # 3. 形态学开运算 (Morphological Opening)
    # 这里的核心逻辑是：消除小的独立像素块（噪点），保留大的连通块（墙壁）
    # kernel 大小决定了去噪的强度。(3, 3) 适合去小点，如果噪点大可以改成 (5, 5)
    kernel = np.ones((3, 3), np.uint8)
    clean_obstacles = cv2.morphologyEx(obstacles, cv2.MORPH_OPEN, kernel)

    # 4. 找出被剔除的噪点
    # 用原始障碍物减去清理后的障碍物，得到的就是我们要抹去的噪点
    noise = cv2.subtract(obstacles, clean_obstacles)

    # 5. 将噪点在原图中“涂白” (254 是 ROS 默认的 Free Space 像素值)
    clean_map = img.copy()
    clean_map[noise == 255] = 254

    # 6. 保存最终结果
    cv2.imwrite(out_path, clean_map)
    print(f"清理成功！已生成降噪后的地图: {out_path}")

if __name__ == '__main__':
    # 确保在当前目录下运行
    clean_ros_map(input_map, output_map)