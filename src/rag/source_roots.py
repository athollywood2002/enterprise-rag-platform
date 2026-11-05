"""Descriptor-relative source access. Symlinks are excluded, including in-root links."""

import os
import stat
from contextlib import contextmanager
from pathlib import PurePosixPath

from .folder_parser import DocumentError


def relative_path(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise DocumentError("invalid_path", "Choose a valid relative file path.")
    if "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DocumentError("invalid_path", "Control characters and backslashes are not allowed.")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise DocumentError("invalid_path", "Paths must stay within the selected source.")
    return str(path)


@contextmanager
def open_beneath(root, relative="", directory=False):
    """No resolve-then-open race: open each component with O_NOFOLLOW and dir_fd."""
    parts = relative_path(relative).split("/") if relative else []
    fds = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        fds.append(fd)
        for i, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if i < len(parts) - 1 or directory:
                flags |= os.O_DIRECTORY
            fd = os.open(part, flags, dir_fd=fd)
            fds.append(fd)
        mode = os.fstat(fd).st_mode
        if not (stat.S_ISDIR(mode) if directory or not parts else stat.S_ISREG(mode)):
            raise OSError("Not a regular file or directory")
        yield fd
    except OSError as error:
        raise DocumentError(
            "source_unavailable",
            "Source is unavailable, changed, or is a symlink. Preview it again.",
        ) from error
    finally:
        for fd in reversed(fds):
            os.close(fd)


def browse(root, relative, limit):
    with open_beneath(root, relative, directory=True) as fd:
        entries = []
        with os.scandir(fd) as scan:
            for entry in scan:
                if len(entries) >= limit:
                    raise DocumentError(
                        "file_limit",
                        "This directory has too many entries. Select a smaller folder.",
                    )
                info = entry.stat(follow_symlinks=False)
                kind = "folder" if stat.S_ISDIR(info.st_mode) else "file"
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    kind = "excluded"
                entries.append(
                    {
                        "name": entry.name,
                        "kind": kind,
                        "size": info.st_size if kind == "file" else 0,
                    }
                )
        return sorted(entries, key=lambda e: (e["kind"] != "folder", e["name"].casefold()))


def inventory(root, relative, limit):
    files = []
    visited = 0

    def walk(path, depth):
        nonlocal visited
        if depth > 32:
            raise DocumentError("depth_limit", "Folder exceeds the 32-level nesting limit.")
        for entry in browse(root, path, limit):
            visited += 1
            if visited > limit:
                raise DocumentError(
                    "file_limit",
                    "Folder exceeds the configured entry limit. Select a smaller folder.",
                )
            child = f"{path}/{entry['name']}" if path else entry["name"]
            relative_path(child)
            if entry["kind"] == "folder":
                walk(child, depth + 1)
            else:
                files.append(
                    {"path": child, "size": entry["size"], "excluded": entry["kind"] == "excluded"}
                )

    walk(relative, 0)
    return files
