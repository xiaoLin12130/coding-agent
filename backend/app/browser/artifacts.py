"""Artifact storage for browser runs.

Every run gets its own directory under runs/ (override with
CODING_AGENT_RUNS_DIR): screenshots, DOM snapshots and JSON logs are written
there so a failed run can be inspected after the fact.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import runs_dir as _default_runs_dir
from .models import BrowserArtifacts


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


class ArtifactStore:
    def __init__(
        self,
        base_dir: Path | str | None = None,
        run_name: str | None = None,
        run_dir: Path | str | None = None,
    ) -> None:
        if run_dir is not None:
            self.run_dir = Path(run_dir)
        else:
            base = Path(base_dir) if base_dir is not None else _default_runs_dir()
            suffix = f"-{run_name}" if run_name else ""
            self.run_dir = base / f"{_timestamp()}{suffix}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._counters: dict[str, int] = {}
        # Paths recorded while the run happens; exposed via collect().
        self.screenshots: list[str] = []
        self.dom_snapshots: list[str] = []
        self.logs: list[str] = []

    def _next(self, label: str) -> int:
        self._counters[label] = self._counters.get(label, 0) + 1
        return self._counters[label]

    def next_path(self, label: str, suffix: str) -> Path:
        return self.run_dir / f"{label}-{self._next(label)}{suffix}"

    def write_text(self, name: str, payload: str) -> Path:
        path = self.run_dir / name
        path.write_text(payload, encoding="utf-8")
        return path

    def write_json(self, name: str, payload: Any) -> Path:
        path = self.run_dir / name
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        return path

    def collect(self) -> BrowserArtifacts:
        """Snapshot of everything written for this run."""
        return BrowserArtifacts(
            run_dir=str(self.run_dir),
            screenshots=list(self.screenshots),
            dom_snapshots=list(self.dom_snapshots),
            logs=list(self.logs),
        )
