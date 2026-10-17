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


class Simulation:
    def __init__(self) -> None:
        self.travel_times: list[list[int]] = []  # travel_times[i][j] = ticks from i to j
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

    def init(self, params: dict) -> dict:
        """Build the world at tick 0 from travel_times and vessels."""
        if self.committed is not None:
            raise CommandError("simulation already initialized")
        self.travel_times = params["travel_times"]
        vessels = {v["id"]: {"state": "idle", "location": v["location"]} for v in params["vessels"]}
        self.committed = {"tick": 0, "vessels": vessels}
        self.planned = copy.deepcopy(self.committed)
        return self.planned

    def get_state(self, params: dict) -> dict:
        """Return the planned state."""
        return self.planned

    def set_destination(self, params: dict) -> dict:
        """Send an idle vessel toward a location, replacing any earlier order this tick."""
        vessel_id = params["vessel_id"]
        destination = params["destination"]
        if vessel_id not in self.committed["vessels"]:
            raise CommandError(f"unknown vessel {vessel_id}")
        vessel = self.committed["vessels"][vessel_id]
        if vessel["state"] != "idle":
            raise CommandError(f"vessel {vessel_id} is not idle")
        if not 0 <= destination < len(self.travel_times):
            raise CommandError(f"destination {destination} is out of range")
        self.planned["vessels"][vessel_id] = {
            "state": "transit",
            "from": vessel["location"],
            "to": destination,
            "arrives_at_tick": self.committed["tick"]
            + self.travel_times[vessel["location"]][destination],
        }
        return self.planned

    def tick(self, params: dict) -> dict:
        """Commit the planned state, advance one tick, and resolve arrivals."""
        raise NotImplementedError

    # Command name -> handler. Adding a command means adding one line here.
    COMMANDS = {
        "init": init,
        "get_state": get_state,
        "set_destination": set_destination,
        "tick": tick,
    }


def main() -> None:
    sim = Simulation()
    for line in sys.stdin:
        if line.strip():  # blank lines are not commands
            print(json.dumps(sim.handle(line)), flush=True)


if __name__ == "__main__":
    main()
