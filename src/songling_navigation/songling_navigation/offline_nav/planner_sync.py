"""Refresh Humble Smac's grid-unit search settings after map resolution changes."""

import math
import time

from nav2_msgs.msg import Costmap
from rcl_interfaces.msg import Parameter
from rcl_interfaces.srv import GetParameters, SetParametersAtomically
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy


class PlannerResolutionSync:
    names = [
        "GridBased.minimum_turning_radius",
        "GridBased.analytic_expansion_max_length",
        "GridBased.angle_quantization_bins",
    ]

    def __init__(self, node):
        self.node = node
        self.observed = self.synced = self.pending = None
        self.started = self.retry_at = 0.0
        self.error = ""
        self.get = node.create_client(GetParameters, "/planner_server/get_parameters")
        self.put = node.create_client(
            SetParametersAtomically, "/planner_server/set_parameters_atomically"
        )
        node.create_subscription(
            Costmap, "/global_costmap/costmap_raw", self.on_costmap,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                       reliability=ReliabilityPolicy.RELIABLE),
        )
        node.create_timer(0.2, self.tick)

    def on_costmap(self, message):
        resolution = message.metadata.resolution
        if not math.isfinite(resolution) or resolution <= 0:
            return
        if self.observed != resolution:
            self.synced = None
        self.observed = resolution

    def ready_for(self, resolution):
        return (self.pending is None and self.observed is not None
                and self.synced is not None
                and math.isclose(self.observed, resolution, rel_tol=1e-6)
                and math.isclose(self.synced, resolution, rel_tol=1e-6))

    def matches_map(self, resolution):
        model = self.node.active_model
        return (model is not None and self.observed is not None
                and math.isclose(model.resolution, resolution, rel_tol=1e-6)
                and math.isclose(self.observed, resolution, rel_tol=1e-6))

    def tick(self):
        if self.pending is not None:
            if time.monotonic() - self.started > 8:
                future, self.pending = self.pending, None
                future.cancel()
                self.error = "规划器参数同步超时"
                self.retry_at = time.monotonic() + 1
            return
        if self.node.busy or self.node.active_model is None:
            return
        resolution = self.node.active_model.resolution
        if (self.ready_for(resolution) or not self.matches_map(resolution)
                or time.monotonic() < self.retry_at
                or not self.get.service_is_ready() or not self.put.service_is_ready()):
            return
        request = GetParameters.Request()
        request.names = self.names
        self.started = time.monotonic()
        self.pending = self.get.call_async(request)
        self.pending.add_done_callback(lambda f: self.received(f, resolution))

    def failed(self, exc):
        self.pending = None
        self.error = str(exc)
        self.retry_at = time.monotonic() + 1

    def received(self, future, resolution):
        if future is not self.pending:
            return
        try:
            values = future.result().values
            if (len(values) != 3 or [v.type for v in values] != [3, 3, 2]
                    or values[0].double_value <= 0 or values[1].double_value <= 0
                    or values[2].integer_value <= 0):
                raise ValueError("规划器搜索参数无效")
            if self.node.busy or not self.matches_map(resolution):
                self.pending = None
                return
            request = SetParametersAtomically.Request()
            # Reassign exactly the current values. Humble's callback recalculates
            # turning primitives in cells using the newly received map resolution.
            request.parameters = [Parameter(name=k, value=v) for k, v in zip(self.names, values)]
            self.pending = self.put.call_async(request)
            self.pending.add_done_callback(lambda f: self.finished(f, resolution))
        except Exception as exc:
            self.failed(exc)

    def finished(self, future, resolution):
        if future is not self.pending:
            return
        try:
            result = future.result().result
            if not result.successful:
                raise ValueError(result.reason or "规划器拒绝同步")
            self.synced = resolution if self.matches_map(resolution) else None
            self.pending = None
            self.error = ""
        except Exception as exc:
            self.failed(exc)
