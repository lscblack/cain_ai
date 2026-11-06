"""VoiceStorageService: where voice audio lives, and the only code that touches it.

    <voice_home>/users/<user_id>/profiles/<profile_id>/...
    <voice_home>/users/<user_id>/generations/<generation_id>/...
    <voice_home>/tmp/...

Paths are built from UUIDs and fixed names, never from client input, and every
resolved path is checked to stay inside the storage root. Files are never overwritten:
a new reference recording gets a new versioned name.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import get_settings


class StorageError(Exception):
    pass


class VoiceStorageService:
    def __init__(self, root: Path | str | None = None) -> None:
        self.home = Path(root or get_settings().voice_home).expanduser().resolve()
        self.root = self.home / "users"
        self.tmp_root = self.home / "tmp"

    def _ensure(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        return path

    def resolve(self, rel_path: str) -> Path:
        full = (self.root / rel_path).resolve()
        if not full.is_relative_to(self.root):
            raise StorageError("path escapes voice storage")
        return full

    def rel(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.root))

    def profile_dir(self, user_id: uuid.UUID, profile_id: uuid.UUID) -> Path:
        return self._ensure(self.root / str(user_id) / "profiles" / str(profile_id))

    def generation_dir(self, user_id: uuid.UUID, generation_id: uuid.UUID) -> Path:
        return self._ensure(self.root / str(user_id) / "generations" / str(generation_id))

    @staticmethod
    def new_name(stem: str, suffix: str) -> str:
        return f"{stem}-{uuid.uuid4().hex[:12]}{suffix}"

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def delete_file(self, rel_path: str) -> None:
        try:
            self.resolve(rel_path).unlink(missing_ok=True)
        except StorageError:
            pass

    def delete_profile_tree(self, user_id: uuid.UUID, profile_id: uuid.UUID) -> None:
        # uuid.UUID typed on purpose: this can only ever remove one profile's own folder.
        target = self.root / str(uuid.UUID(str(user_id))) / "profiles" / str(uuid.UUID(str(profile_id)))
        if target.is_dir() and target.resolve().is_relative_to(self.root):
            shutil.rmtree(target, ignore_errors=True)

    def delete_generation_tree(self, user_id: uuid.UUID, generation_id: uuid.UUID) -> None:
        target = self.root / str(uuid.UUID(str(user_id))) / "generations" / str(uuid.UUID(str(generation_id)))
        if target.is_dir() and target.resolve().is_relative_to(self.root):
            shutil.rmtree(target, ignore_errors=True)

    @contextmanager
    def temp_dir(self) -> Iterator[Path]:
        self._ensure(self.tmp_root)
        path = Path(tempfile.mkdtemp(prefix="v-", dir=self.tmp_root))
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def sweep_temp(self, older_than_s: int = 3600) -> int:
        """Remove temp audio left behind by a killed process."""
        if not self.tmp_root.is_dir():
            return 0
        removed = 0
        cutoff = time.time() - older_than_s
        for child in self.tmp_root.iterdir():
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed

    def disk_free_bytes(self) -> int:
        self._ensure(self.home)
        return shutil.disk_usage(self.home).free


def get_storage() -> VoiceStorageService:
    return VoiceStorageService()


def write_atomic(path: Path, data: bytes) -> None:
    if path.exists():
        raise StorageError(f"refusing to overwrite {path.name}")
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.chmod(tmp, 0o600)
    tmp.rename(path)
