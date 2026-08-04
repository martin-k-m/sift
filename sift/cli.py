"""The command line."""

from __future__ import annotations

import argparse
import sys

from . import __version__, io as sift_io
from .query import Query, QueryError, parse_aggregate, parse_condition, run

EXAMPLES = """\
examples:
  sift data.csv --where "price > 100" --select name,price --sort price --desc
  sift data.csv --agg "avg(price)" --agg "count()" --group-by category,region
  sift latency.csv --agg "p95(ms)" --agg "median(ms)" --group-by endpoint
  sift events.jsonl --where 'level == error' --limit 20 --to json
  cat data.csv | sift --where "name ~ ^A" --select name

comparisons:
  =  ==  !=  >  <  >=  <=      and  ~  for a regular expression match

aggregates:
  count()  sum  min  max  avg  median  distinct  and  pN  for any percentile
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sift",
        description="Query CSV and JSONL from the terminal. Streaming, no dependencies.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("file", nargs="?", help="input file; omit or use - for stdin")
    p.add_argument("--select", "-s", metavar="COLS", help="comma-separated columns to keep")
    p.add_argument("--where", "-w", action="append", default=[], metavar="COND",
                   help="filter, repeatable; all must hold")
    p.add_argument("--sort", metavar="COL", help="sort by a column")
    p.add_argument("--desc", action="store_true", help="sort descending")
    p.add_argument("--limit", "-n", type=int, metavar="N", help="stop after N rows")
    p.add_argument("--agg", "-a", action="append", default=[], metavar="EXPR",
                   help="count(), sum/min/max/avg/median/distinct(col), pN(col); repeatable")
    p.add_argument("--group-by", "-g", metavar="COLS",
                   help="group the aggregates by one or more comma-separated columns")
    p.add_argument("--from", dest="from_fmt", choices=["csv", "jsonl", "ndjson", "json"],
                   help="input format; inferred from the extension otherwise")
    p.add_argument("--to", dest="to_fmt", choices=["csv", "jsonl", "ndjson", "json"],
                   default="csv", help="output format (default: csv)")
    p.add_argument("--version", action="version", version=f"sift {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        q = Query(
            select=[c.strip() for c in args.select.split(",")] if args.select else None,
            where=[parse_condition(w) for w in args.where],
            sort_by=args.sort,
            descending=args.desc,
            limit=args.limit,
            aggregates=[parse_aggregate(a) for a in args.agg],
            group_by=[c.strip() for c in args.group_by.split(",")] if args.group_by else [],
        )
    except QueryError as e:
        print(f"sift: {e}", file=sys.stderr)
        return 2

    if args.group_by and not args.agg:
        print("sift: --group-by needs --agg, otherwise there is nothing to group",
              file=sys.stderr)
        return 2

    fmt = sift_io.sniff(args.file, args.from_fmt)

    try:
        stream = sift_io.open_input(args.file)
    except OSError as e:
        print(f"sift: {e.strerror}: {args.file}", file=sys.stderr)
        return 1

    try:
        rows = sift_io.read(stream, fmt)
        sift_io.write(run(rows, q), sys.stdout, args.to_fmt)
    except QueryError as e:
        print(f"sift: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(f"sift: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        # `sift big.csv | head` closes the pipe early. That is the pipeline
        # working, not a failure, so exit quietly.
        return 0
    except KeyboardInterrupt:
        return 130
    finally:
        if stream is not sys.stdin:
            stream.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
