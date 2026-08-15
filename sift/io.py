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

# The default of 128 KB is a guard against a runaway quote eating a whole file,
# not a statement about legitimate data, and a single embedded document or
# base64 blob in one cell passes it easily. Raised to 10 MB, which is past any
# cell a person meant to write and still far short of letting one bad quote
# swallow a large file. Not `sys.maxsize`: the limit is stored as a C long,
# 32-bit on Windows, and a limit that admits everything is not a limit.
MAX_FIELD_SIZE = 10 * 1024 * 1024
csv.field_size_limit(MAX_FIELD_SIZE)

# `utf-8-sig` reads plain UTF-8 unchanged and additionally strips the byte order
# mark that Excel writes on every CSV it exports. Without it the mark lands on
# the front of the first header name, so `--where "name = x"` on an
# Excel-exported file reports that there is no column `name` while showing what
# looks like exactly that column back to the user.
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
                # `_csv.Error` is not a ValueError, so without this it escapes
                # the CLI's handlers as a traceback. The line number is what
                # makes the message actionable on a 2 GB file. `line_num` is
                # the last line read in full, so the bad row starts on the next
                # one; a quoted field spanning lines can run on from there.
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
        # stdin arrives already decoded, with whatever the platform chose. Ask
        # for the same encoding a file would get so `sift f.csv` and
        # `cat f.csv | sift` do not disagree about what the bytes mean.
        # A StringIO under test, or a stream already consumed, has nothing to
        # reconfigure. Reading it as it stands is the right fallback.
        with contextlib.suppress(AttributeError, ValueError, OSError):
            sys.stdin.reconfigure(encoding=encoding, newline="")  # type: ignore[union-attr]
        return sys.stdin
    # newline="" is required by csv: it does its own line-ending handling, and
    # without it a file with \r\n produces a stray \r on every last field.
    return open(path, newline="", encoding=encoding)
