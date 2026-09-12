"""Best-effort, bounded refresh telemetry; never a publication authority."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile


class RefreshProgress:
    def __init__(self, path: Path, attempt_id: str, generation: str) -> None:
        self.path = path
        self.attempt_id = attempt_id
        self.generation = generation
        self.phase = "source_inventory"
        self.current = 0
        self.total = 0
        self.current_file: str | None = None
        self._last_write = float("-inf")
        self.diagnostic: str | None = None

    def update(self, phase: str, current: int = 0, total: int = 0,
               current_file: str | None = None, *, status: str = "running") -> None:
        changed = phase != self.phase
        self.phase = phase[:64]
        self.current = max(0, current)
        self.total = max(self.current, total)
        self.current_file = current_file[:300] if current_file else None
        now = time.monotonic()
        if status == "running" and not changed and now - self._last_write < 2:
            return
        self._last_write = now
        payload = {
            "schema_version": 1, "attempt_id": self.attempt_id, "generation": self.generation,
            "phase": self.phase, "current": self.current, "total": self.total,
            "percent": round(100 * self.current / self.total, 2) if self.total else None,
            "current_file": self.current_file,
            "updated_at": datetime.now(timezone.utc).isoformat(), "status": status,
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                    prefix=".progress-", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except Exception as error:
            # This is exclusively the telemetry I/O boundary, not build work.
            self.diagnostic = "Progress reporting unavailable: " + str(error)[:300]
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as error:
                    self.diagnostic = "Progress temporary cleanup failed: " + str(error)[:300]

    def finish(self, status: str) -> None:
        self.update(self.phase, self.current, self.total, self.current_file, status=status)
