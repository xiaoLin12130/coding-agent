"""State persistence.

Every read/write of state/project_state.json and state/memory.json goes
through StateStore so the shape stays validated by Pydantic and writes are
atomic (temp file + replace).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import AppPaths, get_paths
from .models import Memory, ProjectState


class StateStoreError(RuntimeError):
    """Raised when a state file exists but cannot be parsed as expected."""


class StateStore:
    def __init__(self, paths: AppPaths | None = None) -> None:
        self.paths = paths or get_paths()

    # -- low level ---------------------------------------------------------

    @staticmethod
    def _read_json(path: Path) -> dict:
        if not path.exists():
            return {}
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise StateStoreError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise StateStoreError(f"{path} must contain a JSON object")
        return data

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        # Atomic write: readers never observe a half-written state file.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):  # pragma: no cover - failure path
                os.unlink(tmp_name)

    # -- project state -----------------------------------------------------

    def load_project_state(self) -> ProjectState:
        return ProjectState.model_validate(
            self._read_json(self.paths.project_state_file)
        )

    def save_project_state(self, state: ProjectState) -> None:
        self._write_json(
            self.paths.project_state_file,
            state.model_dump(mode="json"),
        )

    # -- memory ------------------------------------------------------------

    def load_memory(self) -> Memory:
        return Memory.model_validate(self._read_json(self.paths.memory_file))

    def save_memory(self, memory: Memory) -> None:
        self._write_json(self.paths.memory_file, memory.model_dump(mode="json"))
