"""PythonCodeGenerator: a small bundled corpus of original Python snippets for
Mode.CODE practice.

Snippets are flattened to a single line (indentation stripped, lines joined
by a single space) — code mode reuses the same space-separated typing UI as
free/adaptive text rather than adding multi-line/Enter-key handling, which
would be a much larger change than this milestone's scope (see PLAN.md M4).
"""

from __future__ import annotations

_SNIPPETS: tuple[str, ...] = (
    """
def fibonacci(n):
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
""",
    """
def is_prime(n):
    if n < 2:
        return False
    for i in range(2, int(n ** 0.5) + 1):
        if n % i == 0:
            return False
    return True
""",
    """
def binary_search(items, target):
    low, high = 0, len(items) - 1
    while low <= high:
        mid = (low + high) // 2
        if items[mid] == target:
            return mid
        if items[mid] < target:
            low = mid + 1
        else:
            high = mid - 1
    return -1
""",
    """
class Stack:
    def __init__(self):
        self._items = []

    def push(self, value):
        self._items.append(value)

    def pop(self):
        return self._items.pop()
""",
    """
def word_frequencies(text):
    counts = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    return counts
""",
    """
squares = [n * n for n in range(10) if n % 2 == 0]
total = sum(squares)
print(f"total: {total}")
""",
    """
def merge_sorted(left, right):
    result = []
    i = j = 0
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1
    result.extend(left[i:])
    result.extend(right[j:])
    return result
""",
    """
from dataclasses import dataclass

@dataclass
class Point:
    x: float
    y: float

    def distance_to(self, other):
        return ((self.x - other.x) ** 2 + (self.y - other.y) ** 2) ** 0.5
""",
    """
def read_lines(path):
    with open(path, encoding="utf-8") as handle:
        return [line.strip() for line in handle if line.strip()]
""",
    """
def retry(times=3):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for attempt in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if attempt == times - 1:
                        raise
        return wrapper
    return decorator
""",
)


def _flatten(snippet: str) -> str:
    lines = [line.strip() for line in snippet.splitlines() if line.strip()]
    return " ".join(lines)


class PythonCodeGenerator:
    def __init__(self) -> None:
        self._flattened = tuple(_flatten(snippet) for snippet in _SNIPPETS)

    def snippets(self) -> tuple[str, ...]:
        return self._flattened
