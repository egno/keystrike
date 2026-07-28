import time


class MonotonicClock:
    def now_ns(self) -> int:
        return time.monotonic_ns()

    def wall_epoch(self) -> float:
        return time.time()
