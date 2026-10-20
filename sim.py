"""Fleet simulation engine.

Reads newline-delimited JSON commands from stdin and writes exactly one JSON
response per command to stdout.

Usage: python3 sim.py < commands.jsonl
"""

import copy
import json
import sys


class CommandError(Exception):
    """A rejected command. Its message is returned as the error response."""


def is_int(value) -> bool:
    """True for a JSON integer. Python treats booleans as ints, so exclude them."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_index(value, n: int) -> bool:
    """True for a valid location index, 0 to n-1."""
    return is_int(value) and 0 <= value < n


def without_cargo(state: dict) -> dict:
    """The base problem's view of a world state: no vessel or dock cargo."""
    return {
        "tick": state["tick"],
        "vessels": {
            vessel_id: {k: v for k, v in vessel.items() if k != "cargo"}
            for vessel_id, vessel in state["vessels"].items()
        },
    }


def find_cargo(entries: list[dict], **key) -> dict | None:
    """Return the entry matching key (e.g. location and destination), or None."""
    for entry in entries:
        if all(entry[k] == v for k, v in key.items()):
            return entry
    return None


def add_cargo(entries: list[dict], quantity: int, **key) -> None:
    """Add units to the entry matching key, creating it at the end if needed."""
    entry = find_cargo(entries, **key)
    if entry is None:
        entries.append({**key, "quantity": quantity})
    else:
        entry["quantity"] += quantity


def take_cargo(entries: list[dict], entry: dict) -> None:
    """Remove one unit from entry, dropping it from the list when none are left."""
    entry["quantity"] -= 1
    if entry["quantity"] == 0:
        entries.remove(entry)


