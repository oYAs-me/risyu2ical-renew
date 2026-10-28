from __future__ import annotations

from collections.abc import Iterable


def group_consecutive_periods(periods: Iterable[int]) -> list[tuple[int, int]]:
    """Return inclusive (first, last) ranges for consecutive periods."""
    ordered = sorted(set(periods))
    if not ordered:
        return []
    groups: list[tuple[int, int]] = []
    start = previous = ordered[0]
    for period in ordered[1:]:
        if period != previous + 1:
            groups.append((start, previous))
            start = period
        previous = period
    groups.append((start, previous))
    return groups
