"""Exact linear disclosure witnesses. No numeric tolerance and no inference from bounds."""

import json
import re
from dataclasses import dataclass
from fractions import Fraction

MAX_BYTES = 2 * 1024 * 1024
MAX_CELLS = 64
MAX_RELEASES = 128
MAX_TERMS = 4096
IDENTIFIER = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}\Z")
NUMBER = re.compile(r"-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,12}|/[1-9][0-9]{0,11})?\Z")
REPORT_VERSION = "sum-reconstruction/v1"


class InputError(ValueError):
    """A bounded, public error message that does not echo input values."""


@dataclass(frozen=True)
class Release:
    id: str
    coefficients: tuple[int, ...]
    total: Fraction


@dataclass(frozen=True)
class Problem:
    cells: tuple[str, ...]
    protected: tuple[str, ...]
    releases: tuple[Release, ...]


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InputError("duplicate JSON member")
        result[key] = value
    return result


def _constant(_value):
    raise InputError("non-finite JSON number")


def load_json(data: bytes):
    """Load UTF-8 JSON without losing duplicate-member evidence."""
    if len(data) > MAX_BYTES:
        raise InputError("input exceeds 2 MiB")
    depth = 0
    quoted = escaped = False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 64:
                raise InputError("JSON nesting exceeds 64 levels")
        elif byte in (93, 125):
            depth -= 1
    try:
        return json.loads(
            data.decode("utf-8-sig"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, InputError):
            raise
        raise InputError("invalid UTF-8 JSON") from None


def _object(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= value.keys():
        raise InputError("missing or invalid object fields")
    if value.keys() - set(required) - set(optional):
        raise InputError("unknown object fields")


def _ids(value, maximum):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise InputError("invalid identifier-list length")
    if any(not isinstance(v, str) or not IDENTIFIER.fullmatch(v) for v in value):
        raise InputError("identifiers must be short ASCII names")
    if len(set(value)) != len(value):
        raise InputError("duplicate identifier")
    return tuple(value)


def _number(value):
    if type(value) is int and abs(value) <= 10**18:
        return Fraction(value)
    if isinstance(value, str) and NUMBER.fullmatch(value):
        return Fraction(value)
    raise InputError("totals must be bounded integers or exact decimal/fraction strings")


def parse_problem(value) -> Problem:
    """Validate an explicit mapping of published equations to shared cells."""
    _object(value, ("version", "cells", "releases"), ("protected",))
    if type(value["version"]) is not int or value["version"] != 1:
        raise InputError("unsupported input version")
    cells = _ids(value["cells"], MAX_CELLS)
    protected = _ids(value.get("protected", list(cells)), MAX_CELLS)
    if not set(protected) <= set(cells):
        raise InputError("protected cell is not declared")
    raw_releases = value["releases"]
    if not isinstance(raw_releases, list) or not 1 <= len(raw_releases) <= MAX_RELEASES:
        raise InputError("releases must contain 1..128 equations")
    releases = []
    terms_seen = 0
    for raw in raw_releases:
        _object(raw, ("id", "terms", "total"))
        release_id = _ids([raw["id"]], 1)[0]
        terms = raw["terms"]
        if not isinstance(terms, dict) or not terms or not set(terms) <= set(cells):
            raise InputError("terms must reference declared cells")
        if any(type(c) is not int or not 1 <= abs(c) <= 10**6 for c in terms.values()):
            raise InputError("coefficients must be nonzero bounded integers")
        terms_seen += len(terms)
        if terms_seen > MAX_TERMS:
            raise InputError("too many equation terms")
        releases.append(
            Release(release_id, tuple(terms.get(c, 0) for c in cells), _number(raw["total"]))
        )
    if len({r.id for r in releases}) != len(releases):
        raise InputError("duplicate release identifier")
    return Problem(cells, protected, tuple(releases))


def _witness(problem, weights):
    return [
        {"release": release.id, "coefficient": str(weight)}
        for release, weight in zip(problem.releases, weights, strict=True)
        if weight
    ]


def audit(problem: Problem, *, show_values: bool = False) -> dict:
    """Return all protected cells uniquely fixed by a consistent rational system.

    Row operations are also applied to an identity matrix. Its rows are certificates
    in terms of the original public releases, not opaque solver status messages.
    """
    n, m = len(problem.cells), len(problem.releases)
    rows = [[Fraction(c) for c in r.coefficients] + [r.total] for r in problem.releases]
    provenance = [[Fraction(i == j) for j in range(m)] for i in range(m)]
    pivots = []
    for col in range(n):
        rank = len(pivots)
        pivot = next((i for i in range(rank, m) if rows[i][col]), None)
        if pivot is None:
            continue
        rows[rank], rows[pivot] = rows[pivot], rows[rank]
        provenance[rank], provenance[pivot] = provenance[pivot], provenance[rank]
        divisor = rows[rank][col]
        rows[rank] = [v / divisor for v in rows[rank]]
        provenance[rank] = [v / divisor for v in provenance[rank]]
        for i in range(m):
            if i == rank or not rows[i][col]:
                continue
            factor = rows[i][col]
            rows[i] = [v - factor * p for v, p in zip(rows[i], rows[rank], strict=True)]
            provenance[i] = [
                v - factor * p for v, p in zip(provenance[i], provenance[rank], strict=True)
            ]
        pivots.append(col)
    report = {
        "schema": REPORT_VERSION,
        "model": "rational-linear-equalities",
        "status": "no-unique-reconstruction",
        "cell_count": n,
        "release_count": m,
        "protected_count": len(problem.protected),
        "rank": len(pivots),
        "degrees_of_freedom": n - len(pivots),
        "values_included": show_values,
        "recoverable": [],
        "limitations": [
            "No nonnegative, integer, interval, external-data or cross-release mapping inference.",
            "No unique reconstruction under this model is not a privacy guarantee.",
        ],
    }
    for i, row in enumerate(rows):
        if not any(row[:-1]) and row[-1]:
            report["status"] = "inconsistent"
            report["degrees_of_freedom"] = None
            report["contradiction"] = {"witness": _witness(problem, provenance[i])}
            if show_values:
                report["contradiction"]["residual"] = str(row[-1])
            return report
    for i, col in enumerate(pivots):
        if problem.cells[col] not in problem.protected:
            continue
        if any(v for j, v in enumerate(rows[i][:-1]) if j != col):
            continue
        recovered = {"cell": problem.cells[col], "witness": _witness(problem, provenance[i])}
        if show_values:
            recovered["value"] = str(rows[i][-1])
        report["recoverable"].append(recovered)
    if report["recoverable"]:
        report["status"] = "reconstructible"
    return report


def _certificate_number(value):
    # Certificates may have larger exact fractions than input totals, but are bounded.
    if not isinstance(value, str) or len(value) > 4096:
        raise InputError("invalid certificate coefficient")
    if not re.fullmatch(r"-?[0-9]+(?:/[1-9][0-9]*)?", value):
        raise InputError("invalid certificate coefficient")
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        raise InputError("invalid certificate coefficient") from None


def _combine(problem, witness):
    if not isinstance(witness, list) or not 1 <= len(witness) <= len(problem.releases):
        raise InputError("invalid certificate length")
    by_id = {release.id: release for release in problem.releases}
    seen = set()
    coefficients = [Fraction(0) for _ in problem.cells]
    total = Fraction(0)
    for term in witness:
        _object(term, ("release", "coefficient"))
        name = term["release"]
        if not isinstance(name, str) or name not in by_id or name in seen:
            raise InputError("invalid certificate release")
        seen.add(name)
        weight = _certificate_number(term["coefficient"])
        if not weight:
            raise InputError("zero certificate coefficient")
        release = by_id[name]
        coefficients = [
            v + weight * c for v, c in zip(coefficients, release.coefficients, strict=True)
        ]
        total += weight * release.total
    return coefficients, total


def verify_report(problem: Problem, report: dict) -> int:
    """Verify supplied positive identities directly, without Gaussian elimination.

    This checks certificates, not completeness or unproved report metadata. A valid
    cell identity alone does not prove that the rest of the system is consistent.
    """
    if not isinstance(report, dict) or report.get("schema") != REPORT_VERSION:
        raise InputError("unsupported certificate report")
    status = report.get("status")
    if status == "inconsistent":
        item = report.get("contradiction")
        _object(item, ("witness",), ("residual",))
        coefficients, total = _combine(problem, item["witness"])
        if any(coefficients) or not total:
            raise InputError("contradiction certificate is false")
        if "residual" in item and _certificate_number(item["residual"]) != total:
            raise InputError("contradiction residual does not match")
        return 1
    if status != "reconstructible":
        raise InputError("report has no positive certificates to verify")
    entries = report.get("recoverable")
    if not isinstance(entries, list) or not 1 <= len(entries) <= len(problem.protected):
        raise InputError("invalid recovered-cell list")
    seen = set()
    for item in entries:
        _object(item, ("cell", "witness"), ("value",))
        cell = item["cell"]
        if not isinstance(cell, str) or cell not in problem.protected or cell in seen:
            raise InputError("invalid recovered cell")
        seen.add(cell)
        coefficients, total = _combine(problem, item["witness"])
        expected = [Fraction(c == cell) for c in problem.cells]
        if coefficients != expected:
            raise InputError("reconstruction certificate is false")
        if "value" in item and _certificate_number(item["value"]) != total:
            raise InputError("recovered value does not match")
    return len(entries)
