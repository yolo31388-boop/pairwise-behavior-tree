# pairwise-behavior-tree

Boss 行为树的 selector 每次都重新选中已经 running 的子节点，导致同一个攻击被重复触发；parallel 节点在所有子节点成功后还在 tick，blackboard 的 key 在回滚后没有恢复；sequence 在子节点 running 时继续 tick 后面的节点，冷却按真实时间而不是 tick 计时；inverter 对 running 的处理不对；多个 Boss 共享同一个 blackboard scope，仇恨目标互相污染。ai/behavior_tree.py 是核心，tests/test_behavior_tree.py 15个红。要修的是：selector 记住 running 子节点并优先返回它；sequence 遇到 failure 立即停止、遇到 running 不 tick 后续节点；parallel 按 require_all 聚合；blackboard 按 scope 隔离；cooldown 按 tick 递减；inverter 只翻转 success/failure；reset 清理运行态。

## 运行

```bash
python -m pytest tests -q
```

初始状态：15 个用例失败。修复实现使全部用例通过，不要修改 `tests/` 下的测试。
