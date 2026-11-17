import pytest

from ai.behavior_tree import (
    FAILURE,
    RUNNING,
    SUCCESS,
    Blackboard,
    Cooldown,
    Inverter,
    Leaf,
    Parallel,
    Selector,
    Sequence,
)


def leaf(status):
    return Leaf(status)


def test_selector_returns_first_success():
    assert Selector([leaf(FAILURE), leaf(SUCCESS)]).tick({}) == SUCCESS


def test_selector_remembers_running_child():
    running = leaf(RUNNING)
    success = leaf(SUCCESS)
    selector = Selector([running, success])
    assert selector.tick({}) == RUNNING
    assert selector.tick({}) == RUNNING
    assert success.ticks == 0


def test_selector_prefers_first_child():
    assert Selector([leaf(SUCCESS), leaf(FAILURE)]).tick({}) == SUCCESS


def test_sequence_stops_after_failure():
    first = leaf(SUCCESS)
    second = leaf(FAILURE)
    assert Sequence([first, second]).tick({}) == FAILURE
    assert first.ticks == 1
    assert second.ticks == 1


def test_sequence_all_success():
    assert Sequence([leaf(SUCCESS), leaf(SUCCESS)]).tick({}) == SUCCESS


def test_parallel_require_all_success():
    assert Parallel([leaf(SUCCESS), leaf(SUCCESS)]).tick({}) == SUCCESS


def test_parallel_any_policy():
    assert Parallel([leaf(FAILURE), leaf(SUCCESS)], require_all=False).tick({}) == SUCCESS


def test_blackboard_scope_isolated():
    board = Blackboard()
    board.set("boss", "hp", 100)
    assert board.get("boss", "hp") == 100
    assert board.get("player", "hp") is None


def test_cooldown_gates_child():
    child = leaf(SUCCESS)
    gate = Cooldown(child, ticks=2)
    assert gate.tick({}) == FAILURE
    assert gate.tick({}) == SUCCESS
    assert child.ticks == 1


def test_selector_reset_clears_running():
    child = leaf(RUNNING)
    selector = Selector([child])
    assert selector.tick({}) == RUNNING
    selector.reset()
    child.status = SUCCESS
    assert selector.tick({}) == SUCCESS


def test_inverter_flips_failure():
    assert Inverter(leaf(FAILURE)).tick({}) == SUCCESS


def test_sequence_propagates_running_without_ticking_later_child():
    running = leaf(RUNNING)
    later = leaf(SUCCESS)
    assert Sequence([running, later]).tick({}) == RUNNING
    assert later.ticks == 0


def test_parallel_ticks_every_child_once():
    first = leaf(SUCCESS)
    second = leaf(SUCCESS)
    Parallel([first, second]).tick({})
    assert first.ticks == 1 and second.ticks == 1


def test_blackboard_overwrites_value():
    board = Blackboard()
    board.set("boss", "hp", 100)
    board.set("boss", "hp", 50)
    assert board.get("boss", "hp") == 50


def test_selector_does_not_retick_running_child():
    running = leaf(RUNNING)
    selector = Selector([running, leaf(SUCCESS)])
    selector.tick({})
    selector.tick({})
    assert running.ticks == 1
