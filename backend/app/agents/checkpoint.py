"""Checkpoints: durable enough to resume a run (M5) and to recover after a
crash or restart (M6 builds the recovery flow on top).

One JSON file per run under state/checkpoints/, rewritten atomically after
every step, so a process that dies mid-run leaves a readable checkpoint behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..config import checkpoints_dir
from .models import Checkpoint, utc_now


class CheckpointStore:
    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else checkpoints_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        return self.root / (run_id + ".json")

    def save(self, checkpoint: Checkpoint) -> Path:
        checkpoint.updated_at = utc_now()
        path = self.path_for(checkpoint.run_id)
        payload = json.dumps(
            checkpoint.model_dump(mode="json"), indent=2, ensure_ascii=False
        ) + "\n"
        handle, temporary = tempfile.mkstemp(
            dir=str(self.root), prefix="." + checkpoint.run_id + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):  # pragma: no cover - failure path
                os.unlink(temporary)
        return path

    def load(self, run_id: str) -> Checkpoint | None:
        path = self.path_for(run_id)
        if not path.exists():
            return None
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return None
        try:
            return Checkpoint.model_validate(json.loads(raw))
        except Exception:
            # A torn checkpoint must not break the run that is still going.
            return None

    def latest(self) -> Checkpoint | None:
        candidates = sorted(
            self.root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
        )
        for path in candidates:
            checkpoint = self.load(path.stem)
            if checkpoint is not None:
                return checkpoint
        return None

    def delete(self, run_id: str) -> bool:
        path = self.path_for(run_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def runs(self) -> list[str]:
        return sorted(path.stem for path in self.root.glob("*.json"))
