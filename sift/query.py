"""
The query language, and the engine that runs it.

Deliberately not SQL. SQL over a single file needs a parser, a planner and a
type system to be worth the name, and anything less is a dialect that lies
about what it accepts. This is a pipeline of named clauses instead — `where`,
`select`, `sort`, `limit`, and one aggregation form — which is small enough to
specify completely on one screen and to implement without a parser generator.

Everything streams. A row is read, tested, projected and written before the
next is read, so a file larger than memory costs the same as a small one. The
two clauses that cannot stream, `sort` and the aggregations, say so by
buffering, and they are the only places memory grows with input size.
"""

from __future__ import annotations

import operator
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Iterator, Sequence

Row = dict[str, Any]

# Longest first, so `>=` is never read as `>` followed by a stray `=`.
COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    ">=": operator.ge,
    "<=": operator.le,
    "!=": operator.ne,
    "==": operator.eq,
    "=": operator.eq,
    ">": operator.gt,
    "<": operator.lt,
    "~": lambda a, b: re.search(str(b), str(a)) is not None,
}

AGGREGATES: dict[str, Callable[[Sequence[Any]], Any]] = {
    "count": len,
    "sum": lambda v: sum(_numbers(v)),
    "min": lambda v: min(_numbers(v), default=None),
    "max": lambda v: max(_numbers(v), default=None),
    "avg": lambda v: (lambda n: sum(n) / len(n) if n else None)(_numbers(v)),
}


class QueryError(ValueError):
    """A query that cannot be understood, phrased for the person who typed it."""


def _numbers(values: Iterable[Any]) -> list[float]:
    """The numeric subset of a column, with blanks and text skipped.

    Aggregating a column that is mostly numbers should not fail because one row
    is empty or holds a label; the alternative is every user pre-cleaning their
    data before they can count it.
    """
    out = []
    for v in values:
        n = coerce(v)
        if isinstance(n, (int, float)) and not isinstance(n, bool):
            out.append(float(n))
    return out


def coerce(value: Any) -> Any:
    """Read a CSV field as a number when it plainly is one.

    CSV has no types, so the alternative is comparing "9" to "10" as strings and
    getting the wrong answer. Leading zeros are left alone: `007` is an
    identifier far more often than it is seven, and turning it into 7 loses the
    thing that made it a key.
    """
    if not isinstance(value, str):
        return value
    s = value.strip()
    if not s:
        return s
    if len(s) > 1 and s[0] == "0" and s[1].isdigit():
        return value
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        return value


@dataclass
class Condition:
    column: str
    op: str
    value: Any

    def test(self, row: Row) -> bool:
        if self.column not in row:
            raise QueryError(f"no column {self.column!r}; found {', '.join(row) or 'none'}")
        left = coerce(row[self.column])
        right = self.value
        fn = COMPARATORS[self.op]
        try:
            return fn(left, right)
        except TypeError:
            # A numeric comparison against text is not an error in the data, it
            # is simply false — mixed columns are normal and should filter, not
            # crash the run.
            return False


@dataclass
class Query:
    select: list[str] | None = None
    where: list[Condition] = field(default_factory=list)
    sort_by: str | None = None
    descending: bool = False
    limit: int | None = None
    aggregate: tuple[str, str] | None = None  # (function, column)
    group_by: str | None = None


def parse_condition(text: str) -> Condition:
    for op in COMPARATORS:  # dict order: longest operators first
        if op in text:
            col, _, raw = text.partition(op)
            col, raw = col.strip(), raw.strip()
            if not col:
                raise QueryError(f"missing column name in {text!r}")
            # `~` is a regex match and its operand is always a pattern, never a
            # number, so it is the one comparator that skips coercion.
            return Condition(col, op, raw if op == "~" else coerce(raw))
    raise QueryError(
        f"no comparison in {text!r}; expected one of {', '.join(COMPARATORS)}"
    )


def parse_aggregate(text: str) -> tuple[str, str]:
    m = re.fullmatch(r"\s*(\w+)\s*\(\s*([^)]*)\s*\)\s*", text)
    if not m:
        raise QueryError(f"expected something like sum(price), got {text!r}")
    fn, col = m.group(1).lower(), m.group(2).strip()
    if fn not in AGGREGATES:
        raise QueryError(f"unknown function {fn!r}; have {', '.join(AGGREGATES)}")
    if fn != "count" and not col:
        raise QueryError(f"{fn}() needs a column")
    return fn, col or "*"


def run(rows: Iterable[Row], q: Query) -> Iterator[Row]:
    """Apply a query to a stream of rows."""
    out: Iterable[Row] = rows

    if q.where:
        out = (r for r in out if all(c.test(r) for c in q.where))

    if q.aggregate:
        yield from _aggregate(out, q)
        return

    if q.select:
        cols = q.select

        def project(r: Row) -> Row:
            missing = [c for c in cols if c not in r]
            if missing:
                raise QueryError(
                    f"no column {missing[0]!r}; found {', '.join(r) or 'none'}"
                )
            return {c: r[c] for c in cols}

        out = (project(r) for r in out)

    if q.sort_by:
        key = q.sort_by
        # Buffers, unavoidably: the last row read can be the first row out.
        # Sorting on the coerced value so 9 lands before 10.
        try:
            out = sorted(out, key=lambda r: (r[key] is None, coerce(r[key])), reverse=q.descending)
        except KeyError:
            raise QueryError(f"cannot sort on {key!r}: no such column") from None
        except TypeError:
            # Mixed types in one column have no total order. Comparing as text
            # is at least deterministic, and the alternative is refusing to run.
            out = sorted(out, key=lambda r: str(r[key]), reverse=q.descending)

    if q.limit is not None:
        out = _take(out, q.limit)

    yield from out


def _take(rows: Iterable[Row], n: int) -> Iterator[Row]:
    if n <= 0:
        return
    for i, row in enumerate(rows):
        yield row
        if i + 1 >= n:
            return


def _aggregate(rows: Iterable[Row], q: Query) -> Iterator[Row]:
    fn_name, col = q.aggregate  # type: ignore[misc]
    fn = AGGREGATES[fn_name]
    label = f"{fn_name}({col})"

    if not q.group_by:
        values = [r.get(col) for r in rows] if col != "*" else list(rows)
        yield {label: fn(values)}
        return

    # Grouping buffers one bucket per distinct key, not the whole input, so it
    # is bounded by cardinality rather than by row count.
    buckets: dict[Any, list[Any]] = {}
    for r in rows:
        if q.group_by not in r:
            raise QueryError(f"cannot group on {q.group_by!r}: no such column")
        buckets.setdefault(r[q.group_by], []).append(r if col == "*" else r.get(col))

    for key, values in buckets.items():
        yield {q.group_by: key, label: fn(values)}
