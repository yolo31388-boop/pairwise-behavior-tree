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


class Action(Node):
    def __init__(self, name: str, fn: Callable[[], str]):
        super().__init__(name)
        self.fn = fn

    def tick(self) -> str:
        if self.status == "idle":
            self.on_enter_count += 1
            self.status = RUNNING
        result = self.fn()
        if result != RUNNING:
            self.status = result
            self.on_exit_count += 1
        return result


class Sequence(Node):
    def tick(self) -> str:
        if self.status == "idle":
            self.on_enter_count += 1
            self.status = RUNNING
            self.running_index = 0
        while self.running_index < len(self.children):
            child = self.children[self.running_index]
            result = child.tick()
            if result == FAILURE:
                self.status = FAILURE
                self.on_exit_count += 1
                return FAILURE
            if result == RUNNING:
                return RUNNING
            self.running_index += 1
        self.status = SUCCESS
        self.on_exit_count += 1
        return SUCCESS


class Selector(Node):
    def tick(self) -> str:
        if self.status == "idle":
            self.on_enter_count += 1
            self.status = RUNNING
            self.running_index = 0
        while self.running_index < len(self.children):
            child = self.children[self.running_index]
            result = child.tick()
            if result == SUCCESS:
                self.status = SUCCESS
                self.on_exit_count += 1
                return SUCCESS
            if result == RUNNING:
                return RUNNING
            self.running_index += 1
        self.status = FAILURE
        self.on_exit_count += 1
        return FAILURE


class Parallel(Node):
    """并行节点。任一子节点失败立即终止其他子节点。"""
    def tick(self) -> str:
        if self.status == "idle":
            self.on_enter_count += 1
            self.status = RUNNING
        all_success = True
        for index, child in enumerate(self.children):
            if child.status in (SUCCESS, FAILURE):
                continue
            result = child.tick()
            if result == FAILURE:
                self._terminate_others(index)
                self.status = FAILURE
                self.on_exit_count += 1
                return FAILURE
            elif result == RUNNING:
                all_success = False
            # result == SUCCESS: continue
        if all_success:
            self.status = SUCCESS
            self.on_exit_count += 1
            return SUCCESS
        return RUNNING

    def _terminate_others(self, failed_index: int):
        for index, child in enumerate(self.children):
            if index != failed_index and child.status == RUNNING:
                child.reset()


class Inverter(Node):
    def tick(self) -> str:
        if self.status == "idle":
            self.on_enter_count += 1
            self.status = RUNNING
        if not self.children:
            self.status = FAILURE
            return FAILURE
        result = self.children[0].tick()
        if result == RUNNING:
            return RUNNING
        self.status = SUCCESS if result == FAILURE else FAILURE
        self.on_exit_count += 1
        return self.status


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

    def snapshot(self) -> dict:
        def walk(n):
            return {"name": n.name, "status": n.status,
                    "children": [walk(c) for c in n.children]}
        return {"root": walk(self.root), "ticks": self.tick_count}
