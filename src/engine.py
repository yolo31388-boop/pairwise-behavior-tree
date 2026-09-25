"""行为树AI引擎：Sequence/Selector/Parallel/装饰器，running挂起，确定性。

核心不变量：
- Parallel任一子节点失败立即终止其他子节点
- Selector遇到running挂起，下一帧继续
- Sequence失败短路
- 装饰器传递running
- on_enter/on_exit精确一次
- 确定性
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional


SUCCESS = "success"
FAILURE = "failure"
RUNNING = "running"

_TERMINAL = (SUCCESS, FAILURE)


@dataclass
class Node:
    name: str
    children: List["Node"] = field(default_factory=list)
    status: str = "idle"
    running_index: int = 0
    on_enter_count: int = 0
    on_exit_count: int = 0

    def reset(self):
        self.status = "idle"
        self.running_index = 0
        for c in self.children:
            c.reset()

    def abort(self):
        """外部中断：终止运行中的子树。

        对每个已进入但未退出的节点精确触发一次on_exit，
        然后递归重置状态，保证中断后可重新tick且结果确定。
        """
        if self.status == RUNNING:
            self.on_exit_count += 1
        for child in self.children:
            child.abort()
        self.status = "idle"
        self.running_index = 0

    def _enter(self) -> None:
        self.on_enter_count += 1
        self.status = RUNNING

    def _exit(self, result: str) -> str:
        self.status = result
        self.on_exit_count += 1
        return result


class Action(Node):
    def __init__(self, name: str, fn: Callable[[], str]):
        super().__init__(name)
        self.fn = fn

    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
        result = self.fn()
        if result != RUNNING:
            return self._exit(result)
        return RUNNING


class Sequence(Node):
    """按顺序执行；失败立即短路返回，running挂起并从当前子节点继续。"""
    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
            self.running_index = 0
        while self.running_index < len(self.children):
            child = self.children[self.running_index]
            result = child.tick()
            if result == FAILURE:
                return self._exit(FAILURE)
            if result == RUNNING:
                return RUNNING
            self.running_index += 1
        return self._exit(SUCCESS)


class Selector(Node):
    """按顺序尝试；成功立即返回，running挂起并下一帧从该子节点继续。"""
    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
            self.running_index = 0
        while self.running_index < len(self.children):
            child = self.children[self.running_index]
            result = child.tick()
            if result == SUCCESS:
                return self._exit(SUCCESS)
            if result == RUNNING:
                return RUNNING
            self.running_index += 1
        return self._exit(FAILURE)


class Parallel(Node):
    """并行节点。

    - 任一子节点失败：立即终止所有仍在运行的子节点并返回failure；
    - 全部子节点成功才返回success；
    - 有子节点running时返回running，并记住已完成的子节点（不再重复tick）。
    """
    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
        all_success = True
        for child in self.children:
            if child.status in _TERMINAL:
                continue
            result = child.tick()
            if result == FAILURE:
                for other in self.children:
                    if other is not child and other.status == RUNNING:
                        other.abort()
                return self._exit(FAILURE)
            if result == RUNNING:
                all_success = False
        if all_success:
            return self._exit(SUCCESS)
        return RUNNING


class Inverter(Node):
    """反转子节点结果；running原样透传。"""
    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
        if not self.children:
            return self._exit(FAILURE)
        result = self.children[0].tick()
        if result == RUNNING:
            return RUNNING
        return self._exit(SUCCESS if result == FAILURE else FAILURE)


class Repeat(Node):
    """重复执行子节点times次；子节点失败立即返回failure，running透传。"""
    def __init__(self, name: str, children: Optional[List[Node]] = None,
                 times: int = 1):
        super().__init__(name, children or [])
        self.times = times
        self.completed = 0

    def reset(self):
        super().reset()
        self.completed = 0

    def abort(self):
        super().abort()
        self.completed = 0

    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
        if not self.children or self.times <= 0:
            return self._exit(SUCCESS)
        child = self.children[0]
        while self.completed < self.times:
            result = child.tick()
            if result == RUNNING:
                return RUNNING
            if result == FAILURE:
                return self._exit(FAILURE)
            self.completed += 1
            if self.completed < self.times:
                child.reset()
        return self._exit(SUCCESS)


class UntilFail(Node):
    """重复执行子节点直到其失败；子节点失败返回success，running透传。"""
    def tick(self) -> str:
        if self.status in _TERMINAL:
            return self.status
        if self.status == "idle":
            self._enter()
        if not self.children:
            return self._exit(SUCCESS)
        child = self.children[0]
        while True:
            result = child.tick()
            if result == RUNNING:
                return RUNNING
            if result == FAILURE:
                return self._exit(SUCCESS)
            child.reset()


class BehaviorTree:
    def __init__(self, root: Node):
        self.root = root
        self.tick_count = 0

    def tick(self) -> str:
        self.tick_count += 1
        return self.root.tick()

    def reset(self):
        self.root.reset()
        self.tick_count = 0

    def interrupt(self):
        """外部中断事件：终止运行中的节点并重置整棵树。"""
        self.root.abort()
        self.tick_count = 0

    def snapshot(self) -> dict:
        def walk(n):
            return {"name": n.name, "status": n.status,
                    "children": [walk(c) for c in n.children]}
        return {"root": walk(self.root), "ticks": self.tick_count}
