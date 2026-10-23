# Fleet Simulation Engine

A discrete-time simulation engine for a fleet of vessels (Saronic interview project, Project 2). It reads one JSON command per line on stdin and writes exactly one JSON response per line on stdout.

It implements the base problem, Follow-on 1 (cargo and docks) and Follow-on 2 (historical queries). The design and the reasoning behind it are in [`Fleet_Simulation_Design_Doc.pdf`](Fleet_Simulation_Design_Doc.pdf).

## Requirements

- Python 3.10 or newer (tested on 3.10, 3.11 and 3.14). Check with `python3 --version`.
- Nothing to install: the engine uses only the Python standard library.

## Project layout

```
sim.py                            the engine (single file)
tests/
  test_sim.py                     test runner
  cases/NAME.in.jsonl             commands for one test case
  cases/NAME.out.jsonl            the exact responses expected for them
Fleet_Simulation_Design_Doc.pdf   design doc
```

## Running the engine

Run every command below from the project root, the folder that contains `sim.py`.

### 1. Run a file of commands

```bash
python3 sim.py < tests/cases/base_example.in.jsonl
```

Each input line produces one output line, in order. The first three lines of output:

```
{"status": "ok", "payload": {"tick": 0, "vessels": {"v1": {"state": "idle", "location": 0}, "v2": {"state": "idle", "location": 2}}}}
{"status": "ok", "payload": {"tick": 0, "vessels": {"v1": {"state": "transit", "from": 0, "to": 2, "arrives_at_tick": 7}, "v2": {"state": "idle", "location": 2}}}}
{"status": "ok", "payload": {"tick": 0, "vessels": {"v1": {"state": "transit", "from": 0, "to": 1, "arrives_at_tick": 4}, "v2": {"state": "idle", "location": 2}}}}
```

The spec's three worked examples are included, so you can replay each one:

| Spec example | Command |
|---|---|
| Base problem | `python3 sim.py < tests/cases/base_example.in.jsonl` |
| Follow-on 1: cargo and docks | `python3 sim.py < tests/cases/cargo_example.in.jsonl` |
| Follow-on 2: history (continues Follow-on 1) | `python3 sim.py < tests/cases/history_example.in.jsonl` |

### 2. Type commands interactively

```bash
python3 sim.py
```

Paste or type one command per line and press Enter; the response appears immediately. Press `Ctrl-D` to quit. For example:

```
> {"command": "init", "parameters": {"travel_times": [[0,4,7],[4,0,3],[7,3,0]], "vessels": [{"id": "v1", "location": 0}, {"id": "v2", "location": 2}]}}
{"status": "ok", "payload": {"tick": 0, "vessels": {"v1": {"state": "idle", "location": 0}, "v2": {"state": "idle", "location": 2}}}}
> {"command": "set_destination", "parameters": {"vessel_id": "v1", "destination": 1}}
{"status": "ok", "payload": {"tick": 0, "vessels": {"v1": {"state": "transit", "from": 0, "to": 1, "arrives_at_tick": 4}, "v2": {"state": "idle", "location": 2}}}}
> {"command": "tick", "parameters": {}}
{"status": "ok", "payload": {"tick": 1, "vessels": {"v1": {"state": "transit", "from": 0, "to": 1, "arrives_at_tick": 4}, "v2": {"state": "idle", "location": 2}}}}
> {"command": "set_destination", "parameters": {"vessel_id": "v1", "destination": 2}}
{"status": "error", "payload": {"message": "vessel v1 is not idle"}}
```

(`>` marks the lines you type; it is not printed.)

### 3. Drive it from another program

Start `python3 sim.py` as a subprocess, write one command line to its stdin, and read one line from its stdout. Every response is flushed immediately, so a driver can wait for each reply before sending the next command. Blank lines are ignored and get no response.

## Commands

Every command is a JSON object with a `command` name and a `parameters` object (use `{}` when there are none).

