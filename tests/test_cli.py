import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, data=None):
    return subprocess.run(
        [sys.executable, "-m", "sum_reconstruction", *map(str, args)],
        input=data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
    )


class CliTests(unittest.TestCase):
    def test_end_to_end_new_file_audit_and_verify(self):
        source = ROOT / "examples/overlap.json"
        before = source.read_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            result = run("audit", source, "-o", report)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout, "")
            verified = run("verify", source, report)
            self.assertEqual(verified.returncode, 0, verified.stderr)
            self.assertEqual(json.loads(verified.stdout)["checked"], 3)
            old_report = report.read_bytes()
            blocked = run("audit", source, "-o", report)
            self.assertEqual(blocked.returncode, 2)
            self.assertEqual(report.read_bytes(), old_report)
        self.assertEqual(source.read_bytes(), before)

    def test_exit_codes_and_stdout(self):
        for name, code, status in [
            ("overlap", 1, "reconstructible"),
            ("underdetermined", 0, "no-unique-reconstruction"),
            ("inconsistent", 2, "inconsistent"),
        ]:
            result = run("audit", ROOT / f"examples/{name}.json", "--show-values")
            self.assertEqual(result.returncode, code, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], status)

    def test_stdin_and_errors_do_not_echo_input(self):
        data = (ROOT / "examples/overlap.json").read_text()
        self.assertEqual(run("audit", "-", data=data).returncode, 1)
        sentinel = "SYNTHETIC_PRIVATE_MARKER"
        result = run("audit", "-", data="{" + sentinel)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(sentinel, result.stdout + result.stderr)
        result = run("audit", "/missing/" + sentinel)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(sentinel, result.stderr)

    def test_input_overwrite_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "input.json"
            source.write_text((ROOT / "examples/overlap.json").read_text())
            original = source.read_bytes()
            result = run("audit", source, "-o", source)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(source.read_bytes(), original)
            link = Path(tmp) / "link.json"
            try:
                link.symlink_to(source)
            except OSError:
                return  # Windows systems without symlink privilege still test exclusive creation above.
            self.assertEqual(run("audit", source, "-o", link).returncode, 2)
            self.assertEqual(source.read_bytes(), original)

    def test_verify_rejects_two_stdin_sources(self):
        result = run("verify", "-", "-", data="{}")
        self.assertEqual(result.returncode, 2)

    def test_help_and_version(self):
        self.assertEqual(run("--version").stdout.strip(), "0.1.0")
        self.assertEqual(run("--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
