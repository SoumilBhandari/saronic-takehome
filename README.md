# Fleet Simulation Engine

A discrete-time simulation engine for a fleet of vessels, driven by newline-delimited JSON commands over stdin/stdout.

## Requirements

Python 3.10+. No dependencies.

## Run

```bash
python3 sim.py < tests/cases/base_example.in.jsonl
```

## Test

```bash
python3 -m unittest
```

## Decisions

Choices the spec leaves open, filled in as each step is built.
