"""Differential test: sift against SQLite, which is the oracle this suite was
missing.

The rest of the suite is 63 examples someone wrote down, which can only find the
mistakes that person thought of. This generates random CSVs and random queries,
asks SQLite the same question, and compares the rows.

Two things stay out of the comparison because sift models them differently on
purpose rather than by mistake:

- Blank fields, which sift reads as missing and skips in aggregates while
  still comparing them as text in --where. Generated data has no blanks.
- Mixed columns, since sift decides numerically or lexically per value. Each
  generated column is all numbers or all text.
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
import subprocess
import sys

NAMES = ["ana", "bo", "cy", "dee", "eli", "fay"]
REGIONS = ["north", "south", "east"]
COLS = ["name", "region", "age", "score"]
TYPES = {"name": "TEXT", "region": "TEXT", "age": "INTEGER", "score": "REAL"}

TRIALS = 200
SEED_BASE = 7000


def _rows(rng, n):
    return [
        {
            "name": rng.choice(NAMES),
            "region": rng.choice(REGIONS),
            "age": rng.randint(1, 90),
            "score": round(rng.uniform(0, 100), 2),
        }
        for _ in range(n)
    ]


def _canon(v):
    if isinstance(v, bool):
        return str(int(v))
    s = str(v)
    try:
        f = float(s)
    except ValueError:
        return s
    return str(int(f)) if f.is_integer() else f"{f:.9g}"


def _multiset(rows):
    # No --sort is generated, so row order carries no meaning here and a
    # multiset avoids failing on a tie the two engines break differently.
    return sorted(tuple(_canon(v) for v in row) for row in rows)


def _case(rng):
    """Return (sift args, sql, columns the answer has, in order)."""
    column = rng.choice(["age", "score"])
    op = rng.choice([">", ">=", "<", "<=", "==", "!="])
    literal = rng.randint(1, 90) if column == "age" else round(rng.uniform(0, 100), 2)
    sql_op = "=" if op == "==" else op
    where = f"{column} {op} {literal}"
    sql_where = f"WHERE {column} {sql_op} {literal}"

    if rng.random() < 0.45:
        group = rng.choice(["name", "region"])
        func, arg = rng.choice(
            [
                ("count", "()"),
                ("sum", "(age)"),
                ("avg", "(age)"),
                ("min", "(age)"),
                ("max", "(age)"),
            ]
        )
        agg = f"{func}{arg}"
        sql_agg = "COUNT(*)" if func == "count" else f"{func.upper()}(age)"
        args = ["--where", where, "--agg", agg, "--group-by", group]
        out_name = "count(*)" if func == "count" else agg
        sql = f"SELECT {group}, {sql_agg} FROM t {sql_where} GROUP BY {group}"
        return args, sql, [group, out_name]

    picked = rng.sample(COLS, k=rng.randint(1, len(COLS)))
    args = ["--where", where, "--select", ",".join(picked)]
    sql = f"SELECT {', '.join(picked)} FROM t {sql_where}"
    return args, sql, picked


def test_sift_agrees_with_sqlite(tmp_path):
    compared = 0
    for trial in range(TRIALS):
        rng = random.Random(SEED_BASE + trial)
        rows = _rows(rng, rng.randint(1, 25))
        path = tmp_path / f"t{trial}.csv"
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLS)
            w.writeheader()
            w.writerows(rows)

        db = sqlite3.connect(":memory:")
        spec = ", ".join(f"{c} {TYPES[c]}" for c in COLS)
        db.execute(f"CREATE TABLE t ({spec})")
        db.executemany(
            "INSERT INTO t VALUES (?, ?, ?, ?)", [tuple(r[c] for c in COLS) for r in rows]
        )

        args, sql, out_cols = _case(rng)
        run = subprocess.run(
            [sys.executable, "-m", "sift", str(path), *args, "--to", "json"],
            capture_output=True,
            text=True,
        )
        assert run.returncode == 0, f"sift failed: {run.stderr}\nargs: {args}"
        got = _multiset([[r[c] for c in out_cols] for r in json.loads(run.stdout or "[]")])
        want = _multiset(db.execute(sql).fetchall())
        compared += 1
        assert got == want, (
            f"seed {SEED_BASE + trial}\nargs: {args}\nsql: {sql}\nsift: {got}\nsqlite: {want}"
        )

    # A generator that stopped producing cases would leave every assertion above
    # unreached and this test still green.
    assert compared == TRIALS
