# =============================================================================
#  Program Description:  Transcript tests for sim.py. Runs each
#                        tests/cases/NAME.in.jsonl through sim.py and compares
#                        the output, line by line as JSON, with NAME.out.jsonl.
#
#  Usage:                python3 -m unittest
# =============================================================================

import json
import subprocess
import sys
import unittest
from pathlib import Path

CASES = Path(__file__).parent / "cases"
SIM = Path(__file__).parent.parent / "sim.py"


class TranscriptTest(unittest.TestCase):
    def test_transcripts(self) -> None:
        """Run sim.py on every case and compare its output with the expected file."""
        inputs = sorted(CASES.glob("*.in.jsonl"))
        self.assertTrue(inputs, "no transcripts found")
        for input_path in inputs:
            name = input_path.name.removesuffix(".in.jsonl")
            with self.subTest(case=name):
                result = subprocess.run(
                    [sys.executable, str(SIM)],
                    input=input_path.read_text(),
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                expected = (CASES / f"{name}.out.jsonl").read_text().splitlines()
                self.assertEqual(
                    [json.loads(line) for line in result.stdout.splitlines()],
                    [json.loads(line) for line in expected],
                )
