from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol
from uuid import UUID


class DocumentStorage(Protocol):
    def save(
        self,
        *,
        candidate_profile_id: UUID,
        document_id: UUID,
        original_filename: str,
        content: bytes,
    ) -> str: ...

    def read(self, storage_key: str) -> bytes: ...

    def delete(self, storage_key: str) -> None: ...


def sanitize_filename(filename: str) -> str:
    base_name = Path(filename).name.strip() or "document"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", base_name).strip(".-")
    return safe[:180] or "document"


class LocalDocumentStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(
        self,
        *,
        candidate_profile_id: UUID,
        document_id: UUID,
        original_filename: str,
        content: bytes,
    ) -> str:
        safe_name = sanitize_filename(original_filename)
        relative_path = Path(str(candidate_profile_id)) / f"{document_id}-{safe_name}"
        target = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if root not in target.parents:
            msg = "Resolved document storage path escaped the storage root."
            raise ValueError(msg)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return relative_path.as_posix()

    def read(self, storage_key: str) -> bytes:
        relative_path = Path(storage_key)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            msg = "Invalid document storage key."
            raise ValueError(msg)
        target = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if root not in target.parents:
            msg = "Resolved document storage path escaped the storage root."
            raise ValueError(msg)
        return target.read_bytes()

    def delete(self, storage_key: str) -> None:
        relative_path = Path(storage_key)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            msg = "Invalid document storage key."
            raise ValueError(msg)
        target = (self.root / relative_path).resolve()
        root = self.root.resolve()
        if root not in target.parents:
            msg = "Resolved document storage path escaped the storage root."
            raise ValueError(msg)
        if target.exists():
            target.unlink()


class InMemoryDocumentStorage:
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def save(
        self,
        *,
        candidate_profile_id: UUID,
        document_id: UUID,
        original_filename: str,
        content: bytes,
    ) -> str:
        safe_name = sanitize_filename(original_filename)
        key = f"{candidate_profile_id}/{document_id}-{safe_name}"
        self._objects[key] = content
        return key

    def read(self, storage_key: str) -> bytes:
        return self._objects[storage_key]

    def delete(self, storage_key: str) -> None:
        self._objects.pop(storage_key, None)
