"""Runs every transcript in tests/cases through sim.py.

Each case is a pair: NAME.in.jsonl (commands) and NAME.out.jsonl (expected
responses). Responses are compared line by line as parsed JSON.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

CASES = Path(__file__).parent / "cases"
SIM = Path(__file__).parent.parent / "sim.py"


class TranscriptTest(unittest.TestCase):
    def test_transcripts(self) -> None:
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
