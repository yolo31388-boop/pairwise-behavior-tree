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


# ---------- 并行：失败终止 ----------

def test_parallel_failure_terminates_running_children():
    """失败时正在running的兄弟节点必须被重置回idle。"""
    running_child = Action("run", lambda: "running")
    fail = Action("fail", lambda: "failure")
    tree = BehaviorTree(Parallel("par", [running_child, fail]))
    assert tree.tick() == "failure"
    assert running_child.status == "idle", "running子节点应被终止重置"
    assert fail.status == "failure"


def test_parallel_failure_never_ticks_later_children():
    """失败点之后的子节点本帧不应被执行。"""
    calls = []
    late = Action("late", lambda: calls.append("late") or "success")
    tree = BehaviorTree(Parallel("par", [
        _action("ok", "success"), _action("bad", "failure"), late]))
    assert tree.tick() == "failure"
    assert calls == []


# ---------- 并行：全成功 / running挂起 ----------

def test_parallel_remembers_completed_children():
    """running挂起期间已成功的子节点下一帧不得重复执行。"""
    counts = {"a": 0}
    def a_fn():
        counts["a"] += 1
        return "success"
    state = {"n": 0}
    def b_fn():
        state["n"] += 1
        return "running" if state["n"] < 2 else "success"
    tree = BehaviorTree(Parallel("par", [Action("a", a_fn), Action("b", b_fn)]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert counts["a"] == 1, "已完成子节点不应被重复tick"


def test_parallel_all_success_multi():
    tree = BehaviorTree(Parallel("par", [
        _action("a", "success"), _action("b", "success"), _action("c", "success")]))
    assert tree.tick() == "success"
    assert all(c.status == "success" for c in tree.root.children)


# ---------- 选择器：running继续 ----------

def test_selector_resume_does_not_reevaluate_earlier():
    """挂起恢复后，前面已失败的子节点不得重新评估。"""
    calls = []
    a = Action("a", lambda: calls.append("a") or "failure")
    state = {"n": 0}
    def b_fn():
        state["n"] += 1
        return "running" if state["n"] < 2 else "success"
    tree = BehaviorTree(Selector("sel", [a, Action("b", b_fn)]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert calls == ["a"], "恢复时不应从头重新评估"


def test_selector_running_then_failure_falls_through():
    """running的子节点最终失败时，选择器继续尝试后续子节点。"""
    state = {"n": 0}
    def a_fn():
        state["n"] += 1
        return "running" if state["n"] < 2 else "failure"
    tree = BehaviorTree(Selector("sel", [
        Action("a", a_fn), _action("b", "success")]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"


# ---------- 序列：短路 / 挂起 ----------

def test_sequence_running_resume_skips_completed():
    """序列挂起恢复后，已成功子节点不得重复执行。"""
    counts = {"a": 0}
    def a_fn():
        counts["a"] += 1
        return "success"
    state = {"n": 0}
    def b_fn():
        state["n"] += 1
        return "running" if state["n"] < 3 else "success"
    tree = BehaviorTree(Sequence("seq", [Action("a", a_fn), Action("b", b_fn)]))
    assert tree.tick() == "running"
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert counts["a"] == 1


def test_sequence_failure_result_is_not_success():
    tree = BehaviorTree(Sequence("seq", [
        _action("a", "success"), _action("b", "failure"), _action("c", "success")]))
    result = tree.tick()
    assert result == "failure"
    assert result != "success"
    assert tree.root.children[2].status == "idle", "失败短路，后续节点不应执行"


# ---------- 装饰器：传递running / 终态幂等 ----------

def test_inverter_running_then_resolves():
    state = {"n": 0}
    def fn():
        state["n"] += 1
        return "running" if state["n"] < 2 else "failure"
    tree = BehaviorTree(Inverter("inv", [Action("a", fn)]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"


def test_terminal_tick_is_idempotent():
    """已完成节点再次tick不改变结果也不重复触发回调。"""
    a = _action("a", "success")
    tree = BehaviorTree(Sequence("seq", [a]))
    first = tree.tick()
    assert tree.tick() == first and tree.tick() == first
    assert tree.root.on_enter_count == 1
    assert tree.root.on_exit_count == 1
    assert a.on_enter_count == 1 and a.on_exit_count == 1


# ---------- 回调精确 ----------

def test_callbacks_precise_in_nested_tree():
    seq = Sequence("seq", [
        Parallel("par", [_action("a", "success"), _action("b", "success")]),
        Selector("sel", [_action("c", "failure"), _action("d", "success")]),
    ])
    tree = BehaviorTree(seq)
    assert tree.tick() == "success"
    for node in [seq, seq.children[0], seq.children[1]]:
        assert node.on_enter_count == 1, node.name
        assert node.on_exit_count == 1, node.name


# ---------- 确定性 ----------

def test_determinism_complex_tree():
    def run():
        state = {"n": 0}
        def move():
            state["n"] += 1
            return "running" if state["n"] < 2 else "success"
        root = Sequence("root", [
            Parallel("par", [Action("move", move), _action("defend", "success")]),
            Selector("sel", [_action("attack", "failure"), _action("retreat", "success")]),
        ])
        tree = BehaviorTree(root)
        return [tree.tick() for _ in range(4)], tree.snapshot()
    assert run() == run()


# ---------- 中断重置 ----------

def test_interrupt_reset_restores_behavior():
    """运行中途reset后，整树行为与全新树一致。"""
    def build():
        state = {"n": 0}
        def fn():
            state["n"] += 1
            return "running" if state["n"] < 3 else "success"
        return BehaviorTree(Sequence("seq", [Action("a", fn), _action("b", "success")])), state
    tree, state = build()
    assert tree.tick() == "running"
    tree.reset()
    state["n"] = 0  # 外部事件同步重置世界状态
    assert all(c.status == "idle" for c in tree.root.children)
    fresh, _ = build()
    assert [tree.tick() for _ in range(3)] == [fresh.tick() for _ in range(3)]
    assert tree.snapshot()["root"] == fresh.snapshot()["root"]


# ---------- 复杂嵌套树 ----------

def test_nested_parallel_failure_propagates():
    """嵌套树中并行失败向上传播，且兄弟分支不被执行。"""
    calls = []
    par = Parallel("par", [
        _action("move", "running"), _action("attack", "failure")])
    sel = Selector("sel", [
        Action("fallback", lambda: calls.append("fb") or "success")])
    tree = BehaviorTree(Sequence("root", [par, sel]))
    assert tree.tick() == "failure"
    assert calls == [], "序列短路，selector分支不应执行"
    assert par.children[0].status == "idle", "并行失败应终止running子节点"


# ---------- 空节点安全 ----------

def test_empty_nodes_safe():
    assert BehaviorTree(Sequence("s", [])).tick() == "success"
    assert BehaviorTree(Selector("s", [])).tick() == "failure"
    assert BehaviorTree(Parallel("p", [])).tick() == "success"
    inv = Inverter("inv", [])
    assert BehaviorTree(inv).tick() == "failure"
    assert inv.on_enter_count == 1
    assert inv.on_exit_count == 1
