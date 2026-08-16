# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed
- `--sort` combined with `--limit N` no longer buffers the input. Only the best
  N rows seen so far can still be in the answer, so the engine keeps a bounded
  heap of N rows. Measured on the benchmark harness, `--sort price --limit 10`
  goes from 236.90 MB to 0.14 MB at 500k rows and from 949.26 MB to 0.14 MB at
  2M, with the run time roughly halving in both cases. The rows and their order
  are unchanged: `heapq.nsmallest`/`nlargest` are documented as equivalent to
  sorting and slicing, and the tests assert that equivalence directly.
- Sorting a column that mixes numbers and text now reaches its answer in one
  pass with a total-order key (numbers, then text, then missing values) instead
  of attempting a numeric sort and re-sorting everything as text when it
  failed. A column that is entirely numeric or entirely text sorts exactly as
  before.

### Fixed
- A CSV exported from Excel is now queryable by its first column. Excel writes
  a byte order mark, which read as plain UTF-8 attached itself to the first
  header name, so `--where "name = x"` reported that there was no column `name`
  while listing what looked exactly like one. Input is read as `utf-8-sig`,
  which is identical for files without the mark.
- A cell larger than 128 KB no longer aborts the run with a `_csv.Error`
  traceback. The stdlib limit exists to bound a runaway quote, not to reject a
  base64 blob in a cell; it is raised, and any remaining `csv` error becomes a
  message naming the line.
- A file that is not UTF-8 now says which file, and that `--encoding` is the
  flag that fixes it, instead of reporting a byte offset and stopping.

### Added
- `--encoding`, for the CSV exports that are cp1252 or latin-1 rather than
  UTF-8. Defaults to `utf-8-sig`. It also applies to stdin, so a file and the
  same file piped in are read the same way.
- A `ruff` lint job in CI, configured with `target-version = "py39"` so the
  advertised support floor is checked rather than asserted.
- Benchmark script (`benchmarks/bench.py`) measuring throughput and peak memory
  with the stdlib `tracemalloc`, demonstrating that streaming clauses hold
  constant memory while `--sort` and `--group-by` buffer.
- Benchmark results writeup (`benchmarks/RESULTS.md`) with measured numbers: a
  streaming `--where --limit` query holds a flat 0.15 MB from 500k to 2M rows,
  while `--sort` grows 237 MB to 949 MB. Linked from the README.
- Contribution, security, and changelog documentation.

## [0.2.0]

### Added
- Multiple aggregates computed in a single pass (`--agg` is repeatable), so
  `count()` and `avg(price)` no longer need two runs over the file.
- Arbitrary percentiles via `pN` (`p95`, `p99`, `p1`, fractional `p99.9`),
  using linear interpolation between ranks — the definition numpy, pandas, and
  Excel share.
- Grouping by several columns (`--group-by category,region`).
- Negated regex match `!~`, the complement of `~`.

### Fixed
- Mixed-type columns no longer drop rows when sorting; the fallback sorts the
  same buffered rows as text rather than re-reading an emptied generator.
- Fractional percentiles are no longer unreachable in the name parser.

## [0.1.0]

### Added
- Initial release: `--where`, `--select`, `--sort`/`--desc`, `--limit`, and a
  single aggregation form, over CSV, JSONL, and JSON, all streaming where the
  clause allows. MIT licensed.

[Unreleased]: https://github.com/martin-k-m/sift/compare/main...HEAD
[0.2.0]: https://github.com/martin-k-m/sift/releases/tag/v0.2.0
[0.1.0]: https://github.com/martin-k-m/sift/releases/tag/v0.1.0
