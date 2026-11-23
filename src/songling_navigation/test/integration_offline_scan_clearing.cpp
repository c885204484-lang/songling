// Test the installed Nav2 raytracer without sensors, TF or motion publishers.
#include <iostream>
#include <cmath>
#include "nav2_costmap_2d/obstacle_layer.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"
class Layer:public nav2_costmap_2d::ObstacleLayer {
public:
 void setup(){resizeMap(120,120,.1,-6,-6);std::fill(costmap_,costmap_+14400,254);}
 void clear(double inc,bool wall=false){
  nav2_costmap_2d::Observation o; o.origin_.x=0;o.origin_.y=0;o.origin_.z=.5;o.raytrace_max_range_=15;o.raytrace_min_range_=0;
  sensor_msgs::PointCloud2Modifier mod(*o.cloud_);mod.setPointCloud2FieldsByString(1,"xyz");int n=std::ceil(2*M_PI/inc);mod.resize(n);
  sensor_msgs::PointCloud2Iterator<float> x(*o.cloud_,"x"),y(*o.cloud_,"y"),z(*o.cloud_,"z");
  for(int i=0;i<n;++i,++x,++y,++z){double a=-3.14159+i*inc;double range=14.9999;if(wall && std::cos(a)>0 && std::abs(2*std::tan(a))<1)range=2/std::cos(a);*x=range*std::cos(a);*y=range*std::sin(a);*z=.5;}
  double a=1e9,b=1e9,c=-1e9,d=-1e9;raytraceFreespace(o,&a,&b,&c,&d);
 }
 int residual(double range){int n=0;for(unsigned y=0;y<120;y++)for(unsigned x=0;x<120;x++){double wx,wy;mapToWorld(x,y,wx,wy);double r=std::hypot(wx,wy);if(r>.7&&r<range&&getCost(x,y)==254)n++;}return n;}
};
int main(int argc,char**argv){rclcpp::init(argc,argv);for(double step:{.025,.005}){Layer l;l.setup();l.clear(step);std::cout<<"increment="<<step<<" uncleared cells within 1.5m="<<l.residual(1.5)<<" within 5m="<<l.residual(5)<<std::endl;if(step==.005&&l.residual(5)!=0)return 4;if(step==.025&&l.residual(5)==0)return 5;}Layer blocked;blocked.setup();blocked.clear(.005,true);unsigned x,y;blocked.worldToMap(3,0,x,y);if(blocked.getCost(x,y)!=254)return 2;blocked.worldToMap(1,0,x,y);if(blocked.getCost(x,y)!=0)return 3;std::cout<<"Real wall occlusion preserved; observed free space cleared."<<std::endl;rclcpp::shutdown();}
