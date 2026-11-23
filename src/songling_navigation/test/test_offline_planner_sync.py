"""Map resolution changes must not retain Smac's previous grid-unit radius."""

from concurrent.futures import Future
from types import SimpleNamespace

import pytest

pytest.importorskip("rclpy")
from rcl_interfaces.msg import ParameterValue, SetParametersResult
from songling_navigation.offline_nav.planner_sync import PlannerResolutionSync


class Client:
    def __init__(self):
        self.calls = []
        self.futures = []

    def service_is_ready(self):
        return True

    def call_async(self, request):
        future = Future()
        self.calls.append(request)
        self.futures.append(future)
        return future


def sync_state():
    clients = [Client(), Client()]
    node = SimpleNamespace(busy=False, active_model=SimpleNamespace(resolution=0.515),
        create_client=lambda *args: clients.pop(0),
        create_subscription=lambda *args: None, create_timer=lambda *args: None)
    sync = PlannerResolutionSync(node)
    return sync


def observe(sync, resolution):
    sync.on_costmap(SimpleNamespace(metadata=SimpleNamespace(resolution=resolution)))


def parameters(sync):
    values = [ParameterValue(type=3, double_value=1.9),
              ParameterValue(type=3, double_value=3.0),
              ParameterValue(type=2, integer_value=72)]
    sync.get.futures[-1].set_result(SimpleNamespace(values=values))
    return values


def test_initial_map_must_match_before_refresh_and_plan_ready():
    sync = sync_state()
    observe(sync, .1)
    sync.tick()
    assert not sync.get.calls
    assert not sync.ready_for(.515)
    observe(sync, .515)
    sync.tick()
    assert len(sync.get.calls) == 1
    values = parameters(sync)
    assert [p.name for p in sync.put.calls[0].parameters] == sync.names
    assert [p.value for p in sync.put.calls[0].parameters] == values
    assert not sync.ready_for(.515)
    sync.put.futures[0].set_result(SimpleNamespace(result=SetParametersResult(successful=True)))
    assert sync.ready_for(.515)
    sync.tick()
    assert len(sync.get.calls) == 1


def test_resolution_change_invalidates_previous_ready_state():
    sync = sync_state()
    observe(sync, .515)
    sync.synced = .515
    assert sync.ready_for(.515)
    observe(sync, .1)
    assert not sync.ready_for(.515)
    assert not sync.ready_for(.1)


def test_map_changed_while_reading_parameters_does_not_write_old_refresh():
    sync = sync_state()
    observe(sync, .515)
    sync.tick()
    observe(sync, .2)
    parameters(sync)
    assert not sync.put.calls
    assert sync.pending is None
    assert not sync.ready_for(.515)


def test_does_not_refresh_while_navigating():
    sync = sync_state()
    observe(sync, .515)
    sync.node.busy = True
    sync.tick()
    assert not sync.get.calls


def test_rejected_refresh_does_not_enable_planning():
    sync = sync_state()
    observe(sync, .515)
    sync.tick()
    parameters(sync)
    sync.put.futures[0].set_result(SimpleNamespace(result=SetParametersResult(successful=False, reason="rejected")))
    assert not sync.ready_for(.515)
    assert sync.error == "rejected"
