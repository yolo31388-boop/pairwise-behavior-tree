"""行为树不变量回归测试：并行终止、挂起恢复、装饰器、回调、确定性、中断。"""

from __future__ import annotations

from src import (
    BehaviorTree, Action, Sequence, Selector, Parallel,
    Inverter, Repeat, UntilFail,
)


def _action(name, result):
    return Action(name, lambda: result)


def _scripted(name, results):
    """按脚本依次返回结果的Action。"""
    state = {"i": 0}
    def fn():
        r = results[min(state["i"], len(results) - 1)]
        state["i"] += 1
        return r
    return Action(name, fn), state


# 1. 并行失败终止：任一子节点失败立即终止其他running子节点
def test_parallel_failure_terminates_running_siblings():
    move = Action("move", lambda: "running")
    attack = Action("attack", lambda: "failure")
    defend = Action("defend", lambda: "running")
    tree = BehaviorTree(Parallel("par", [move, attack, defend]))
    assert tree.tick() == "failure"
    # 失败位置之后的defend本帧未被tick；之前的move被abort重置
    assert defend.on_enter_count == 0
    assert move.status == "idle"
    assert move.on_enter_count == 1
    assert move.on_exit_count == 1  # 被终止时精确退出一次


def test_parallel_failure_late_child_aborts_earlier_running():
    slow = Action("slow", lambda: "running")
    ok = _action("ok", "success")
    fail = _action("fail", "failure")
    tree = BehaviorTree(Parallel("par", [slow, ok, fail]))
    assert tree.tick() == "failure"
    assert slow.status == "idle"
    assert slow.on_exit_count == 1


