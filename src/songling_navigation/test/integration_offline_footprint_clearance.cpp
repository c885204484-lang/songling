// Use Nav2's installed footprint checker to catch duplicate body clearance.
#include <cassert>
#include <iostream>
#include <fstream>
#include "nav2_costmap_2d/footprint_collision_checker.hpp"

int main(int argc, char ** argv) {
  nav2_costmap_2d::Costmap2D center_map(160, 160, .05, -4., -4., 0);
  nav2_costmap_2d::Costmap2D body_map(160, 160, .05, -4., -4., 0);
  for (unsigned y = 0; y < 160; ++y) {
    for (unsigned x = 0; x < 160; ++x) {
      double wx, wy;
      body_map.mapToWorld(x, y, wx, wy);
      if (wx >= -.65) center_map.setCost(x, y, 254);
      if (wx >= 0.) body_map.setCost(x, y, 254);
    }
  }
  nav2_costmap_2d::Footprint footprint;
  for (auto xy : {std::pair<double, double>{-.43, -.34}, {-.43, .34},
                 {.43, .34}, {.43, -.34}}) {
    geometry_msgs::msg::Point point;
    point.x = xy.first;
    point.y = xy.second;
    footprint.push_back(point);
  }
  nav2_costmap_2d::FootprintCollisionChecker<nav2_costmap_2d::Costmap2D *> before(&center_map);
  nav2_costmap_2d::FootprintCollisionChecker<nav2_costmap_2d::Costmap2D *> after(&body_map);
  // The center is over .65m from the actual wall. Sweeping the full body over
  // an already expanded map reports a collision despite sufficient clearance.
  assert(before.footprintCostAtPose(-.85, 0., 0., footprint) == 254);
  assert(after.footprintCostAtPose(-.85, 0., 0., footprint) == 0);
  // A body genuinely crossing the original wall must still be rejected.
  assert(after.footprintCostAtPose(-.2, 0., 0., footprint) == 254);
  std::cout << "Duplicate clearance removed; physical wall collision still rejected.\n";
  if (argc == 2) {
    std::ifstream input(argv[1]);
    unsigned width, height, count;
    double resolution, origin_x, origin_y;
    input >> width >> height >> resolution >> origin_x >> origin_y;
    nav2_costmap_2d::Costmap2D old_grid(width, height, resolution, origin_x, origin_y, 0);
    nav2_costmap_2d::Costmap2D new_grid(width, height, resolution, origin_x, origin_y, 0);
    for (auto grid : {&old_grid, &new_grid}) {
      for (unsigned y = 0; y < height; ++y) {
        for (unsigned x = 0; x < width; ++x) {
          int cost;
          input >> cost;
          grid->setCost(x, y, cost);
        }
      }
    }
    nav2_costmap_2d::FootprintCollisionChecker<nav2_costmap_2d::Costmap2D *> old_checker(&old_grid);
    nav2_costmap_2d::FootprintCollisionChecker<nav2_costmap_2d::Costmap2D *> new_checker(&new_grid);
    input >> count;
    unsigned old_hits = 0, new_hits = 0;
    for (unsigned i = 0; i < count; ++i) {
      double x, y, yaw;
      input >> x >> y >> yaw;
      double old_cost = old_checker.footprintCostAtPose(x, y, yaw, footprint);
      double new_cost = new_checker.footprintCostAtPose(x, y, yaw, footprint);
      std::cout << "Field arc " << i << " previous cost=" << old_cost << " corrected cost=" << new_cost << '\n';
      old_hits += old_cost >= 254;
      new_hits += new_cost >= 254;
    }
    assert(input.good());
    assert(old_hits > 0);
    assert(new_hits == 0);
  }
}
