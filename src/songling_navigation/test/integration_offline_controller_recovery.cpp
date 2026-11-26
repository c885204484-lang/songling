// Exercise installed BT control nodes with the repository's real navigation XML.
// Mock action endpoints only: this test cannot send vehicle commands.
#include <cassert>
#include <iostream>
#include <string>
#include "behaviortree_cpp_v3/bt_factory.h"
struct Counts {int plans=0,clears=0,follows=0;bool controller_ok=false,planner_ok=true;};
void check(const std::string &file,bool initial_ok,bool planner_ok,bool fixed_path) {
 BT::BehaviorTreeFactory f;Counts c;c.controller_ok=initial_ok;c.planner_ok=planner_ok;
 for(auto name:{"recovery_node","pipeline_sequence","rate_controller","round_robin_node"})
  f.registerFromPlugin(std::string("/opt/ros/humble/lib/libnav2_")+name+"_bt_node.so");
 auto failed=[](BT::TreeNode &){return BT::NodeStatus::FAILURE;};
 f.registerSimpleCondition("GlobalUpdatedGoal",failed);f.registerSimpleCondition("GoalUpdated",failed);
 f.registerSimpleCondition("IsPathValid",[](BT::TreeNode &){return BT::NodeStatus::SUCCESS;},{BT::InputPort<std::string>("path")});
 auto compute=[&](BT::TreeNode &n){++c.plans;if(!c.planner_ok)return BT::NodeStatus::FAILURE;n.setOutput("path",std::string("fresh-from-current-pose"));return BT::NodeStatus::SUCCESS;};
 f.registerSimpleAction("ComputePathToPose",compute,{BT::InputPort<std::string>("goal"),BT::OutputPort<std::string>("path"),BT::InputPort<std::string>("planner_id")});
 f.registerSimpleAction("ComputePathThroughPoses",compute,{BT::InputPort<std::string>("goals"),BT::OutputPort<std::string>("path"),BT::InputPort<std::string>("planner_id")});
 f.registerSimpleAction("FollowPath",[&](BT::TreeNode &n){
  ++c.follows;
  const bool new_path=n.getInput<std::string>("path").value()=="fresh-from-current-pose";
  if(fixed_path)assert(new_path);
  return (c.controller_ok||(!fixed_path&&new_path))?BT::NodeStatus::SUCCESS:BT::NodeStatus::FAILURE;
 },{BT::InputPort<std::string>("path"),BT::InputPort<std::string>("controller_id"),BT::InputPort<std::string>("goal_checker_id")});
 f.registerSimpleAction("ClearEntireCostmap",[&](BT::TreeNode &){++c.clears;return BT::NodeStatus::SUCCESS;},{BT::InputPort<std::string>("service_name")});
 f.registerSimpleAction("RemovePassedGoals",[](BT::TreeNode &n){n.setOutput("output_goals",n.getInput<std::string>("input_goals").value());return BT::NodeStatus::SUCCESS;},{BT::InputPort<std::string>("input_goals"),BT::OutputPort<std::string>("output_goals"),BT::InputPort<double>("radius")});
 f.registerSimpleAction("Wait",[](BT::TreeNode &n){assert(n.getInput<int>("wait_duration").value()>=1);return BT::NodeStatus::SUCCESS;},{BT::InputPort<int>("wait_duration")});
 auto bb=BT::Blackboard::create();bb->set("path",std::string("original-long-path"));bb->set("goals",std::string("remaining-goals"));bb->set("goal",std::string("terminal-goal"));
 auto tree=f.createTreeFromFile(file,bb);BT::NodeStatus status=BT::NodeStatus::RUNNING;
 for(int i=0;i<30&&status==BT::NodeStatus::RUNNING;i++)status=tree.tickRoot();
 if(fixed_path){
  const auto expected=initial_ok&&planner_ok?BT::NodeStatus::SUCCESS:BT::NodeStatus::FAILURE;
  assert(status==expected);
  assert(c.plans==(planner_ok?1:2));
  assert(c.clears==(planner_ok?0:1));
  assert(c.follows==(planner_ok?1:0));
 }
 else if(initial_ok){assert(status==BT::NodeStatus::SUCCESS);assert(c.plans==0&&c.clears==0);}
 else if(planner_ok){assert(status==BT::NodeStatus::SUCCESS);assert(c.plans==1&&c.clears==1&&c.follows==2);}
 else {assert(status!=BT::NodeStatus::SUCCESS);assert(c.plans>0);}
 std::cout<<file<<" initial_ok="<<initial_ok<<" planner_ok="<<planner_ok<<" plans="<<c.plans<<" follows="<<c.follows<<" PASSED"<<std::endl;
}
int main(int argc,char**argv){
 assert(argc==5);
 for(int i=1;i<argc;i++){
  const bool fixed_path=i>=3;
  check(argv[i],true,true,fixed_path);
  check(argv[i],false,true,fixed_path);
  check(argv[i],false,false,fixed_path);
 }
}
