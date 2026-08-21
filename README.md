# sift

[![CI](https://github.com/martin-k-m/sift/actions/workflows/ci.yml/badge.svg)](https://github.com/martin-k-m/sift/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Query CSV and JSONL from the terminal. Streaming, zero dependencies, pure stdlib.

Not on PyPI yet. Install from the repository:

```bash
pip install git+https://github.com/martin-k-m/sift
```

The distribution will be `sift-query` when it is published, because `sift` is
taken. The command, the import and the repository stay `sift`; only the string
after `pip install` will differ.

```bash
sift sales.csv --where "price > 100" --select name,price --sort price --desc
sift sales.csv --agg "avg(price)" --agg "count()" --group-by category,region
sift latency.csv --agg "p95(ms)" --agg "median(ms)" --group-by endpoint
sift events.jsonl --where 'level == error' --limit 20 --to json
cat sales.csv | sift --where "name ~ ^A" --select name
```

## Why not SQL

SQL over a single file needs a parser, a planner and a type system to deserve
the name. Anything less is a dialect that lies about what it accepts, you type
a `JOIN` or a window function, and it fails somewhere unhelpful.

`sift` is a pipeline of named clauses instead. There are five, they are listed
below in full, and there is nothing else to discover.

| Clause | Does |
| --- | --- |
| `--where` | keep rows matching a comparison; repeat for AND |
| `--select` | keep and order columns |
| `--sort` / `--desc` | order by a column |
| `--limit` | stop after N rows; with `--sort`, keep the top N without holding the file |
| `--agg` / `--group-by` | `count()`, `sum`, `min`, `max`, `avg`, `median`, `distinct`, `pN`; repeat `--agg` for several at once |

Comparisons: `=` `==` `!=` `>` `<` `>=` `<=`, and `~` for a regular expression
match, `!~` for one that does not match.

## Percentiles

`pN(col)` takes any percentile, so `p95`, `p99` and `p1` all work rather than a
fixed handful someone else picked. `median` is `p50`.

There is no single definition of a percentile, there are at least nine, and
they disagree on small inputs. `sift` uses linear interpolation between ranks,
which is what numpy, pandas and Excel's `PERCENTILE` all default to, so a
number from here matches the number you get when you check it somewhere else.

## What it does about CSV having no types

CSV fields are text, so a naive tool compares `"9" > "100"` as strings and
returns the wrong rows. `sift` reads a field as a number when it plainly is
one, which makes `--where "price > 100"` and `--sort price` mean what they look
like.

Two deliberate exceptions:

- **Leading zeros stay text.** `007` is an identifier far more often than it is
  seven, and coercing it loses the thing that made it a key.
- **Mixed columns filter rather than fail.** Comparing `> 6` against `"abc"` is
  false, not an error. Real columns have blanks and labels in them, and
  refusing to run is worse than excluding the row.

Aggregates skip blanks and non-numbers for the same reason: `avg(price)` over a
column with one empty cell should be the average of the rest, not a crash.

## Streaming

A row is read, tested, projected and written before the next is read, so a file
larger than memory costs the same as a small one, and `sift big.csv --limit 10`
stops reading after ten rows rather than after the file.

Three things cannot stream, and are the only places memory grows with input:

- `--sort`, because the last row read can be the first row out. `--sort` *with*
  `--limit N` is the exception: only the best N rows seen so far can still be in
  the answer, so it keeps N rows and not the file;
- `--group-by`, which holds one bucket per distinct key, bounded by
  cardinality, not by row count;
- reading `--from json`, because an array's shape is only known at its closing
  bracket. Use JSONL where the file is large.

## Formats

Input is inferred from the extension and overridden with `--from`; output is
`--to`, defaulting to CSV. Both ends support `csv`, `jsonl` and `json`, so
`sift` doubles as a converter:

```bash
sift data.csv --to jsonl > data.jsonl
```

Input is read as UTF-8, tolerating the byte order mark Excel writes, so an
Excel export is queryable by its first column rather than by a name with an
invisible character on the front. For the exports that are not UTF-8 at all,
`--encoding cp1252` or `--encoding latin-1`; the error message says so when it
happens.

Piping into `head` closes the pipe early; that is the pipeline working, so
`sift` exits quietly rather than reporting a broken pipe.

The streaming claim is measured, not asserted: a `--where --limit` query holds a
flat **0.15 MB** whether the file is 500k or 2M rows, while a bare `--sort` grows
from 237 MB to 949 MB over the same inputs. `--sort price --limit 10` used to pay
that same 949 MB and now holds a flat **0.14 MB**. See
[benchmarks/RESULTS.md](benchmarks/RESULTS.md).

## Exit codes

`0` success · `1` an input or file problem · `2` a query that could not be
understood, with the reason and the columns that do exist.

## Related

Four small tools that each do one thing to a table of data, and are written to
be read rather than to compete with DuckDB:

- [csvpeek](https://github.com/martin-k-m/csvpeek) profiles a file: column
  types, null counts, distributions.
- **sift** queries one: filter, sort, aggregate, in one pass where it can.
- [drift](https://github.com/martin-k-m/drift) diffs two of them, in Rust.
- [quarry](https://github.com/martin-k-m/quarry) is the long way round, a
  hand-written SQL parser and executor meant to be read.

## License

MIT
