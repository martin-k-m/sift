# Contributing to sift

Thanks for taking a look. `sift` is small on purpose, so the bar for a change
is that it keeps the tool small and keeps the promises in the README.

## Setup

No dependencies to run. The test and lint tools are the `dev` group in
`pyproject.toml`, which is the one list CI installs from too.

```bash
git clone https://github.com/martin-k-m/sift
cd sift
uv sync --group dev
uv run pytest -q
```

or with pip, which needs 25.1 or newer for `--group`:

```bash
pip install -e .
python -m pip install --group dev
python -m pytest -q
```

## Ground rules

- **Zero runtime dependencies.** The standard library is the whole toolbox. A
  change that adds a dependency needs to justify why the stdlib genuinely
  cannot do it.
- **Everything that can stream, streams.** A new clause that reads the whole
  input where it did not have to is a regression, even if the tests pass. The
  only clauses allowed to buffer are `--sort`, `--group-by`, and reading a
  JSON array, and each says so in a comment.
- **Errors are for the person who typed the query.** An error message names
  the problem and, where it can, the columns or functions that *do* exist. A
  stack trace reaching the user is a bug.
- **A change to behaviour comes with a test.** The test suite in
  `tests/test_sift.py` is the specification; add to it.

## Before you open a pull request

```bash
python -m pytest -q          # all tests pass
sift --version               # the entry point still resolves
```

Keep the diff focused on one thing. Small, single-purpose pull requests get
reviewed and merged faster than large ones.

## Reporting bugs

Open an issue with the exact command you ran, the input (a few rows is enough),
what you expected, and what happened. A failing case as a `pytest` function is
the most useful bug report there is.
