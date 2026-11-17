"""Boss behavior tree.

Tick-based, synchronous behavior tree.

Semantics:
- Blackboard: per-scope namespaces, missing keys return a caller default.
- Selector: children are visited in priority order; the child that returns
  RUNNING is remembered and short-circuits later ticks until reset(), so a
  running attack is never re-triggered.
- Sequence: stops immediately on FAILURE; a RUNNING child blocks every later
  child and is remembered for resumption.
- Parallel: every child is ticked once per tick; the result is converged
  according to the success policy (require_all) and a configurable failure
  policy. Once a terminal status is reached it is cached, so children are not
  ticked again after the node has converged.
- Cooldown: counted in ticks, not wall-clock time, so pausing the game (no
  ticks) freezes the cooldown.
- Inverter: only flips SUCCESS/FAILURE; RUNNING passes through.
- reset()/interrupt(): clear all runtime state recursively; interrupt() also
  cancels coroutines registered via register_task() (e.g. skills in flight
  when the Boss switches phase).
"""

SUCCESS = "success"
FAILURE = "failure"
RUNNING = "running"

# Parallel failure policies.
FAIL_ON_ONE = "fail_on_any"   # any child failing fails the whole node
FAIL_ON_ALL = "fail_on_all"   # the node fails only when every child failed


class Blackboard:
    """Scoped key/value store.

    Each ``scope`` is an independent namespace, so different AIs never
    overwrite each other's data even when they use the same key name.
    """

    def __init__(self):
        self._scopes = {}

    def set(self, scope, key, value):
        self._scopes.setdefault(scope, {})[key] = value
        return value

    def get(self, scope, key, default=None):
        return self._scopes.get(scope, {}).get(key, default)

    def clear(self, scope=None):
        """Drop one scope, or every scope when ``scope`` is None."""
        if scope is None:
            self._scopes.clear()
        else:
            self._scopes.pop(scope, None)


class Node:
    """Base class: runtime-state cleanup and coroutine interruption."""

    priority = 0

    def __init__(self):
        # asyncio.Task (or any object with cancel()) owned by this node.
        self._tasks = set()

    def tick(self, board):
        raise NotImplementedError

    def register_task(self, task):
        """Track a running coroutine so interrupt() can cancel it."""
        self._tasks.add(task)
        return task

    def reset(self):
        """Clear this node's runtime state and propagate to the subtree."""
        self._reset_state()
        for child in self._children():
            child.reset()

    def interrupt(self):
        """Cancel tracked coroutines, then reset the whole subtree."""
        for task in list(self._tasks):
            cancel = getattr(task, "cancel", None)
            if callable(cancel):
                cancel()
        self._tasks.clear()
        self._reset_state()
        for child in self._children():
            child.interrupt()

    def _children(self):
        return ()

    def _reset_state(self):
        pass


class Leaf(Node):
    def __init__(self, status, priority=0):
        super().__init__()
        self.status = status
        self.priority = priority
        self.ticks = 0

    def tick(self, board):
        self.ticks += 1
        return self.status


class Selector(Node):
    """Pick the first child that succeeds; remember the running one.

    Children are ordered by their ``priority`` attribute (higher first).
    The sort is stable, so children without an explicit priority keep their
    declaration order. While a child is RUNNING it is recorded in
    ``running_index`` and subsequent ticks return RUNNING directly instead of
    re-selecting (and re-triggering) it.
    """

    def __init__(self, children, remember=True):
        super().__init__()
        self.remember = remember
        self.children = sorted(
            children,
            key=lambda child: getattr(child, "priority", 0),
            reverse=True,
        )
        self.running_index = None

    def tick(self, board):
        if self.remember and self.running_index is not None:
            # Resumable active-node stack: hand control straight back to the
            # already running child without ticking anyone.
            return RUNNING

        for index, child in enumerate(self.children):
            status = child.tick(board)
            if status == RUNNING:
                if self.remember:
                    self.running_index = index
                return RUNNING
            if status == SUCCESS:
                return SUCCESS
            # FAILURE: try the next child in priority order.
        return FAILURE

    def _reset_state(self):
        self.running_index = None

    def _children(self):
        return self.children


class Sequence(Node):
    """Run children in order; FAILURE stops immediately, RUNNING is remembered."""

    def __init__(self, children):
        super().__init__()
        self.children = list(children)
        self.running_index = None

    def tick(self, board):
        if self.running_index is not None:
            return RUNNING

        for index, child in enumerate(self.children):
            status = child.tick(board)
            if status == RUNNING:
                self.running_index = index
                return RUNNING
            if status == FAILURE:
                return FAILURE
        return SUCCESS

    def _reset_state(self):
        self.running_index = None

    def _children(self):
        return self.children


class Parallel(Node):
    """Tick every child once per tick and converge by policy.

    Success policy: ``require_all=True`` needs every child to succeed;
    ``require_all=False`` succeeds as soon as one child succeeds.
    Failure policy is configurable via ``failure_policy`` (FAIL_ON_ONE /
    FAIL_ON_ALL) and defaults to FAIL_ON_ONE for require_all=True,
    FAIL_ON_ALL otherwise. The converged terminal status is cached, so once
    the node succeeds or fails it stops ticking its children until reset().
    """

    def __init__(self, children, require_all=True, failure_policy=None):
        super().__init__()
        self.children = list(children)
        self.require_all = require_all
        if failure_policy is None:
            failure_policy = FAIL_ON_ONE if require_all else FAIL_ON_ALL
        self.failure_policy = failure_policy
        self.converged = None

    def tick(self, board):
        if self.converged is not None:
            return self.converged

        results = [child.tick(board) for child in self.children]
        successes = results.count(SUCCESS)
        failures = results.count(FAILURE)

        if self.require_all:
            succeeded = successes == len(results)
        else:
            succeeded = successes >= 1
        if succeeded:
            self.converged = SUCCESS
            return SUCCESS

        if self.failure_policy == FAIL_ON_ONE:
            failed = failures >= 1
        else:
            failed = failures == len(results)
        if failed:
            self.converged = FAILURE
            return FAILURE

        return RUNNING

    def _reset_state(self):
        self.converged = None

    def _children(self):
        return self.children


class Cooldown(Node):
    """Gate the child by a cooldown measured in ticks.

    With ``ticks=N`` the child may run at most once every N ticks: the first
    N-1 ticks after arming (and after each firing) return FAILURE without
    touching the child. Because the counter only moves on tick(), opening a
    pause menu freezes the cooldown instead of letting real time drain it.
    """

    def __init__(self, child, ticks):
        super().__init__()
        self.child = child
        self.ticks = ticks
        self.remaining = self._gate_ticks()

    def _gate_ticks(self):
        return max(0, self.ticks - 1)

    def tick(self, board):
        if self.remaining > 0:
            self.remaining -= 1
            return FAILURE

        status = self.child.tick(board)
        self.remaining = self._gate_ticks()
        return status

    def _reset_state(self):
        self.remaining = self._gate_ticks()

    def _children(self):
        return (self.child,)


class Inverter(Node):
    """Flip SUCCESS/FAILURE only; RUNNING is passed through unchanged."""

    def __init__(self, child):
        super().__init__()
        self.child = child

    def tick(self, board):
        status = self.child.tick(board)
        if status == SUCCESS:
            return FAILURE
        if status == FAILURE:
            return SUCCESS
        return RUNNING

    def _children(self):
        return (self.child,)
