"""Bounded, per-agent data store. No files, pickle, or implicit globals."""
from __future__ import annotations

import json
import math


def json_copy(value, depth=0):
    """Validate plain data, preserving JSON types; tuples become lists."""
    if depth > 48:
        raise ValueError("workspace data exceeds 48 nesting levels")
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) in (list, tuple):
        return [json_copy(v, depth + 1) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: json_copy(v, depth + 1) for k, v in value.items()}
    raise ValueError("workspace accepts finite JSON data with string keys; tuples load as lists")


class Workspace:
    SCOPES = ("game", "level", "observation")

    def __init__(self, *, max_bytes=2_000_000, max_entries=128):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self._entries = {}
        self._sizes = {}
        self._level = None
        self._observation = None
        self._version = 0

    def sync(self, *, level, observation):
        """Use the real host state, including action count, not a model-supplied ID."""
        if level != self._level:
            self._clear("level")
        if observation != self._observation or level != self._level:
            self._clear("observation")
            self._version += 1
        self._level, self._observation = level, observation

    def _clear(self, scope):
        for key in list(self._entries):
            if key[0] == scope:
                del self._entries[key]
                del self._sizes[key]

    def handle(self, request):
        op = request.get("op")
        scope = request.get("scope", "level")
        if scope not in self.SCOPES:
            raise ValueError("scope must be game, level, or observation")
        if op == "info":
            return dict(level=self._level, version=self._version,
                        bytes=sum(self._sizes.values()), max_bytes=self.max_bytes,
                        entries=len(self._entries), max_entries=self.max_entries)
        if op == "keys":
            return sorted(k[1] for k in self._entries if k[0] == scope)
        if op == "clear":
            self._clear(scope)
            return None
        key = request.get("key")
        if not isinstance(key, str) or not key or len(key) > 128:
            raise ValueError("workspace key must be a nonempty string of at most 128 characters")
        slot = (scope, key)
        if op == "get":
            return json_copy(self._entries.get(slot, request.get("default")))
        if op == "delete":
            found = slot in self._entries
            self._entries.pop(slot, None)
            self._sizes.pop(slot, None)
            return found
        if op != "put":
            raise ValueError("unknown workspace operation")
        expected = request.get("expected_version")
        if expected is not None and expected != self._version:
            raise ValueError("stale workspace version; re-read the current state")
        value = json_copy(request.get("value"))
        size = len(json.dumps([scope, key, value], ensure_ascii=False, allow_nan=False).encode("utf-8"))
        if size > 512_000:
            raise ValueError("workspace entry exceeds 512000 bytes; save a smaller result")
        if slot not in self._entries and len(self._entries) >= self.max_entries:
            raise ValueError("workspace entry limit reached; delete unused entries")
        if sum(self._sizes.values()) - self._sizes.get(slot, 0) + size > self.max_bytes:
            raise ValueError("workspace byte limit reached; delete unused entries")
        # Commit only after validation. Failed writes leave the old value intact.
        self._entries[slot], self._sizes[slot] = value, size
        return None
