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

Choices the spec leaves open. Each is pinned by a transcript in `tests/cases/`.

The rule behind most of them: a vessel's **mode** (idle / docked / transit) is checked against the committed state, while **amounts** (inventory, throughput used) are checked against the planned state. Commands always write to the planned state.

**Protocol**
- Blank lines are not commands and get no response.
- `parameters` is required on every command; unknown extra fields are ignored.
- An unexpected failure returns `internal error: ...` and the engine keeps running.
- A rejected command changes nothing, including a failed `init` (which can be retried) and a rejected `tick` (time does not advance).

**Vessels**
- `set_destination` to the vessel's current location is rejected: the trip would arrive at a tick that has already passed and never resolve.
- `dock` after `dock`, or `undock` after `undock`, in the same tick: accepted, no change.
- `undock` after `dock`, or `dock` after `undock`, in the same tick: rejected, because the committed mode has not changed yet.

**Cargo**
- `undock` and `load`/`unload`/`swap` in the same tick are allowed in either order, with the same result: cargo moves while the vessel is still docked, and it leaves at the tick.
- `load` then `unload` of the same cargo counts as 2 operations. Operations count commands, not net change, which is what makes `swap` count as 1.
- Both halves of a `swap` must be possible before it starts; the unit being unloaded cannot be loaded back in the same swap.

**Input checks**
- `init` rejects a non-square or non-integer `travel_times`, a nonzero diagonal, travel times of 0 or less, a `dock_throughput` that is not one positive integer per location, vessels with an invalid id or location, and duplicate vessel ids.
- Locations and destinations must be integers in range; booleans are rejected even though Python treats them as integers.
