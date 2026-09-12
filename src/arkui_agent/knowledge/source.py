"""Read-only Git/source observation; no checkout, refresh or watcher."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from typing import Callable
from pathlib import Path

from arkui_agent.repository.workspace import RepositoryWorkspace, RepositoryWorkspaceError

from .model import FileHash, SourceFingerprint


class SourceReadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FileStamp:
    path: str
    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int


def stamp(path: Path) -> FileStamp:
    info = path.stat()
    return FileStamp(str(path), info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def hash_file(path: Path) -> tuple[str, FileStamp]:
    before = stamp(path)
    with path.open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    after = stamp(path)
    if before != after:
        raise SourceReadError(f"File changed while reading: {path}")
    return checksum, after


@dataclass(frozen=True, slots=True)
class SourceObservation:
    repository: str
    revision: str | None
    dirty: bool
    fingerprint: SourceFingerprint
    stamps: tuple[FileStamp, ...]
    tracked_files: tuple[str, ...]


class GitSourceReader:
    """The caller explicitly associates a repository identity with a checkout."""

    def __init__(self, root: str | Path, *, repository: str) -> None:
        self.workspace = RepositoryWorkspace(root)
        self.repository = repository

    def _git(self, *arguments: str, allow_unborn: bool = False) -> bytes:
        try:
            result = subprocess.run(("git", "--no-optional-locks", "-C", str(self.workspace.root), *arguments),
                                    capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise SourceReadError("Git source observation unavailable.") from error
        if result.returncode != 0:
            if allow_unborn and result.returncode == 1:
                return b""
            raise SourceReadError(result.stderr.decode("utf-8", errors="replace").strip() or "Git observation failed.")
        return result.stdout

    def _state(self) -> tuple[str | None, bytes]:
        revision = self._git("rev-parse", "--verify", "--quiet", "HEAD^{commit}", allow_unborn=True).decode().strip()
        status = self._git("status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignore-submodules=none")
        return revision or None, status

    def observe(self, paths: tuple[str, ...], *,
                progress: Callable[[str, int, int, str | None], None] | None = None) -> SourceObservation:
        try:
            top = Path(self._git("rev-parse", "--show-toplevel").decode("utf-8").strip()).resolve()
            if top != self.workspace.root:
                raise SourceReadError("Source root must be the Git worktree root.")
            before = self._state()
            tracked = tuple(sorted(self._git("ls-files", "-z").decode("utf-8").strip("\0").split("\0")))
            if tracked == ("",):
                tracked = ()
            files: list[FileHash] = []
            stamps: list[FileStamp] = []
            for current, path in enumerate(paths, 1):
                actual = self.workspace.resolve(path)
                checksum, file_stamp = hash_file(actual)
                files.append(FileHash(path, checksum))
                stamps.append(file_stamp)
                if progress is not None:
                    progress("source_inventory", current, len(paths), path)
            after = self._state()
            if before != after:
                raise SourceReadError("Git revision/status changed during source observation.")
            if any(stamp(Path(item.path)) != item for item in stamps):
                raise SourceReadError("Source changed during inventory read.")
            return SourceObservation(self.repository, after[0], bool(after[1]), SourceFingerprint(tuple(files)),
                                     tuple(stamps), tracked)
        except (OSError, UnicodeError, RepositoryWorkspaceError) as error:
            raise SourceReadError(str(error)) from error
