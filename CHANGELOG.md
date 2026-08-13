# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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
