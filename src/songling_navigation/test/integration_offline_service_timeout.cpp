// Reproduce a Jetson-sized clear-service delay using the installed Nav2 BT node.
// Uses only /offline_regression_clear in an isolated ROS domain.
#include <cassert>
#include <chrono>
#include <thread>
#include "behaviortree_cpp_v3/bt_factory.h"
#include "nav2_msgs/srv/clear_entire_costmap.hpp"
#include "rclcpp/rclcpp.hpp"
using namespace std::chrono_literals;
BT::NodeStatus run(int timeout) {
  auto client = std::make_shared<rclcpp::Node>("clear_timeout_client_"+std::to_string(timeout));
  BT::BehaviorTreeFactory factory;
  factory.registerFromPlugin("/opt/ros/humble/lib/libnav2_clear_costmap_service_bt_node.so");
  auto bb=BT::Blackboard::create();bb->set("node",client);
  bb->set("server_timeout",std::chrono::milliseconds(timeout));bb->set("bt_loop_duration",10ms);
  bb->set("wait_for_service_timeout",1000ms);bb->set("number_recoveries",0);
  auto tree=factory.createTreeFromText(R"(<root main_tree_to_execute="MainTree"><BehaviorTree ID="MainTree"><ClearEntireCostmap service_name="/offline_regression_clear"/></BehaviorTree></root>)",bb);
  auto status=BT::NodeStatus::RUNNING;
  for(int i=0;i<100 && status==BT::NodeStatus::RUNNING;i++){status=tree.tickRoot();std::this_thread::sleep_for(10ms);}
  return status;
}
int main(int argc,char**argv) {
  rclcpp::init(argc,argv);
  auto server=std::make_shared<rclcpp::Node>("delayed_clear_server");
  auto service=server->create_service<nav2_msgs::srv::ClearEntireCostmap>("/offline_regression_clear",[](std::shared_ptr<nav2_msgs::srv::ClearEntireCostmap::Request>, std::shared_ptr<nav2_msgs::srv::ClearEntireCostmap::Response>){std::this_thread::sleep_for(80ms);});
  rclcpp::executors::SingleThreadedExecutor executor;executor.add_node(server);
  std::thread worker([&]{executor.spin();});
  auto before=run(20);std::this_thread::sleep_for(100ms);auto after=run(200);
  executor.cancel();worker.join();rclcpp::shutdown();
  assert(before==BT::NodeStatus::FAILURE);assert(after==BT::NodeStatus::SUCCESS);
  std::cout<<"80 ms clear response: 20 ms timeout fails, 200 ms timeout succeeds."<<std::endl;
}
