"""行为树表驱动测试：并行失败终止、Selector挂起、Sequence短路、装饰器、确定性。"""

from __future__ import annotations

import pytest

from src import BehaviorTree, Sequence, Selector, Parallel, Action, Inverter


def _action(name, result):
    return Action(name, lambda: result)


def test_sequence_success():
    tree = BehaviorTree(Sequence("seq", [
        _action("a", "success"), _action("b", "success")]))
    assert tree.tick() == "success"


def test_sequence_failure_short_circuit():
    calls = []
    a = Action("a", lambda: "failure")
    b = Action("b", lambda: calls.append("b") or "success")
    tree = BehaviorTree(Sequence("seq", [a, b]))
    tree.tick()
    assert calls == [], "失败后不应执行后续节点"


def test_selector_running_suspend():
    """Selector遇到running应挂起，下一帧从该节点继续。"""
    state = {"count": 0}
    def running_then_success():
        state["count"] += 1
        return "running" if state["count"] < 2 else "success"
    a = Action("a", running_then_success)
    b = Action("b", lambda: "failure")
    tree = BehaviorTree(Selector("sel", [a, b]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert state["count"] == 2  # 只执行a，不跳到b


def test_parallel_failure_stops_others():
    """并行节点任一子节点失败必须终止其他子节点。"""
    calls = []
    fail = Action("fail", lambda: "failure")
    def slow():
        calls.append("slow")
        return "running"
    slow_action = Action("slow", slow)
    tree = BehaviorTree(Parallel("par", [fail, slow_action]))
    result = tree.tick()
    assert result == "failure"
    # 正确版本：fail后立即终止，slow_action不应被执行
    # BUG版本：会继续执行slow_action，calls不为空
    assert calls == [], "失败后应终止其他子节点，不应执行slow: %s" % calls


def test_parallel_all_success():
    tree = BehaviorTree(Parallel("par", [
        _action("a", "success"), _action("b", "success")]))
    assert tree.tick() == "success"


def test_parallel_running():
    a = Action("a", lambda: "running")
    b = Action("b", lambda: "success")
    tree = BehaviorTree(Parallel("par", [a, b]))
    assert tree.tick() == "running"


def test_inverter():
    tree = BehaviorTree(Inverter("inv", [_action("a", "failure")]))
    assert tree.tick() == "success"
    tree2 = BehaviorTree(Inverter("inv", [_action("a", "success")]))
    assert tree2.tick() == "failure"


def test_inverter_passes_running():
    a = Action("a", lambda: "running")
    tree = BehaviorTree(Inverter("inv", [a]))
    assert tree.tick() == "running"


def test_on_enter_exit_precise():
    a = Action("a", lambda: "success")
    tree = BehaviorTree(a)
    tree.tick()
    assert a.on_enter_count == 1
    assert a.on_exit_count == 1


def test_reset():
    a = Action("a", lambda: "success")
    tree = BehaviorTree(a)
    tree.tick()
    tree.reset()
    assert a.status == "idle"
    assert tree.tick_count == 0


def test_deterministic():
    def run():
        state = {"c": 0}
        def fn():
            state["c"] += 1
            return "running" if state["c"] < 3 else "success"
        tree = BehaviorTree(Sequence("s", [Action("a", fn), _action("b", "success")]))
        results = [tree.tick() for _ in range(5)]
        return (results, tree.snapshot())
    assert run() == run()