class Simulation:
    def __init__(self) -> None:
        self.travel_times: list[list[int]] = []  # travel_times[i][j] = ticks from i to j
        self.has_cargo = False  # Follow-on 1 is on when init includes dock_throughput
        self.dock_throughput: list[int] = []  # max cargo operations per dock per tick
        self.ops: dict[int, int] = {}  # cargo operations used per location since the last tick
        self.history: list[dict] = []  # committed state at every tick; history[t] is tick t
        self.planned: dict | None = None  # committed state plus commands since the last tick

    @property
    def committed(self) -> dict | None:
        """World state at the current tick: the latest entry in history.

        Commands only write to planned, and tick appends planned as a new entry, so an
        entry is never modified once its tick is over. That is why history needs no copies.
        """
        return self.history[-1] if self.history else None

    def handle(self, line: str) -> dict:
        """Process one input line and return exactly one response envelope."""
        try:
            name, params = self._parse(line)
            if self.committed is None and name != "init":
                raise CommandError("simulation not initialized")
            if name in self.CARGO_COMMANDS and not self.has_cargo:
                raise CommandError(f"{name} requires dock_throughput in init")
            payload = self.COMMANDS[name](self, params)
            return {"status": "ok", "payload": payload if self.has_cargo else without_cargo(payload)}
        except CommandError as e:
            return {"status": "error", "payload": {"message": str(e)}}
        except Exception as e:  # a bug or malformed input; keep running
            return {"status": "error", "payload": {"message": f"internal error: {e!r}"}}

    def _parse(self, line: str) -> tuple[str, dict]:
        """Split a raw line into a known command name and its parameters."""
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            raise CommandError("invalid JSON")
        if not isinstance(message, dict):
            raise CommandError("command must be a JSON object")
        if not isinstance(message.get("parameters"), dict):
            raise CommandError("parameters must be an object")
        name = message.get("command")
        if not isinstance(name, str) or name not in self.COMMANDS:
            raise CommandError(f"unknown command: {name}")
        return name, message["parameters"]

    def _vessel(self, vessel_id: str) -> dict:
        """Return the vessel's committed state, or reject an unknown vessel_id."""
        if vessel_id not in self.committed["vessels"]:
            raise CommandError(f"unknown vessel {vessel_id}")
        return self.committed["vessels"][vessel_id]

    def _check_destination(self, destination) -> None:
        """Reject a destination that is not a valid location index."""
        if not is_index(destination, len(self.travel_times)):
            raise CommandError(f"destination {destination} is out of range")

    def _use_operation(self, location: int) -> None:
        """Count one cargo operation at location, or reject it if the dock is at its limit."""
        used = self.ops.get(location, 0) + 1
        limit = self.dock_throughput[location]
        if used > limit:
            raise CommandError(
                f"transfer of {used} operations exceeds dock throughput of {limit} at location {location}"
            )
        self.ops[location] = used

    def _check_manifest(self, manifest: list[dict]) -> None:
        """Reject the command if any cargo_manifest entry is out of range."""
        if manifest and not self.has_cargo:
            raise CommandError("cargo_manifest requires dock_throughput in init")
        n = len(self.travel_times)
        for entry in manifest:
            if not (
                is_index(entry["location"], n)
                and is_index(entry["destination"], n)
                and is_int(entry["quantity"])
                and entry["quantity"] > 0
            ):
                raise CommandError("invalid cargo_manifest entry")

    def _add_manifest(self, manifest: list[dict]) -> None:
        """Add cargo_manifest units to dock inventory in the committed state."""
        for entry in manifest:
            add_cargo(
                self.committed["cargo"],
                entry["quantity"],
                location=entry["location"],
                destination=entry["destination"],
            )

    def _check_setup(self, travel_times, dock_throughput, vessels) -> None:
        """Reject an init whose map, docks or vessels are invalid."""
        n = len(travel_times) if isinstance(travel_times, list) else 0
        if n == 0 or not all(
            isinstance(row, list) and len(row) == n and all(is_int(t) for t in row)
            for row in travel_times
        ):
            raise CommandError("travel_times must be a non-empty square matrix of integers")
        for i, row in enumerate(travel_times):
            for j, t in enumerate(row):
                if (i == j and t != 0) or (i != j and t <= 0):
                    raise CommandError(
                        "travel_times must be 0 on the diagonal and positive elsewhere"
                    )
        if dock_throughput is not None and not (  # absent means the base problem
            isinstance(dock_throughput, list)
            and len(dock_throughput) == n
            and all(is_int(t) and t > 0 for t in dock_throughput)
        ):
            raise CommandError("dock_throughput must be a positive integer for each location")
        if not isinstance(vessels, list):
            raise CommandError("vessels must be a list")
        seen = set()
        for vessel in vessels:
            if not (
                isinstance(vessel, dict)
                and isinstance(vessel.get("id"), str)
                and is_index(vessel.get("location"), n)
            ):
                raise CommandError("each vessel needs a string id and a valid location")
            if vessel["id"] in seen:
                raise CommandError(f"duplicate vessel id: {vessel['id']}")
            seen.add(vessel["id"])

    def init(self, params: dict) -> dict:
        """Build the world at tick 0 from travel_times, dock_throughput, vessels and cargo."""
        if self.committed is not None:
            raise CommandError("simulation already initialized")
        self._check_setup(params.get("travel_times"), params.get("dock_throughput"), params.get("vessels"))
        self.travel_times = params["travel_times"]
        self.has_cargo = params.get("dock_throughput") is not None
        self.dock_throughput = params.get("dock_throughput") or []
        manifest = params.get("cargo_manifest", [])
        self._check_manifest(manifest)
        vessels = {
            v["id"]: {"state": "idle", "location": v["location"], "cargo": []}
            for v in params["vessels"]
        }
        self.history = [{"tick": 0, "vessels": vessels, "cargo": []}]
        self._add_manifest(manifest)
        self.planned = copy.deepcopy(self.committed)
        return self.planned

    def get_state(self, params: dict) -> dict:
        """Return the planned state."""
        return self.planned

    def get_state_at(self, params: dict) -> dict:
        """Return the committed state at a past or current tick."""
        tick = params["tick"]
        current = self.committed["tick"]
        if not is_int(tick):
            raise CommandError("tick must be an integer")
        if tick < 0:  # checked explicitly: history[-1] would silently return the latest state
            raise CommandError(f"tick {tick} is before the start of the simulation")
        if tick > current:
            raise CommandError(f"tick {tick} is in the future (current tick: {current})")
        return self.history[tick]

    def set_destination(self, params: dict) -> dict:
        """Send an idle vessel toward a location, replacing any earlier order this tick."""
        vessel_id = params["vessel_id"]
        destination = params["destination"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "idle":
            raise CommandError(f"vessel {vessel_id} is not idle")
        self._check_destination(destination)
        if destination == vessel["location"]:
            raise CommandError(f"vessel {vessel_id} is already at location {destination}")
        self.planned["vessels"][vessel_id] = {
            "state": "transit",
            "from": vessel["location"],
            "to": destination,
            "arrives_at_tick": self.committed["tick"]
            + self.travel_times[vessel["location"]][destination],
            "cargo": self.planned["vessels"][vessel_id]["cargo"],
        }
        return self.planned

    def dock(self, params: dict) -> dict:
        """Park an idle vessel at its current location, replacing any earlier order this tick."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "idle":
            raise CommandError(f"vessel {vessel_id} is not idle")
        self.planned["vessels"][vessel_id] = {
            "state": "docked",
            "location": vessel["location"],
            "cargo": self.planned["vessels"][vessel_id]["cargo"],
        }
        return self.planned

    def undock(self, params: dict) -> dict:
        """Return a docked vessel to idle at its current location."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "docked":
            raise CommandError(f"vessel {vessel_id} is not docked")
        self.planned["vessels"][vessel_id] = {
            "state": "idle",
            "location": vessel["location"],
            "cargo": self.planned["vessels"][vessel_id]["cargo"],
        }
        return self.planned

    def _check_load(self, location: int, destination: int) -> dict:
        """Return the planned dock entry a load would take from, or reject the load."""
        self._check_destination(destination)
        entry = find_cargo(self.planned["cargo"], location=location, destination=destination)
        if entry is None:
            raise CommandError(f"no cargo for destination {destination} at location {location}")
        return entry

    def _move_load(self, vessel_id: str, entry: dict) -> None:
        """Move one unit of a checked dock entry onto the vessel."""
        destination = entry["destination"]
        take_cargo(self.planned["cargo"], entry)
        add_cargo(self.planned["vessels"][vessel_id]["cargo"], 1, destination=destination)

    def _check_unload(self, vessel_id: str, destination: int) -> dict:
        """Return the planned vessel entry an unload would take from, or reject the unload."""
        self._check_destination(destination)
        entry = find_cargo(self.planned["vessels"][vessel_id]["cargo"], destination=destination)
        if entry is None:
            raise CommandError(f"vessel {vessel_id} has no cargo for destination {destination}")
        return entry

    def _move_unload(self, vessel_id: str, location: int, entry: dict) -> None:
        """Move one unit of a checked vessel entry to the dock, delivering it if it has arrived."""
        destination = entry["destination"]
        take_cargo(self.planned["vessels"][vessel_id]["cargo"], entry)
        if destination != location:  # cargo unloaded at its destination is delivered
            add_cargo(self.planned["cargo"], 1, location=location, destination=destination)

    def load(self, params: dict) -> dict:
        """Move one unit of cargo from the dock onto a docked vessel."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "docked":
            raise CommandError(f"vessel {vessel_id} is not docked")
        entry = self._check_load(vessel["location"], params["destination"])
        self._use_operation(vessel["location"])
        self._move_load(vessel_id, entry)
        return self.planned

    def unload(self, params: dict) -> dict:
        """Move one unit of cargo from a docked vessel to the dock, delivering it if it has arrived."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "docked":
            raise CommandError(f"vessel {vessel_id} is not docked")
        entry = self._check_unload(vessel_id, params["destination"])
        self._use_operation(vessel["location"])
        self._move_unload(vessel_id, vessel["location"], entry)
        return self.planned

    def swap(self, params: dict) -> dict:
        """Load one unit and unload another as a single cargo operation."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "docked":
            raise CommandError(f"vessel {vessel_id} is not docked")
        location = vessel["location"]
        # Both halves are checked before either moves: the swap is simultaneous.
        load_entry = self._check_load(location, params["load_destination"])
        unload_entry = self._check_unload(vessel_id, params["unload_destination"])
        self._use_operation(location)
        self._move_load(vessel_id, load_entry)
        self._move_unload(vessel_id, location, unload_entry)
        return self.planned

    def tick(self, params: dict) -> dict:
        """Commit the planned state, advance one tick, resolve arrivals, and add new cargo."""
        manifest = params.get("cargo_manifest", [])
        self._check_manifest(manifest)  # before committing, so a rejected tick changes nothing
        self.history.append(self.planned)  # the plan becomes the committed state
        self.committed["tick"] += 1
        self.ops = {}
        for vessel_id, vessel in self.committed["vessels"].items():
            if vessel["state"] == "transit" and vessel["arrives_at_tick"] == self.committed["tick"]:
                self.committed["vessels"][vessel_id] = {
                    "state": "idle",
                    "location": vessel["to"],
                    "cargo": vessel["cargo"],
                }
        self._add_manifest(manifest)
        self.planned = copy.deepcopy(self.committed)
        return self.planned

    # Follow-on 1 commands, rejected when init had no dock_throughput.
    CARGO_COMMANDS = {"dock", "undock", "load", "unload", "swap"}

    # Command name -> handler. Adding a command means adding one line here.
    COMMANDS = {
        "init": init,
        "get_state": get_state,
        "get_state_at": get_state_at,
        "set_destination": set_destination,
        "dock": dock,
        "undock": undock,
        "load": load,
        "unload": unload,
        "swap": swap,
        "tick": tick,
    }


def main() -> None:
    sim = Simulation()
    for line in sys.stdin:
        if line.strip():  # blank lines are not commands
            print(json.dumps(sim.handle(line)), flush=True)


if __name__ == "__main__":
    main()
