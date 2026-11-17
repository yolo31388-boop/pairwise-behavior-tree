"""Boss behavior tree (starter code with known defects)."""

SUCCESS = "success"
FAILURE = "failure"
RUNNING = "running"


class Blackboard:
    def set(self, scope, key, value):
        return None

    def get(self, scope, key, default=None):
        return default


class Leaf:
    def __init__(self, status):
        self.status = status
        self.ticks = 0

    def tick(self, board):
        self.ticks += 1
        return self.status


class Selector:
    def __init__(self, children, remember=True):
        self.children = list(children)
        self.remember = remember

    def tick(self, board):
        return FAILURE

    def reset(self):
        return None


class Sequence:
    def __init__(self, children):
        self.children = list(children)

    def tick(self, board):
        return FAILURE

    def reset(self):
        return None


class Parallel:
    def __init__(self, children, require_all=True):
        self.children = list(children)
        self.require_all = require_all

    def tick(self, board):
        return FAILURE


class Cooldown:
    def __init__(self, child, ticks):
        self.child = child
        self.ticks = ticks
        self.remaining = 0

    def tick(self, board):
        return FAILURE


class Inverter:
    def __init__(self, child):
        self.child = child

    def tick(self, board):
        return FAILURE
