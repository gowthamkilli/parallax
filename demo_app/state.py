"""Shared local state: latest fused result + event log.

Persisted to a JSON file on disk (demo_app/state.json) as well as kept
in-memory, satisfying "shared local JSON/state file" literally -- the HTTP
server below is just a thin, same-machine convenience layer over it for the
two browser tabs to poll, not a distributed backend.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

STATE_PATH = Path(__file__).parent / "state.json"
MAX_LOG = 50

_lock = threading.Lock()
_state = {"latest_result": None, "event_log": []}


def load() -> None:
    global _state
    if STATE_PATH.exists():
        try:
            with _lock:
                _state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass  # start fresh rather than crash the server on a corrupt file


def _persist() -> None:
    STATE_PATH.write_text(json.dumps(_state, indent=2), encoding="utf-8")


def get_state() -> dict:
    with _lock:
        return json.loads(json.dumps(_state))  # cheap deep copy, JSON-safe by construction


def add_result(result: dict) -> None:
    with _lock:
        _state["latest_result"] = result
        _state["event_log"].insert(0, result)
        del _state["event_log"][MAX_LOG:]
        _persist()
