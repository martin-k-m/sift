# Security Policy

## Supported versions

`sift` is distributed on PyPI as `sift-query`. Fixes land on the latest
released version; there are no long-lived maintenance branches.

## Reporting a vulnerability

Please report suspected vulnerabilities privately rather than in a public
issue. Use GitHub's [private vulnerability reporting](https://github.com/martin-k-m/sift/security/advisories/new)
for this repository, or email martinkmuskov@gmail.com.

Include the command and input that reproduce the problem and what you observed.
You can expect an acknowledgement within a few days.

## Scope

`sift` reads local files and standard input and writes to standard output. It
runs no network requests and executes no code from its input. The most likely
class of issue is a crafted file or query that causes excessive memory or an
unhandled exception rather than a controlled error; those are in scope and
worth reporting.

One thing that is intentional rather than a vulnerability: `--where "col ~ ..."`
compiles the operand as a regular expression, so a deliberately pathological
pattern can be slow to match (catastrophic backtracking). Patterns come from
the person running the command, not from the data, so this is treated as the
user's own input.
