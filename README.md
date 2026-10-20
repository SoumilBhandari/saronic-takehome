# Fleet Simulation Engine

A discrete-time simulation engine for a fleet of vessels, driven by newline-delimited JSON commands over stdin/stdout.

## Requirements

Python 3.10+. No dependencies.

## Run

```bash
python3 sim.py < tests/cases/base_example.in.jsonl
```

Each line of input is one command; each command gets one line of output. An `init` without `dock_throughput` runs the base problem; with it, Follow-ons 1 and 2.

## Test

```bash
python3 -m unittest
```

Every `tests/cases/NAME.in.jsonl` is run through `sim.py` and its output compared, line by line as JSON, with `NAME.out.jsonl`.
