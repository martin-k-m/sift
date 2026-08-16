# Benchmark results

`sift`'s central claim is in the README: a streaming query costs the same memory
on a large file as on a small one, and the clauses that must buffer (`--sort`,
`--group-by`) are the only ones whose memory grows with input. This is that
claim, measured.

## How to reproduce

```bash
pip install -e .
python benchmarks/bench.py --rows 500000
python benchmarks/bench.py --rows 2000000
```

The harness builds a deterministic CSV (an `id`, two categorical columns, and a
numeric `price`), runs each query through `sift`'s own engine in-process, and
reports throughput and peak resident allocation measured with the stdlib
`tracemalloc` — no third-party profiler, to keep the zero-dependency promise.
Numbers below are from CPython 3.12 on Windows 11; absolute timings will vary by
machine, but the *shape* — flat versus linear — is the point and is
machine-independent.

## The numbers

| Query | Rows | Peak memory | Time |
| --- | ---: | ---: | ---: |
| `--where + --select + --limit 10` | 500,000 | **0.15 MB** | 0.001 s |
| `--where + --select + --limit 10` | 2,000,000 | **0.15 MB** | 0.001 s |
| `--sort price --limit 10` † | 500,000 | **0.14 MB** | 3.9 s |
| `--sort price --limit 10` † | 2,000,000 | **0.14 MB** | 19.8 s |
| `--sort price` | 500,000 | 237 MB | 5.7 s |
| `--sort price` | 2,000,000 | 949 MB | 27.7 s |
| `--agg avg(price) -g category` | 500,000 | 192 MB | 4.9 s |
| `--agg avg(price) -g category` | 2,000,000 | 768 MB | 21.9 s |

† The two `--limit 10` sort rows were measured on a later, slower session than
the rest of the table: the same harness reported 10.5 s and 76.5 s for the bare
`--sort price` rows there, against the 5.7 s and 27.7 s recorded above. Compare
their *memory* against the rest of the table freely, since that is
machine-independent; for their *time*, use the same-session A/B below.

## `--sort` with `--limit` does not hold the file

A `--sort` has to buffer because the last row read can be the first row out.
That stops being true the moment a `--limit N` is attached: only the best N rows
seen so far can still appear in the answer, so the engine keeps a bounded heap of
N rows instead of the input. Both variants were run back to back in one session,
so these timings are comparable to each other:

| Query | Rows | Peak memory | Time |
| --- | ---: | ---: | ---: |
| `--sort price --limit 10`, buffering the file | 500,000 | 236.90 MB | 7.90 s |
| `--sort price --limit 10`, bounded heap | 500,000 | **0.14 MB** | **3.84 s** |
| `--sort price --limit 10`, buffering the file | 2,000,000 | 949.26 MB | 42.87 s |
| `--sort price --limit 10`, bounded heap | 2,000,000 | **0.14 MB** | **19.04 s** |

Memory goes from linear in the input to flat: **0.14 MB at both 500k and 2M
rows**, a 1,700× reduction at 500k and 6,800× at 2M. Time roughly halves as
well, which is the same fact seen from the other side, since sorting N rows
beats sorting the file and the discarded rows are never copied into a list.

The bounded path is `heapq.nsmallest`/`nlargest`, documented as equivalent to
sorting and slicing, ties included, so the rows and their order are identical to
what the full sort produced. The test suite asserts that equivalence across
several limits and both directions rather than taking it on trust, and asserts
the memory gap directly with `tracemalloc`.

A bare `--sort` with no `--limit` still buffers, and always will; nothing short
of spilling to disk changes that, and it is not worth a temp file for a tool
whose point is that it has no moving parts.

## Reading them

**The streaming query is flat.** `--where … --limit 10` holds **0.15 MB whether
the file is 500,000 rows or 2,000,000** — quadruple the input, identical memory,
and it finishes in a millisecond because `--limit 10` stops reading after the
tenth matching row rather than after the file. That flat 0.15 MB, independent of
input size, *is* the streaming guarantee. Against the 2M-row `--sort` it is a
**~6,000× difference in peak memory** for the same source file.

**The buffering queries grow linearly, as designed.** `--sort` goes 237 MB →
949 MB as the input goes 500k → 2M — four times the rows, roughly four times the
memory, because the last row read can be the first row out, so the whole file
must be held. `--group-by` is the same story: it keeps one accumulator per
distinct key, and here every row is materialized before grouping. These are not
regressions; they are the two places the README says memory *must* grow, and the
measurement confirms it grows and nowhere else does.

## One honest caveat about the harness

A plain `--where price > 500` (no `--limit`) reports 5 MB at 500k rows and 27 MB
at 2M — it appears to grow. It does not grow *in `sift`*: the benchmark writes
output into an in-memory `StringIO`, so it is accumulating the ~1,000,000
matching output rows, and that buffer is what `tracemalloc` sees. Piped to a
real terminal, a file, or `head`, those rows leave as they are produced and the
engine's own footprint stays flat, exactly like the `--limit 10` line.

The `--limit 10` row is the honest demonstration precisely because it removes
this artifact: with only ten rows ever held on the output side, what remains is
the engine's true working set, and that is the number that does not move.