| Command | Parameters | What it does |
|---|---|---|
| `init` | `travel_times`, `vessels`; optional `dock_throughput`, `cargo_manifest` | Builds the world at tick 0. Must be the first command, and runs once. |
| `tick` | optional `cargo_manifest` | Commits this tick's commands and advances time by one tick. |
| `set_destination` | `vessel_id`, `destination` | Sends an idle vessel to another location. |
| `get_state` | none | Returns the current planned state. |
| `dock` | `vessel_id` | Docks an idle vessel at its location. |
| `undock` | `vessel_id` | Returns a docked vessel to idle. |
| `load` | `vessel_id`, `destination` | Moves one cargo unit for `destination` from the dock onto the vessel. |
| `unload` | `vessel_id`, `destination` | Moves one cargo unit from the vessel to the dock, delivering it if this is its destination. |
| `swap` | `vessel_id`, `load_destination`, `unload_destination` | A load and an unload as one dock operation. |
| `get_state_at` | `tick` | Returns the committed state at a past or current tick. |

An `init` **without** `dock_throughput` runs the base problem: responses have no `cargo` fields, and `dock`, `undock`, `load`, `unload`, `swap` and `cargo_manifest` are rejected. An `init` **with** `dock_throughput` enables cargo and docks.

Every response is either `{"status": "ok", "payload": <world state>}` or `{"status": "error", "payload": {"message": "<reason>"}}`. A rejected command changes nothing.

## Testing

### Run the full test suite

```bash
python3 -m unittest -v
```

Expected output:

```
test_transcripts (tests.test_sim.TranscriptTest.test_transcripts) ... ok

----------------------------------------------------------------------
Ran 1 test in 0.3s

OK
```

"Ran 1 test" is one test that loops over all 14 cases in `tests/cases/`. For each case it:

1. runs `sim.py` as a separate process with `NAME.in.jsonl` as its input,
2. checks that the process exits cleanly, and
3. compares every output line with `NAME.out.jsonl`, as parsed JSON.

If a case fails, the report names it, for example `FAIL: ... (case='swap')`, and shows which responses differ. The other cases still run.

### Check one case by hand

The expected files match the engine's output byte for byte, so a plain `diff` works. No output means the case passes:

```bash
python3 sim.py < tests/cases/swap.in.jsonl | diff - tests/cases/swap.out.jsonl
```

### What the test cases cover

| Case | Commands | Covers |
|---|---|---|
| `base_example` | 9 | The spec's base example, word for word (ticks 2–3 filled in) |
| `cargo_example` | 21 | The spec's Follow-on 1 example (ticks 5–10 filled in) |
| `history_example` | 25 | The spec's Follow-on 2 example, continuing Follow-on 1 |
| `protocol` | 5 | Invalid JSON, non-object lines, missing `parameters`, unknown commands, blank lines skipped |
| `init` | 5 | Commands before `init`, a failed `init` then a retry, a second `init` |
| `set_destination` | 8 | Overriding an order before the tick, unknown vessel, out-of-range or current location, missing field |
| `base_mode` | 7 | `init` without `dock_throughput`: no cargo fields, cargo commands rejected |
| `cargo_manifest` | 5 | Cargo added on `init` and `tick`, invalid manifest entries, a rejected tick not advancing time |
| `dock` | 10 | `dock` and `set_destination` overriding each other, `undock` checks, unknown vessel |
| `load_unload` | 15 | Throughput shared across vessels, no cargo to move, delivery at the destination |
| `swap` | 13 | The spec's swap example, a missing half, one operation per swap |
| `cargo_decisions` | 15 | The spec's "left to the implementer" cases: dock or undock twice, undock after dock, load then unload, undock with cargo |
| `history` | 16 | Tick 0, negative, non-integer and future ticks, committed vs planned, a rejected tick |
| `validation` | 17 | Bad `travel_times`, `dock_throughput` and vessels; booleans passed as numbers |

### Add a test case

Create `tests/cases/NAME.in.jsonl` with one command per line and `tests/cases/NAME.out.jsonl` with the expected response for each. The runner picks up new pairs automatically; no code changes are needed.
