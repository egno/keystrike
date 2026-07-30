import datetime as dt
import time


class MonotonicClock:
    def now_ns(self) -> int:
        return time.monotonic_ns()

    def wall_epoch(self) -> float:
        return time.time()

    def local_tzinfo(self) -> dt.tzinfo:
        return dt.datetime.now().astimezone().tzinfo or dt.UTC
