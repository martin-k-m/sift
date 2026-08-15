"""
The query language, and the engine that runs it.

Deliberately not SQL. SQL over a single file needs a parser, a planner and a
type system to be worth the name, and anything less is a dialect that lies
about what it accepts. This is a pipeline of named clauses instead, `where`,
`select`, `sort`, `limit`, and one aggregation form, which is small enough to
specify completely on one screen and to implement without a parser generator.

Everything streams. A row is read, tested, projected and written before the
next is read, so a file larger than memory costs the same as a small one. The
two clauses that cannot stream, `sort` and the aggregations, say so by
buffering, and they are the only places memory grows with input size.
"""

from __future__ import annotations

import heapq
import operator
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Callable

from . import aggregate

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
    # `!~` before `~`, so `a !~ b` is read as "does not match", not as `~` with
    # a stray `!` left on the column name.
    "!~": lambda a, b: re.search(str(b), str(a)) is None,
    "~": lambda a, b: re.search(str(b), str(a)) is not None,
}
REGEX_OPS = ("~", "!~")

class QueryError(ValueError):
    """A query that cannot be understood, phrased for the person who typed it."""


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


def sort_key(value: Any) -> tuple[int, Any, str]:
    """A total order over one column's values that can never raise.

    No single Python type compares `9`, `10` and `n/a`, so rank the kinds first:
    numbers, then text, then missing. Ranks never mix, so the remaining slots are
    only ever compared against a value of the same kind.
    """
    if value is None:
        return (2, 0.0, "")
    v = coerce(value)
    # Kept as an int, so a 19-digit id is not rounded by a trip through float.
    if isinstance(v, (int, float)):
        return (0, v, "")
    return (1, 0.0, str(v))


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
            # is simply false, mixed columns are normal and should filter, not
            # crash the run.
            return False


@dataclass
class Query:
    select: list[str] | None = None
    where: list[Condition] = field(default_factory=list)
    sort_by: str | None = None
    descending: bool = False
    limit: int | None = None
    # Several aggregates are computed in one pass rather than one per run,
    # because `count()` and `avg(price)` of the same file is the ordinary ask
    # and piping the file twice to get both is not an answer.
    aggregates: list[tuple[str, str]] = field(default_factory=list)  # (function, column)
    group_by: list[str] = field(default_factory=list)


def parse_condition(text: str) -> Condition:
    for op in COMPARATORS:  # dict order: longest operators first
        if op in text:
            col, _, raw = text.partition(op)
            col, raw = col.strip(), raw.strip()
            if not col:
                raise QueryError(f"missing column name in {text!r}")
            # `~` and `!~` are regex matches and their operand is always a
            # pattern, never a number, so they skip coercion.
            return Condition(col, op, raw if op in REGEX_OPS else coerce(raw))
    raise QueryError(
        f"no comparison in {text!r}; expected one of {', '.join(COMPARATORS)}"
    )


def parse_aggregate(text: str) -> tuple[str, str]:
    # The name allows a dot so a fractional percentile like `p99.9` reaches
    # `resolve`; `resolve` still rejects anything that is not a real function.
    m = re.fullmatch(r"\s*([\w.]+)\s*\(\s*([^)]*)\s*\)\s*", text)
    if not m:
        raise QueryError(f"expected something like sum(price), got {text!r}")
    fn, col = m.group(1).lower(), m.group(2).strip()
    if aggregate.resolve(fn) is None:
        raise QueryError(f"unknown function {fn!r}; have {aggregate.names()}")
    if fn != "count" and not col:
        raise QueryError(f"{fn}() needs a column")
    return fn, col or "*"


def run(rows: Iterable[Row], q: Query) -> Iterator[Row]:
    """Apply a query to a stream of rows."""
    out: Iterable[Row] = rows

    if q.where:
        out = (r for r in out if all(c.test(r) for c in q.where))

    if q.aggregates:
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

        def row_key(r: Row) -> tuple[int, Any, str]:
            try:
                return sort_key(r[key])
            except KeyError:
                raise QueryError(f"cannot sort on {key!r}: no such column") from None

        if q.limit is not None:
            # A bounded heap of N rows instead of the file. nsmallest/nlargest
            # are documented as equivalent to sorting and slicing, ties
            # included, so the output matches the full sort. See
            # benchmarks/RESULTS.md.
            pick = heapq.nlargest if q.descending else heapq.nsmallest
            out = pick(q.limit, out, key=row_key)
        else:
            # Buffers, unavoidably: the last row read can be the first row out.
            out = sorted(out, key=row_key, reverse=q.descending)
    elif q.limit is not None:
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
    """Compute every requested aggregate, grouped or not, in a single pass.

    Rows are buffered rather than per-aggregate value lists, because several
    aggregates over different columns would otherwise need one list each and
    the row is the thing they all read from. Grouped, this is bounded by the
    key cardinality; ungrouped it holds the input, which is the same cost the
    single-aggregate version paid.
    """
    labels = [f"{fn}({col})" for fn, col in q.aggregates]

    def summarize(bucket: list[Row]) -> Row:
        out: Row = {}
        for (fn, col), label in zip(q.aggregates, labels):
            reducer = aggregate.resolve(fn)
            assert reducer is not None  # parse_aggregate rejected unknown names
            # `count()` counts rows; everything else reads one column.
            values = bucket if col == "*" else [r.get(col) for r in bucket]
            out[label] = reducer(values)
        return out

    if not q.group_by:
        yield summarize(list(rows))
        return

    buckets: dict[tuple[Any, ...], list[Row]] = {}
    for r in rows:
        missing = [g for g in q.group_by if g not in r]
        if missing:
            raise QueryError(f"cannot group on {missing[0]!r}: no such column")
        buckets.setdefault(tuple(r[g] for g in q.group_by), []).append(r)

    for key, bucket in buckets.items():
        row: Row = dict(zip(q.group_by, key))
        row.update(summarize(bucket))
        yield row
