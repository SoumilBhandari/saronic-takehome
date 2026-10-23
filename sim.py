# =============================================================================
#  Program Description:  Fleet simulation engine. Reads one JSON command per
#                        line from stdin and writes one JSON response per line
#                        to stdout, reporting every vessel and dock.
# =============================================================================

import copy
import json
import sys


class CommandError(Exception):
    """A rejected command; its message becomes the error response."""


# =============================================================================
#  Input checks
# =============================================================================

def is_int(value) -> bool:
    """True for an int that isn't a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_index(value, n: int) -> bool:
    """True for a valid location index, 0 to n-1."""
    return is_int(value) and 0 <= value < n


# =============================================================================
#  Cargo lists
# =============================================================================

def find_cargo(entries: list[dict], **key) -> dict | None:
    """Return the entry matching every field in key, or None."""
    for entry in entries:
        if all(entry[k] == v for k, v in key.items()):
            return entry
    return None


def add_cargo(entries: list[dict], quantity: int, **key) -> None:
    """Add units to the matching entry, or append a new one."""
    entry = find_cargo(entries, **key)
    if entry is None:
        entries.append({**key, "quantity": quantity})
    else:
        entry["quantity"] += quantity


def take_cargo(entries: list[dict], entry: dict) -> None:
    """Remove one unit from entry, dropping it at zero."""
    entry["quantity"] -= 1
    if entry["quantity"] == 0:
        entries.remove(entry)


def without_cargo(state: dict) -> dict:
    """Return the state with all cargo fields removed (base problem output)."""
    return {
        "tick": state["tick"],
        "vessels": {
            vessel_id: {k: v for k, v in vessel.items() if k != "cargo"}
            for vessel_id, vessel in state["vessels"].items()
        },
    }


# =============================================================================
#  Simulation
# =============================================================================

class Simulation:
    COMMANDS = {
        "init", "tick", "set_destination", "get_state",
        "dock", "undock", "load", "unload", "swap",
        "get_state_at",
    }
    CARGO_COMMANDS = {"dock", "undock", "load", "unload", "swap"}  # need dock_throughput

    def __init__(self) -> None:
        self.travel_times: list[list[int]] = []  # travel_times[i][j] = ticks from i to j
        self.has_cargo = False  # True when init included dock_throughput
        self.dock_throughput: list[int] = []  # max cargo operations per dock per tick
        self.ops: dict[int, int] = {}  # cargo operations used per dock this tick
        self.history: list[dict] = []  # history[t] = committed state at tick t
        self.planned: dict | None = None  # committed state + this tick's commands

    @property
    def committed(self) -> dict | None:
        """The current committed state: the latest history entry, or None before init."""
        return self.history[-1] if self.history else None

    # =========================================================================
    #  Protocol
    # =========================================================================

    def handle(self, line: str) -> dict:
        """Process one input line and return exactly one ok or error response."""
        try:
            name, params = self._parse(line)
            if self.committed is None and name != "init":
                raise CommandError("simulation not initialized")
            if name in self.CARGO_COMMANDS and not self.has_cargo:
                raise CommandError(f"{name} requires dock_throughput in init")
            payload = getattr(self, name)(params)
            return {"status": "ok", "payload": payload if self.has_cargo else without_cargo(payload)}
        except CommandError as e:
            return {"status": "error", "payload": {"message": str(e)}}
        except Exception as e:  # a bug or malformed input; keep running
            return {"status": "error", "payload": {"message": f"internal error: {e!r}"}}

    def _parse(self, line: str) -> tuple[str, dict]:
        """Return the command name and parameters, or reject a malformed line."""
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

    # =========================================================================
    #  Vessel helpers
    # =========================================================================

    def _vessel(self, vessel_id: str, state: str) -> dict:
        """Return the vessel's committed record; reject it if unknown or not in `state`."""
        if vessel_id not in self.committed["vessels"]:
            raise CommandError(f"unknown vessel {vessel_id}")
        vessel = self.committed["vessels"][vessel_id]
        if vessel["state"] != state:
            raise CommandError(f"vessel {vessel_id} is not {state}")
        return vessel

    def _plan(self, vessel_id: str, fields: dict) -> None:
        """Set a vessel's planned mode, keeping its cargo."""
        cargo = self.planned["vessels"][vessel_id]["cargo"]
        self.planned["vessels"][vessel_id] = {**fields, "cargo": cargo}

    def _check_destination(self, destination) -> None:
        """Reject a destination that isn't a valid location."""
        if not is_index(destination, len(self.travel_times)):
            raise CommandError(f"destination {destination} is out of range")

    # =========================================================================
    #  Setup checks
    # =========================================================================

    def _check_setup(self, travel_times, dock_throughput, vessels) -> None:
        """Reject an invalid map, dock list or vessel list in init."""
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

    def _check_manifest(self, manifest: list[dict]) -> None:
        """Reject the command if any cargo_manifest entry is invalid."""
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
        """Add manifest cargo to the committed docks."""
        for entry in manifest:
            add_cargo(
                self.committed["cargo"],
                entry["quantity"],
                location=entry["location"],
                destination=entry["destination"],
            )

    # =========================================================================
    #  Cargo moves
    # =========================================================================

    def _use_operation(self, location: int) -> None:
        """Count one operation at the dock; reject if it's at its limit this tick."""
        used = self.ops.get(location, 0) + 1
        limit = self.dock_throughput[location]
        if used > limit:
            raise CommandError(
                f"transfer of {used} operations exceeds dock throughput of {limit} at location {location}"
            )
        self.ops[location] = used

    def _check_load(self, location: int, destination: int) -> dict:
        """Return the planned dock entry to load from, or reject the load."""
        self._check_destination(destination)
        entry = find_cargo(self.planned["cargo"], location=location, destination=destination)
        if entry is None:
            raise CommandError(f"no cargo for destination {destination} at location {location}")
        return entry

    def _move_load(self, vessel_id: str, entry: dict) -> None:
        """Move one unit from the dock entry onto the vessel."""
        destination = entry["destination"]
        take_cargo(self.planned["cargo"], entry)
        add_cargo(self.planned["vessels"][vessel_id]["cargo"], 1, destination=destination)

    def _check_unload(self, vessel_id: str, destination: int) -> dict:
        """Return the planned vessel entry to unload from, or reject the unload."""
        self._check_destination(destination)
        entry = find_cargo(self.planned["vessels"][vessel_id]["cargo"], destination=destination)
        if entry is None:
            raise CommandError(f"vessel {vessel_id} has no cargo for destination {destination}")
        return entry

    def _move_unload(self, vessel_id: str, location: int, entry: dict) -> None:
        """Move one unit to the dock, or deliver it if this is its destination."""
        destination = entry["destination"]
        take_cargo(self.planned["vessels"][vessel_id]["cargo"], entry)
        if destination != location:
            add_cargo(self.planned["cargo"], 1, location=location, destination=destination)

    # =========================================================================
    #  Base commands
    # =========================================================================

    def init(self, params: dict) -> dict:
        """Build the world at tick 0; without dock_throughput, run the base problem."""
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

    def tick(self, params: dict) -> dict:
        """Commit the plan, advance one tick, resolve arrivals and add new cargo."""
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

    def set_destination(self, params: dict) -> dict:
        """Send an idle vessel to another location, replacing any earlier order."""
        vessel_id = params["vessel_id"]
        destination = params["destination"]
        vessel = self._vessel(vessel_id, "idle")
        self._check_destination(destination)
        if destination == vessel["location"]:
            raise CommandError(f"vessel {vessel_id} is already at location {destination}")
        self._plan(vessel_id, {
            "state": "transit",
            "from": vessel["location"],
            "to": destination,
            "arrives_at_tick": self.committed["tick"]
            + self.travel_times[vessel["location"]][destination],
        })
        return self.planned

    def get_state(self, params: dict) -> dict:
        return self.planned

    # =========================================================================
    #  Follow-on 1: docks and cargo
    # =========================================================================

    def dock(self, params: dict) -> dict:
        """Dock an idle vessel at its current location."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id, "idle")
        self._plan(vessel_id, {"state": "docked", "location": vessel["location"]})
        return self.planned

    def undock(self, params: dict) -> dict:
        """Return a docked vessel to idle."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id, "docked")
        self._plan(vessel_id, {"state": "idle", "location": vessel["location"]})
        return self.planned

    def load(self, params: dict) -> dict:
        """Move one unit from the dock onto a docked vessel."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id, "docked")
        entry = self._check_load(vessel["location"], params["destination"])
        self._use_operation(vessel["location"])
        self._move_load(vessel_id, entry)
        return self.planned

    def unload(self, params: dict) -> dict:
        """Move one unit from a docked vessel to the dock."""
        vessel_id = params["vessel_id"]
        vessel = self._vessel(vessel_id, "docked")
        entry = self._check_unload(vessel_id, params["destination"])
        self._use_operation(vessel["location"])
        self._move_unload(vessel_id, vessel["location"], entry)
        return self.planned

    def swap(self, params: dict) -> dict:
        """Load one unit and unload another as one operation, checking both first."""
        vessel_id = params["vessel_id"]
        location = self._vessel(vessel_id, "docked")["location"]
        load_entry = self._check_load(location, params["load_destination"])
        unload_entry = self._check_unload(vessel_id, params["unload_destination"])
        self._use_operation(location)
        self._move_load(vessel_id, load_entry)
        self._move_unload(vessel_id, location, unload_entry)
        return self.planned

    # =========================================================================
    #  Follow-on 2: history
    # =========================================================================

    def get_state_at(self, params: dict) -> dict:
        """Return the committed state at a past or current tick."""
        tick = params["tick"]
        current = self.committed["tick"]
        if not is_int(tick):
            raise CommandError("tick must be an integer")
        if tick < 0:  # explicit: history[-1] would return the latest state
            raise CommandError(f"tick {tick} is before the start of the simulation")
        if tick > current:
            raise CommandError(f"tick {tick} is in the future (current tick: {current})")
        return self.history[tick]


# =============================================================================
#  Entry point
# =============================================================================

def main() -> None:
    """Answer each non-blank stdin line with one JSON line."""
    sim = Simulation()
    for line in sys.stdin:
        if line.strip():  # blank lines are not commands
            print(json.dumps(sim.handle(line)), flush=True)


if __name__ == "__main__":
    main()
