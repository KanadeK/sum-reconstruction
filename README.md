# sum-reconstruction

Find protected numeric cells that can be reconstructed by combining published aggregate totals. Run locally with Python 3.10+; there are no runtime dependencies or network calls.

Suppose separate releases publish `a + b = 7`, `b + c = 9`, and `a + c = 8`. Each total covers two hidden cells, but together they disclose `a = 3`, `b = 4`, `c = 5`. This tool detects the reconstruction and explains it with exact, independently checkable linear-combination witnesses.

Use it when reviewing overlapping statistical tables, counters or successive aggregate releases whose relationships you can explicitly model. It needs the published equations, **not individual-level source data**.

## Install and try

```sh
git clone https://github.com/KanadeK/sum-reconstruction.git
cd sum-reconstruction
python -m venv .venv
# Linux/macOS: . .venv/bin/activate
# PowerShell: .venv\Scripts\Activate.ps1
python -m pip install .
sum-reconstruction audit examples/overlap.json
```

The audit exits **1** because three protected cells are reconstructible. The JSON report contains the witness for `a`: half of `first`, minus half of `second`, plus half of `third`. Recovered numeric values are omitted by default. Add `--show-values` when you explicitly want them in the report.

```sh
sum-reconstruction audit examples/overlap.json -o review.json
# Expected exit code: 1. Continue to verify the written report.
sum-reconstruction verify examples/overlap.json review.json
# {"status": "certificates-valid", "checked": 3}
sum-reconstruction audit examples/underdetermined.json
# Expected exit code: 0, status: no-unique-reconstruction
```

The tool refuses an existing output file, including the input path. Remove your old report or choose a new filename before repeating `-o`. Without `-o`, the report goes to stdout. `-` accepts UTF-8 JSON from stdin. Module invocation also works: `python -m sum_reconstruction audit ...`.

Uninstall with `python -m pip uninstall sum-reconstruction`. Remove the virtual environment and generated review files when no longer needed; the tool creates no cache or background service. The package is installed from this repository or its release wheel; no PyPI publication is implied.

## Input contract

```json
{
  "version": 1,
  "cells": ["a", "b", "c"],
  "protected": ["a"],
  "releases": [
    {"id": "first", "terms": {"a": 1, "b": 1}, "total": 7},
    {"id": "second", "terms": {"b": 1, "c": 1}, "total": 9},
    {"id": "third", "terms": {"a": 1, "c": 1}, "total": 8}
  ]
}
```

Each release means the sum of `coefficient × cell` equals `total`. The same cell identifier across releases must mean the same underlying quantity. A public known cell can be modeled as a singleton equation. Omit `protected` to check every cell. Use synthetic identifiers to avoid putting personal labels in reports.

Limits: 2 MiB UTF-8 JSON (a BOM is allowed), nesting at most 64 levels, 1–64 cells, 1–128 releases, and at most 4,096 nonzero terms. Identifiers match `[A-Za-z][A-Za-z0-9_.-]{0,63}`. Coefficients are nonzero integers of absolute value at most one million. Totals are JSON integers of absolute value at most `10^18`, or exact strings: an optional minus sign, up to 18 integer digits, optionally followed by a decimal point and 1–12 digits, or `/` and a positive denominator of up to 12 digits. Examples: `"0.10"`, `"-7/3"`. Floating JSON numbers, exponents, duplicate keys, duplicate IDs, unknown fields and undeclared cells are rejected.

## Results and exit codes

| Exit | Meaning |
|---|---|
| 0 | Audit: no protected cell uniquely determined by the supplied rational equalities. Verify: all supplied positive certificates pass the algebra check. |
| 1 | Audit: at least one protected cell is uniquely reconstructible. |
| 2 | Inconsistent equations, invalid input/certificate, exceeded limits, CLI misuse or I/O error. |

An inconsistent system returns a contradiction certificate (a combination with zero coefficients and a nonzero total); it never reports a successful reconstruction. Input/operational errors go to stderr without echoing data or paths. Reports include input identifiers, counts, rank and certificate coefficients. With `--show-values`, they also include exact recovered values or contradiction residuals.

`verify` recomputes each supplied identity directly from the original equations; it does not run row reduction. It verifies positive certificates only, **not completeness, rank metadata or global consistency**. A report with no positive certificates cannot be verified by this command. Re-run `audit` to check the whole system.

Equation inputs are limited to 2 MiB; certificate reports accepted by `verify` have a separate 8 MiB limit because exact rational witnesses can be much larger than their input. Version 0.1.1 fixes the initial release's overly small report-reading limit. A dense 64-cell report roundtrip is covered by regression tests.

## Method and boundaries

The engine performs Gaussian elimination using Python's exact `Fraction` arithmetic and tracks each row operation on an identity matrix. A protected cell is uniquely determined when a reduced row has coefficient 1 for that cell and 0 for every other cell. The tracked row is its witness in terms of the original releases. There are no floating-point tolerances.

This is an equality-only audit, **not an anonymization certificate**. It does not infer that counts are integers or nonnegative, use bounds or rounded totals, identify equivalent cells across files, infer equations from CSV layouts, model external knowledge, or recommend an optimal suppression plan. For example, `a+b=0` does not uniquely determine rational `a,b`, although nonnegative-count assumptions would reveal both as zero. A zero exit status does not establish privacy. Incorrectly mapped or rounded input equations can produce misleading conclusions.

For full statistical disclosure control, consider [sdcTable](https://sdctools.github.io/sdcTable/) or [Tau-Argus](https://github.com/sdcTools/tauargus). [CellVeil](https://github.com/wedo911/cellveil) checks direct/iterative row-and-column recovery in one CSV table. This tool instead accepts overlapping equations from multiple releases and exports exact algebra certificates. The need for secondary suppression is described in [Government Analysis Function guidance](https://analysisfunction.civilservice.gov.uk/policy-store/sdc-for-tables-produced-from-administrative-data/).

## Development

```sh
python -m pip install -e . build ruff coverage
python -m unittest discover -s tests -v
ruff check src tests
ruff format --check src tests
python -m build
```

Tests include Cramer's-rule comparison for 100 seeded full-rank systems, exhaustive finite candidate checks, partial recovery, exact decimal/fraction inputs, contradictions, malformed inputs, tampered certificates and CLI audit/verify flows. GitHub Actions tests Python 3.10 and 3.13 on Linux and Windows, plus 3.13 on macOS. MIT license; no third-party implementation code is bundled.

## 中文说明

这是一个离线的汇总数据发布前检查工具：把已公开的总和写成等式，检查多份统计结果是否共同反推出受保护的单元值。使用精确分数计算，输出可以单独验证的线性组合证据；默认不输出恢复出的数值。

它不读取原始个人记录，也不提供匿名化合规保证。只检查显式输入的有理数线性等式，不考虑非负、整数、区间约束或外部知识。返回码 1 表示发现可反推单元；2 表示输入错误、矛盾或运行错误；0 仅表示在当前模型中未发现唯一反推。
