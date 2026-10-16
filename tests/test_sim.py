"""Runs every transcript in tests/cases through sim.py.

Each case is a pair: NAME.in.jsonl (commands) and NAME.out.jsonl (expected
responses). Responses are compared line by line as parsed JSON.
"""

import unittest
from pathlib import Path

CASES = Path(__file__).parent / "cases"


class TranscriptTest(unittest.TestCase):
    def test_transcripts(self) -> None:
        raise NotImplementedError
