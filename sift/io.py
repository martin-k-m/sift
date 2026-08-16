"""
Reading and writing the two formats, both as streams.

CSV and JSONL are the two shapes tabular data actually arrives in, and both are
line-oriented, which is what lets everything here stay a generator. Neither
reader loads the file.
"""

from __future__ import annotations

import contextlib
import csv
import json
import sys
from collections.abc import Iterable, Iterator
from typing import IO, Any

Row = dict[str, Any]

# The stdlib default of 128 KB rejects real cells. Not sys.maxsize: the limit is
# a C long, 32-bit on Windows, and it still has to stop a runaway quote.
MAX_FIELD_SIZE = 10 * 1024 * 1024
csv.field_size_limit(MAX_FIELD_SIZE)

# Reads plain UTF-8 unchanged and strips Excel's byte order mark, which would
# otherwise fuse onto the first header name and hide that column from queries.
DEFAULT_ENCODING = "utf-8-sig"


def sniff(path: str | None, explicit: str | None) -> str:
    """Decide the format, preferring what the caller said over the extension."""
    if explicit:
        return explicit
    if path:
        low = path.lower()
        if low.endswith((".jsonl", ".ndjson")):
            return "jsonl"
        if low.endswith(".json"):
            return "json"
    return "csv"


def read(stream: IO[str], fmt: str) -> Iterator[Row]:
    if fmt == "csv":
        # DictReader gives the header as keys and skips it as a row, which is
        # the behaviour every query here assumes.
        reader = csv.DictReader(stream)
        while True:
            try:
                row = next(reader)
            except StopIteration:
                return
            except csv.Error as e:
                # _csv.Error is not a ValueError, so the CLI would let it out as
                # a traceback. line_num is the last full line, so the bad row
                # starts on the next one.
                raise ValueError(f"line {reader.line_num + 1}: {e}") from None
            yield row
    elif fmt in ("jsonl", "ndjson"):
        for n, line in enumerate(stream, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"line {n} is not valid JSON: {e.msg}") from None
            if not isinstance(obj, dict):
                raise ValueError(f"line {n} is a {type(obj).__name__}, expected an object")
            yield obj
    elif fmt == "json":
        # The one format that cannot stream: an array's shape is only known at
        # its closing bracket. Read whole, and say so in the docs.
        data = json.load(stream)
        if not isinstance(data, list):
            raise ValueError("expected a JSON array of objects")
        for i, obj in enumerate(data):
            if not isinstance(obj, dict):
                raise ValueError(f"item {i} is a {type(obj).__name__}, expected an object")
            yield obj
    else:
        raise ValueError(f"unknown format {fmt!r}")


def write(rows: Iterable[Row], out: IO[str], fmt: str) -> int:
    """Write rows, returning how many. Returns 0 without emitting a header."""
    n = 0
    if fmt in ("jsonl", "ndjson"):
        for row in rows:
            out.write(json.dumps(row, default=str) + "\n")
            n += 1
        return n

    if fmt == "json":
        buffered = list(rows)
        json.dump(buffered, out, default=str, indent=2)
        out.write("\n")
        return len(buffered)

    writer: csv.DictWriter | None = None
    for row in rows:
        if writer is None:
            # The header comes from the first row, because a projection can
            # change the columns and the input header may no longer apply.
            writer = csv.DictWriter(out, fieldnames=list(row), lineterminator="\n")
            writer.writeheader()
        writer.writerow(row)
        n += 1
    return n


def open_input(path: str | None, encoding: str = DEFAULT_ENCODING) -> IO[str]:
    if path is None or path == "-":
        # stdin arrives decoded by the platform's choice; match what a file
        # would get. A StringIO under test has nothing to reconfigure.
        with contextlib.suppress(AttributeError, ValueError, OSError):
            sys.stdin.reconfigure(encoding=encoding, newline="")  # type: ignore[union-attr]
        return sys.stdin
    # newline="" is required by csv: it does its own line-ending handling, and
    # without it a file with \r\n produces a stray \r on every last field.
    return open(path, newline="", encoding=encoding)
