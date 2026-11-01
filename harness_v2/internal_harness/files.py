"""Application-level file policy. This is NOT an operating-system sandbox."""

import hashlib
import os
from pathlib import Path
import tempfile


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        for name in ("inputs", "work", "outputs", ".state"):
            (self.root / name).mkdir(exist_ok=True)

    def resolve(self, path: str, write: bool = False) -> Path:
        raw = Path(path)
        if raw.is_absolute() or raw.drive or ".." in raw.parts or ":" in path:
            raise PermissionError("Use workspace-relative paths without '..' or drive names")
        # Reject links/junctions even when they point inside the workspace.
        current = self.root
        for part in raw.parts:
            current /= part
            if current.is_symlink() or (hasattr(current, "is_junction") and current.is_junction()):
                raise PermissionError("Links and junctions are not accessible")
        target = (self.root / raw).resolve()
        if not target.is_relative_to(self.root):
            raise PermissionError("Path escapes workspace")
        rel = target.relative_to(self.root)
        if any(part.startswith(".") for part in rel.parts):
            raise PermissionError("Hidden files and internal state are not exposed")
        if write and (not rel.parts or rel.parts[0] not in ("work", "outputs")):
            raise PermissionError("Writes are restricted to work/ and outputs/")
        return target

    def list_files(self, path: str = ".", limit: int = 100) -> dict:
        """List immediate children of a workspace directory; hidden files are excluded."""
        if not 1 <= limit <= 500:
            raise ValueError("limit must be 1..500")
        directory = self.resolve(path)
        entries = []
        for child in directory.iterdir():
            try:
                checked = self.resolve(child.relative_to(self.root).as_posix())
            except PermissionError:
                continue
            entries.append({"path": checked.relative_to(self.root).as_posix(),
                            "directory": checked.is_dir(), "bytes": checked.stat().st_size})
            if len(entries) > limit:
                break
        return {"entries": entries[:limit], "truncated": len(entries) > limit}

    def read_file(self, path: str, offset: int = 0, limit: int = 16000) -> dict:
        """Read a UTF-8 byte window. Use next_offset for large files; do not load entire KGs."""
        if offset < 0 or not 1 <= limit <= 64000:
            raise ValueError("offset >= 0, limit 1..64000 required")
        target = self.resolve(path)
        with target.open("rb") as stream:
            stream.seek(offset)
            chunk = stream.read(limit)
            more = bool(stream.read(1))
        result = {"path": path, "content": chunk.decode("utf-8", errors="replace"),
                  "next_offset": offset + len(chunk), "truncated": more}
        # Hash is useful for small editable files. Avoid hashing huge inputs on every read.
        if target.stat().st_size <= 2_000_000:
            result["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        return result

    def search_files(self, query: str, path: str = ".", limit: int = 20) -> dict:
        """Literal UTF-8 search, bounded to 200 files and 8 MB per file; reports omissions."""
        if not query or not 1 <= limit <= 100:
            raise ValueError("Nonempty query and limit 1..100 required")
        base = self.resolve(path)
        candidates = [base] if base.is_file() else base.rglob("*")
        hits, skipped, scanned = [], 0, 0
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                target = self.resolve(candidate.relative_to(self.root).as_posix())
            except PermissionError:
                skipped += 1
                continue
            if scanned >= 200:
                return {"hits": hits, "skipped": skipped, "truncated": True}
            scanned += 1
            if target.stat().st_size > 8_000_000:
                skipped += 1
                continue
            try:
                content = target.read_text(encoding="utf-8")
            except UnicodeError:
                skipped += 1
                continue
            pos = content.casefold().find(query.casefold())
            if pos >= 0:
                hits.append({"path": target.relative_to(self.root).as_posix(),
                             "snippet": content[max(0, pos - 100):pos + 300]})
            if len(hits) >= limit:
                return {"hits": hits, "skipped": skipped, "truncated": True}
        return {"hits": hits, "skipped": skipped, "truncated": bool(skipped)}

    def write_file(self, path: str, content: str, expected_sha256: str = "") -> dict:
        """Create a UTF-8 file; overwrites require the current SHA-256 from read_file."""
        if len(content.encode("utf-8")) > 2_000_000:
            raise ValueError("Tool writes are limited to 2 MB; use a program for bulk data")
        target = self.resolve(path, write=True)
        if target.exists():
            if target.stat().st_size > 2_000_000:
                raise ValueError("File too large for text editing tool")
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            if not expected_sha256 or actual != expected_sha256:
                raise ValueError("Overwrite conflict: read the file and supply its current sha256")
        elif expected_sha256:
            raise ValueError("Expected an existing file, but it does not exist")
        target.parent.mkdir(parents=True, exist_ok=True)
        self.atomic_write(target, content)
        return {"path": path, "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()}

    def edit_file(self, path: str, old_text: str, new_text: str, expected_sha256: str) -> dict:
        """Replace exactly one occurrence, rejecting ambiguous edits and stale content."""
        target = self.resolve(path, write=True)
        if target.stat().st_size > 2_000_000:
            raise ValueError("File too large for text editing tool")
        content = target.read_bytes().decode("utf-8")
        if not old_text or content.count(old_text) != 1:
            raise ValueError("old_text must match exactly once")
        return self.write_file(path, content.replace(old_text, new_text, 1), expected_sha256)

    @staticmethod
    def atomic_write(path: Path, content: str):
        fd, name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
                stream.write(content)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
