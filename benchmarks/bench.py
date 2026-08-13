"""
Measure what the README claims: a streaming query costs the same memory on a
large file as on a small one, and the clauses that must buffer (--sort,
--group-by) are the only ones whose memory grows with input.

Run it (from the repo root, with the package importable):
    pip install -e .          # once
    python benchmarks/bench.py
    python benchmarks/bench.py --rows 2000000
Or without installing:  PYTHONPATH=. python benchmarks/bench.py

It writes a temporary CSV, runs a handful of queries through sift's own engine
in-process, and reports throughput and peak memory measured with the stdlib
`tracemalloc`. No third-party profiler, to keep the zero-dependency promise.
"""

from __future__ import annotations

import argparse
import io
import time
import tracemalloc

from sift.io import read, write
from sift.query import Query, parse_aggregate, parse_condition, run


def make_csv(rows: int) -> str:
    """A CSV string with a numeric and two categorical columns."""
    buf = io.StringIO()
    buf.write("id,category,region,price\n")
    cats = ("book", "toy", "food", "tool")
    regions = ("north", "south", "east", "west")
    for i in range(rows):
        # Deterministic spread, no randomness, so runs are comparable.
        buf.write(f"{i},{cats[i % 4]},{regions[i % 3]},{(i * 7) % 1000}\n")
    return buf.getvalue()


def measure(label: str, csv_text: str, query: Query) -> None:
    """Run one query, report rows/sec and peak memory over the run."""
    stream = io.StringIO(csv_text)
    out = io.StringIO()

    tracemalloc.start()
    start = time.perf_counter()
    n = write(run(read(stream, "csv"), query), out, "csv")
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rate = (n or 1) / elapsed if elapsed else float("inf")
    print(
        f"  {label:<28} {n:>9,} rows out  "
        f"{elapsed:6.3f}s  {rate/1e6:5.2f}M rows/s  "
        f"peak {peak/1e6:7.2f} MB"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=500_000, help="rows in the test file")
    args = ap.parse_args()

    print(f"Building a {args.rows:,}-row CSV ...")
    csv_text = make_csv(args.rows)
    print(f"  size: {len(csv_text)/1e6:.1f} MB in memory as text\n")

    print("Streaming clauses (memory should stay flat regardless of --rows):")
    measure("--where price > 500", csv_text,
            Query(where=[parse_condition("price > 500")]))
    measure("--where + --select + --limit 10", csv_text,
            Query(where=[parse_condition("price > 500")],
                  select=["id", "price"], limit=10))

    print("\nBuffering clauses (memory grows with input, by design):")
    measure("--sort price", csv_text, Query(sort_by="price"))
    measure("--agg avg(price) -g category", csv_text,
            Query(aggregates=[parse_aggregate("avg(price)")], group_by=["category"]))

    print(
        "\nRead the two groups against each other: the streaming queries hold a\n"
        "few rows no matter how large --rows is, while --sort holds the file.\n"
        "That gap is the streaming claim, measured."
    )


if __name__ == "__main__":
    main()