# 2. 并行全成功才返回成功
def test_parallel_all_success_required():
    a, _ = _scripted("a", ["running", "success"])
    b = _action("b", "success")
    tree = BehaviorTree(Parallel("par", [a, b]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"


# 3. 并行running挂起并记住已完成的子节点
def test_parallel_running_remembers_completed():
    done, done_state = _scripted("done", ["success"])
    slow, _ = _scripted("slow", ["running", "running", "success"])
    tree = BehaviorTree(Parallel("par", [done, slow]))
    assert tree.tick() == "running"
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert done_state["i"] == 1  # 已完成的子节点不会被重复tick


# 4. 选择器running挂起，下一帧从该节点继续而非从头评估
def test_selector_running_resume_not_restart():
    first, first_state = _scripted("first", ["failure"])
    second, _ = _scripted("second", ["running", "success"])
    third = _action("third", "success")
    tree = BehaviorTree(Selector("sel", [first, second, third]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert first_state["i"] == 1  # 已失败的first不被重新评估
    assert third.on_enter_count == 0  # second成功后不再执行third


# 5. 序列失败短路：立即返回failure，后续子节点不执行
def test_sequence_failure_short_circuits():
    calls = []
    a = _action("a", "success")
    b = Action("b", lambda: "failure")
    c = Action("c", lambda: calls.append("c") or "success")
    tree = BehaviorTree(Sequence("seq", [a, b, c]))
    assert tree.tick() == "failure"
    assert calls == []
    assert c.on_enter_count == 0


# 6. 序列running挂起，下一帧从running子节点继续
def test_sequence_running_suspend_resume():
    a, a_state = _scripted("a", ["success"])
    b, _ = _scripted("b", ["running", "success"])
    c = _action("c", "success")
    tree = BehaviorTree(Sequence("seq", [a, b, c]))
    assert tree.tick() == "running"
    assert tree.tick() == "success"
    assert a_state["i"] == 1  # 已完成的a不被重复执行
    assert c.on_enter_count == 1


# 7. 装饰器正确传递running
def test_decorators_pass_running():
    r = Action("r", lambda: "running")
    assert BehaviorTree(Inverter("inv", [r])).tick() == "running"
    assert BehaviorTree(Repeat("rep", [r], times=3)).tick() == "running"
    assert BehaviorTree(UntilFail("uf", [r])).tick() == "running"


def test_repeat_and_until_fail_semantics():
    child, state = _scripted("c", ["success"])
    tree = BehaviorTree(Repeat("rep", [child], times=3))
    assert tree.tick() == "success"
    assert state["i"] == 3
    f, fstate = _scripted("f", ["success", "success", "failure"])
    assert BehaviorTree(UntilFail("uf", [f])).tick() == "success"
    assert fstate["i"] == 3
    inv = BehaviorTree(Inverter("inv", [_action("x", "failure")]))
    assert inv.tick() == "success"


# 8. on_enter/on_exit精确一次
def test_enter_exit_exactly_once_composite():
    a, _ = _scripted("a", ["running", "success"])
    seq = Sequence("seq", [a, _action("b", "success")])
    tree = BehaviorTree(seq)
    tree.tick()
    tree.tick()
    assert seq.on_enter_count == 1
    assert seq.on_exit_count == 1
    assert a.on_enter_count == 1
    assert a.on_exit_count == 1


def test_terminal_tick_is_idempotent_no_double_exit():
    a = _action("a", "success")
    tree = BehaviorTree(a)
    assert tree.tick() == "success"
    assert tree.tick() == "success"  # 完成后重复tick结果确定
    assert a.on_enter_count == 1
    assert a.on_exit_count == 1


# 9. 确定性：相同输入和tick序列产生相同结果
def test_deterministic_same_inputs_same_results():
    def run():
        slow, _ = _scripted("slow", ["running", "running", "success"])
        fail_late, _ = _scripted("fl", ["running", "failure"])
        par = Parallel("par", [slow, _action("ok", "success")])
        root = Selector("root", [par, Sequence("seq", [fail_late, _action("z", "success")])])
        tree = BehaviorTree(root)
        return [tree.tick() for _ in range(4)], tree.snapshot()
    assert run() == run()


# 10. 中断外部事件正确重置子节点状态
def test_interrupt_resets_running_subtree():
    slow = Action("slow", lambda: "running")
    inner = Sequence("inner", [slow, _action("b", "success")])
    tree = BehaviorTree(Parallel("par", [inner, _action("c", "success")]))
    assert tree.tick() == "running"
    tree.interrupt()
    assert tree.root.status == "idle"
    assert inner.status == "idle"
    assert slow.status == "idle"
    assert slow.on_enter_count == slow.on_exit_count == 1  # 中断触发一次exit
    # 中断后重新tick，行为确定
    assert tree.tick() == "running"


# 11. 复杂嵌套树：Parallel内嵌Sequence/Selector/Inverter
def test_complex_nested_tree():
    atk, _ = _scripted("atk", ["running", "failure"])
    move_seq = Sequence("move_seq", [
        _action("step1", "success"), Action("step2", lambda: "running")])
    skill_sel = Selector("skill_sel", [
        Inverter("inv", [_action("heal_ok", "success")]), atk])
    tree = BehaviorTree(Parallel("root", [move_seq, skill_sel]))
    assert tree.tick() == "running"   # step2与atk都在running
    assert tree.tick() == "failure"   # atk失败 -> selector失败 -> parallel终止全部
    assert move_seq.status == "idle"  # 被并行节点终止并重置
    step2 = move_seq.children[1]
    assert step2.on_enter_count == 1
    assert step2.on_exit_count == 1


# 12. 空节点安全
def test_empty_nodes_safe():
    assert BehaviorTree(Sequence("s", [])).tick() == "success"
    assert BehaviorTree(Selector("s", [])).tick() == "failure"
    assert BehaviorTree(Parallel("p", [])).tick() == "success"
    assert BehaviorTree(Inverter("i", [])).tick() == "failure"
    assert BehaviorTree(Repeat("r", [], times=5)).tick() == "success"
    assert BehaviorTree(UntilFail("u", [])).tick() == "success"
