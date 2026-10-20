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
        self.dock_throughput: list[int] = []  # max cargo operations per dock per tick
        self.ops: dict[int, int] = {}  # cargo operations used per location since the last tick
        self.committed: dict | None = None  # world state at the current tick
        self.planned: dict | None = None  # committed state plus commands since the last tick

    def handle(self, line: str) -> dict:
        """Process one input line and return exactly one response envelope."""
        try:
            name, params = self._parse(line)
            if self.committed is None and name != "init":
                raise CommandError("simulation not initialized")
            return {"status": "ok", "payload": self.COMMANDS[name](self, params)}
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
        n = len(self.travel_times)
        for entry in manifest:
            if not (
                0 <= entry["location"] < n
                and 0 <= entry["destination"] < n
                and isinstance(entry["quantity"], int)
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

    def init(self, params: dict) -> dict:
        """Build the world at tick 0 from travel_times, dock_throughput, vessels and cargo."""
        if self.committed is not None:
            raise CommandError("simulation already initialized")
        self.travel_times = params["travel_times"]
        self.dock_throughput = params["dock_throughput"]
        manifest = params.get("cargo_manifest", [])
        self._check_manifest(manifest)
        vessels = {
            v["id"]: {"state": "idle", "location": v["location"], "cargo": []}
            for v in params["vessels"]
        }
        self.committed = {"tick": 0, "vessels": vessels, "cargo": []}
        self._add_manifest(manifest)
        self.planned = copy.deepcopy(self.committed)
        return self.planned

    def get_state(self, params: dict) -> dict:
        """Return the planned state."""
        return self.planned

    def set_destination(self, params: dict) -> dict:
        """Send an idle vessel toward a location, replacing any earlier order this tick."""
        vessel_id = params["vessel_id"]
        destination = params["destination"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "idle":
            raise CommandError(f"vessel {vessel_id} is not idle")
        if not 0 <= destination < len(self.travel_times):
            raise CommandError(f"destination {destination} is out of range")
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

    def load(self, params: dict) -> dict:
        """Move one unit of cargo from the dock onto a docked vessel."""
        vessel_id = params["vessel_id"]
        destination = params["destination"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "docked":
            raise CommandError(f"vessel {vessel_id} is not docked")
        location = vessel["location"]
        dock_cargo = self.planned["cargo"]
        entry = find_cargo(dock_cargo, location=location, destination=destination)
        if entry is None:
            raise CommandError(f"no cargo for destination {destination} at location {location}")
        self._use_operation(location)
        take_cargo(dock_cargo, entry)
        add_cargo(self.planned["vessels"][vessel_id]["cargo"], 1, destination=destination)
        return self.planned

    def unload(self, params: dict) -> dict:
        """Move one unit of cargo from a docked vessel to the dock, delivering it if it has arrived."""
        vessel_id = params["vessel_id"]
        destination = params["destination"]
        vessel = self._vessel(vessel_id)
        if vessel["state"] != "docked":
            raise CommandError(f"vessel {vessel_id} is not docked")
        location = vessel["location"]
        vessel_cargo = self.planned["vessels"][vessel_id]["cargo"]
        entry = find_cargo(vessel_cargo, destination=destination)
        if entry is None:
            raise CommandError(f"vessel {vessel_id} has no cargo for destination {destination}")
        self._use_operation(location)
        take_cargo(vessel_cargo, entry)
        if destination != location:  # cargo unloaded at its destination is delivered
            add_cargo(self.planned["cargo"], 1, location=location, destination=destination)
        return self.planned

    def tick(self, params: dict) -> dict:
        """Commit the planned state, advance one tick, resolve arrivals, and add new cargo."""
        manifest = params.get("cargo_manifest", [])
        self._check_manifest(manifest)  # before committing, so a rejected tick changes nothing
        self.committed = self.planned
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

    # Command name -> handler. Adding a command means adding one line here.
    COMMANDS = {
        "init": init,
        "get_state": get_state,
        "set_destination": set_destination,
        "dock": dock,
        "undock": undock,
        "load": load,
        "unload": unload,
        "tick": tick,
    }


def main() -> None:
    sim = Simulation()
    for line in sys.stdin:
        if line.strip():  # blank lines are not commands
            print(json.dumps(sim.handle(line)), flush=True)


if __name__ == "__main__":
    main()
