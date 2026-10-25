import copy
import itertools
import json
import random
import unittest
from fractions import Fraction
from pathlib import Path

from sum_reconstruction.core import (
    MAX_BYTES,
    InputError,
    audit,
    load_json,
    parse_problem,
    verify_report,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture(name="overlap"):
    return json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def make_problem(matrix, totals, protected=None):
    cells = [f"x{i}" for i in range(len(matrix[0]))]
    value = {
        "version": 1,
        "cells": cells,
        "releases": [
            {
                "id": f"r{i}",
                "terms": {c: a for c, a in zip(cells, row, strict=True) if a},
                "total": total,
            }
            for i, (row, total) in enumerate(zip(matrix, totals, strict=True))
        ],
    }
    if protected is not None:
        value["protected"] = protected
    return parse_problem(value)


def det3(m):
    a, b, c = m
    return (
        a[0] * (b[1] * c[2] - b[2] * c[1])
        - a[1] * (b[0] * c[2] - b[2] * c[0])
        + a[2] * (b[0] * c[1] - b[1] * c[0])
    )


class AlgebraTests(unittest.TestCase):
    def test_overlap_recovers_without_singleton_equations(self):
        problem = parse_problem(fixture())
        report = audit(problem, show_values=True)
        self.assertEqual(report["status"], "reconstructible")
        self.assertEqual(
            {x["cell"]: x["value"] for x in report["recoverable"]}, {"a": "3", "b": "4", "c": "5"}
        )
        self.assertEqual(verify_report(problem, report), 3)
        self.assertEqual(
            report["recoverable"][0]["witness"],
            [
                {"release": "first", "coefficient": "1/2"},
                {"release": "second", "coefficient": "-1/2"},
                {"release": "third", "coefficient": "1/2"},
            ],
        )

    def test_default_omits_recovered_values(self):
        report = audit(parse_problem(fixture()))
        self.assertFalse(report["values_included"])
        self.assertTrue(all("value" not in item for item in report["recoverable"]))
        self.assertEqual(verify_report(parse_problem(fixture()), report), 3)

    def test_underdetermined_is_not_called_safe(self):
        report = audit(parse_problem(fixture("underdetermined")))
        self.assertEqual(report["status"], "no-unique-reconstruction")
        self.assertEqual(report["degrees_of_freedom"], 1)
        self.assertEqual(report["recoverable"], [])
        with self.assertRaises(InputError):
            verify_report(parse_problem(fixture()), report)

    def test_partial_recovery_in_rank_deficient_system(self):
        problem = make_problem([[1, 1, 0], [0, 0, 2]], [9, 7])
        result = audit(problem, show_values=True)
        self.assertEqual(result["degrees_of_freedom"], 1)
        self.assertEqual([(r["cell"], r["value"]) for r in result["recoverable"]], [("x2", "7/2")])

    def test_protected_subset(self):
        value = fixture()
        value["protected"] = ["b"]
        report = audit(parse_problem(value))
        self.assertEqual([r["cell"] for r in report["recoverable"]], ["b"])

    def test_unprotected_recoveries_do_not_trigger_gate(self):
        problem = make_problem([[1, 0]], [2], ["x1"])
        self.assertEqual(audit(problem)["status"], "no-unique-reconstruction")

    def test_row_swap_and_exact_decimal(self):
        problem = make_problem([[0, 2], [3, 0]], ["0.2", "-1/3"])
        self.assertEqual(
            [x["value"] for x in audit(problem, show_values=True)["recoverable"]], ["-1/9", "1/10"]
        )

    def test_redundant_equations(self):
        problem = make_problem([[1, 1], [2, 2], [-1, -1]], [2, 4, -2])
        report = audit(problem)
        self.assertEqual(report["rank"], 1)
        self.assertEqual(report["recoverable"], [])

    def test_inconsistency_has_verifiable_certificate(self):
        problem = parse_problem(fixture("inconsistent"))
        for reveal in [False, True]:
            report = audit(problem, show_values=reveal)
            self.assertEqual(report["status"], "inconsistent")
            self.assertIsNone(report["degrees_of_freedom"])
            self.assertEqual(report["recoverable"], [])
            self.assertEqual(verify_report(problem, report), 1)
            self.assertEqual("residual" in report["contradiction"], reveal)

    def test_nonnegative_or_integer_constraints_are_not_inferred(self):
        result = audit(make_problem([[1, 1]], [0]))
        self.assertEqual(result["status"], "no-unique-reconstruction")
        # Over rational values x=-y is a free family; counts would require extra reasoning.

    def test_cramer_oracle_for_100_seeded_full_rank_systems(self):
        rng = random.Random(17033)
        checked = 0
        while checked < 100:
            matrix = [[rng.randint(-3, 3) for _ in range(3)] for _ in range(3)]
            determinant = det3(matrix)
            if determinant == 0:
                continue
            totals = [rng.randint(-10, 10) for _ in range(3)]
            problem = make_problem(matrix, totals)
            report = audit(problem, show_values=True)
            expected = []
            for col in range(3):
                replaced = [
                    [totals[i] if j == col else matrix[i][j] for j in range(3)] for i in range(3)
                ]
                expected.append(Fraction(det3(replaced), determinant))
            self.assertEqual([Fraction(x["value"]) for x in report["recoverable"]], expected)
            self.assertEqual(verify_report(problem, report), 3)
            checked += 1

    def test_exhaustive_small_integer_candidates_confirm_positive_findings(self):
        rng = random.Random(333)
        domain = list(itertools.product(range(-3, 4), repeat=3))
        for _ in range(35):
            matrix = [[rng.choice([-1, 1]) for _ in range(3)] for _ in range(2)]
            truth = rng.choice(domain)
            totals = [sum(a * b for a, b in zip(row, truth, strict=True)) for row in matrix]
            report = audit(make_problem(matrix, totals), show_values=True)
            feasible = [
                x
                for x in domain
                if all(
                    sum(a * b for a, b in zip(row, x, strict=True)) == total
                    for row, total in zip(matrix, totals, strict=True)
                )
            ]
            self.assertTrue(feasible)
            for item in report["recoverable"]:
                col = int(item["cell"][1:])
                self.assertEqual({x[col] for x in feasible}, {Fraction(item["value"])})

    def test_deterministic_and_input_not_mutated(self):
        value = fixture()
        before = copy.deepcopy(value)
        problem = parse_problem(value)
        self.assertEqual(audit(problem), audit(problem))
        self.assertEqual(value, before)

    def test_maximum_identity_problem(self):
        problem = make_problem(
            [[int(i == j) for j in range(64)] for i in range(64)], list(range(64))
        )
        self.assertEqual(len(audit(problem)["recoverable"]), 64)


class InputTests(unittest.TestCase):
    def test_valid_bom(self):
        self.assertEqual(load_json(b"\xef\xbb\xbf{}"), {})

    def test_duplicate_keys_nonfinite_unicode_and_depth(self):
        for data in [
            b'{"x":1,"x":2}',
            b'{"x":NaN}',
            b'{"x":Infinity}',
            b"\xff",
            b"{",
            b"[" * 1500 + b"]" * 1500,
            b"1" * 5000,
            b" " * (MAX_BYTES + 1),
        ]:
            with self.subTest(size=len(data)), self.assertRaises(InputError):
                load_json(data)

    def test_schema_rejections(self):
        mutations = [
            lambda v: v.update(version=True),
            lambda v: v.update(version=2),
            lambda v: v.update(cells=[]),
            lambda v: v.update(cells=["a", "a"]),
            lambda v: v.update(cells=["private@example.test"]),
            lambda v: v.update(cells=[f"x{i}" for i in range(65)]),
            lambda v: v.update(protected=["unknown"]),
            lambda v: v.update(protected=[]),
            lambda v: v.update(releases=[]),
            lambda v: v.update(releases=[v["releases"][0]] * 129),
            lambda v: v.update(unrecognized=True),
            lambda v: v.pop("cells"),
            lambda v: v["releases"][0].update(total=0.1),
            lambda v: v["releases"][0].update(total=True),
            lambda v: v["releases"][0].update(total="1/0"),
            lambda v: v["releases"][0].update(total="1e3"),
            lambda v: v["releases"][0].update(total=10**19),
            lambda v: v["releases"][0].update(terms={"a": False}),
            lambda v: v["releases"][0].update(terms={"a": 0}),
            lambda v: v["releases"][0].update(terms={"a": 10**7}),
            lambda v: v["releases"][0].update(terms={"unknown": 1}),
            lambda v: v["releases"][0].update(terms={}),
            lambda v: v["releases"][1].update(id="first"),
        ]
        for mutate in mutations:
            value = fixture()
            mutate(value)
            with self.subTest(value=value), self.assertRaises(InputError):
                parse_problem(value)
        for value in [None, [], "x", 7]:
            with self.assertRaises(InputError):
                parse_problem(value)

    def test_term_budget(self):
        cells = [f"x{i}" for i in range(64)]
        value = {
            "version": 1,
            "cells": cells,
            "releases": [
                {"id": f"r{i}", "terms": dict.fromkeys(cells, 1), "total": 1} for i in range(65)
            ],
        }
        with self.assertRaises(InputError):
            parse_problem(value)


class CertificateTests(unittest.TestCase):
    def test_tampering_is_rejected(self):
        problem = parse_problem(fixture())
        original = audit(problem, show_values=True)
        mutations = [
            lambda r: r.update(schema="wrong"),
            lambda r: r.update(recoverable=[]),
            lambda r: r["recoverable"][0].update(cell="unknown"),
            lambda r: r["recoverable"][0].update(value="99"),
            lambda r: r["recoverable"][0].update(witness=[]),
            lambda r: r["recoverable"][0]["witness"][0].update(release=[]),
            lambda r: r["recoverable"][0]["witness"][0].update(release="unknown"),
            lambda r: r["recoverable"][0]["witness"][0].update(coefficient="0"),
            lambda r: r["recoverable"][0]["witness"][0].update(coefficient="5"),
            lambda r: r["recoverable"][0]["witness"][0].update(coefficient="1/0"),
            lambda r: r["recoverable"][0]["witness"][0].update(coefficient="9" * 4097),
            lambda r: r["recoverable"][0]["witness"][0].update(coefficient=1),
            lambda r: r["recoverable"].__setitem__(1, copy.deepcopy(r["recoverable"][0])),
        ]
        for mutate in mutations:
            report = copy.deepcopy(original)
            mutate(report)
            with self.subTest(report=report), self.assertRaises(InputError):
                verify_report(problem, report)

    def test_false_contradiction_and_residual(self):
        problem = parse_problem(fixture("inconsistent"))
        report = audit(problem, show_values=True)
        report["contradiction"]["residual"] = "999"
        with self.assertRaises(InputError):
            verify_report(problem, report)
        report = audit(problem)
        report["contradiction"]["witness"][0]["coefficient"] = "3"
        with self.assertRaises(InputError):
            verify_report(problem, report)


if __name__ == "__main__":
    unittest.main()
