"""Fleet simulation engine.

Reads newline-delimited JSON commands from stdin and writes exactly one JSON
response per command to stdout.

Usage: python3 sim.py < commands.jsonl
"""

import json
import sys


class CommandError(Exception):
    """A rejected command. Its message is returned as the error response."""


class Simulation:
    def __init__(self) -> None:
        self.committed: dict | None = None  # world state at the current tick
        self.planned: dict | None = None  # committed state plus commands since the last tick

    def handle(self, line: str) -> dict:
        """Process one input line and return exactly one response envelope."""
        try:
            name, params = self._parse(line)
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
        raise NotImplementedError

    def get_state(self, params: dict) -> dict:
        """Return the planned state."""
        raise NotImplementedError

    def set_destination(self, params: dict) -> dict:
        """Send an idle vessel toward a location, replacing any earlier order this tick."""
        raise NotImplementedError

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
