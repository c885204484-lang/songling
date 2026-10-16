install(DIRECTORY
  launch
  config
  urdf
  rviz    
  DESTINATION share/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/gps_waypoint_sender2_chd.py
  scripts/amap_path_follower.py
  DESTINATION lib/${PROJECT_NAME}
)

# ==================================================
# 注册 Python 节点脚本，安装到 lib 目录下供系统调用
# ==================================================
install(PROGRAMS
  scripts/pose_to_imu.py
  DESTINATION lib/${PROJECT_NAME}
)

install(PROGRAMS
  scripts/navigation_monitor.py
  DESTINATION lib/${PROJECT_NAME}
)

ament_package()