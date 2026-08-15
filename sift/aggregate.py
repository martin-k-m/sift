"""
The aggregate functions, and how a percentile is defined.

Split out of `query` because there are now enough of them that they were the
larger half of that module, and because the percentile question below deserves
to be answered somewhere a reader can find it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from typing import Any, Callable

Reducer = Callable[[Sequence[Any]], Any]


def numbers(values: Iterable[Any]) -> list[float]:
    """The numeric subset of a column, with blanks and text skipped.

    Aggregating a column that is mostly numbers should not fail because one row
    is empty or holds a label; the alternative is every user pre-cleaning their
    data before they can count it.
    """
    from .query import coerce

    out = []
    for v in values:
        n = coerce(v)
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            out.append(float(n))
    return out


def percentile(values: Sequence[Any], q: float) -> float | None:
    """The q-th percentile, 0 to 100, by linear interpolation between ranks.

    There is no single definition of a percentile, there are at least nine,
    and they disagree on small inputs. This is the one numpy, pandas and Excel's
    PERCENTILE all use by default, so a number from here matches the number a
    reader gets when they check it somewhere else. That agreement is worth more
    than any argument for a different estimator.

    The rank is (n - 1) * q / 100. A whole rank takes that element; a fractional
    one takes the two it falls between, weighted by how far along it sits. p0
    is therefore the minimum, p100 the maximum, and p50 the median.
    """
    nums = sorted(numbers(values))
    if not nums:
        return None
    if len(nums) == 1:
        return nums[0]
    rank = (len(nums) - 1) * (q / 100)
    low = int(rank)
    high = min(low + 1, len(nums) - 1)
    frac = rank - low
    return nums[low] * (1 - frac) + nums[high] * frac


def _distinct(values: Sequence[Any]) -> int:
    """How many different values a column holds.

    Counts the raw text rather than the coerced value, because two spellings of
    the same number are two spellings, a column holding `1` and `1.0` has two
    distinct entries in the file, and collapsing them would be a claim about the
    data that this tool is not in a position to make. Unhashable values fall
    back to their text, which is the only thing a set can hold.
    """
    seen = set()
    for v in values:
        try:
            seen.add(v)
        except TypeError:
            seen.add(str(v))
    return len(seen)


NAMED: dict[str, Reducer] = {
    "count": len,
    "sum": lambda v: sum(numbers(v)),
    "min": lambda v: min(numbers(v), default=None),
    "max": lambda v: max(numbers(v), default=None),
    "avg": lambda v: (lambda n: sum(n) / len(n) if n else None)(numbers(v)),
    "median": lambda v: percentile(v, 50),
    "distinct": _distinct,
}

# `p95`, `p99`, `p1`, any percentile, rather than a fixed handful. Written as
# a pattern because the useful ones differ by field: p95 for a latency, p1 for
# a floor, and nobody wants to file a bug to get p97.
PERCENTILE_NAME = re.compile(r"p(\d{1,3}(?:\.\d+)?)$")


def resolve(name: str) -> Reducer | None:
    """The reducer for a function name, or None if there is no such function."""
    if name in NAMED:
        return NAMED[name]
    m = PERCENTILE_NAME.fullmatch(name)
    if m:
        q = float(m.group(1))
        if q > 100:
            return None
        return lambda v, q=q: percentile(v, q)
    return None


def names() -> str:
    """The function list, for an error message."""
    return ", ".join(NAMED) + ", pN (any percentile, e.g. p95)"
