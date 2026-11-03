from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

from .models import PhotoMeta, norm_path

Progress = Callable[[int, int], None]

_TAGS = ("-Make", "-Model", "-DateTimeOriginal", "-SubSecTimeOriginal")


class MetadataReader(Protocol):
    def read(self, paths: Sequence[Path]) -> dict[Path, PhotoMeta]: ...


class ExifToolError(RuntimeError):
    pass


class ExifToolNotFound(ExifToolError):
    pass


def find_exiftool() -> str:
    env = os.environ.get("PHOTOIMPORTER_EXIFTOOL")
    if env and Path(env).is_file():
        return env
    found = shutil.which("exiftool")
    if found:
        return found
    raise ExifToolNotFound(
        "ExifTool was not found. Install it from https://exiftool.org and put exiftool.exe "
        "on PATH, or set PHOTOIMPORTER_EXIFTOOL to its full path."
    )


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _date(value: object) -> str | None:
    text = _text(value)
    if text is None or text.startswith("0000"):
        return None
    return text


class ExifToolReader:
    def __init__(self, exe: str | None = None):
        self.exe = exe or find_exiftool()

    def read(self, paths: Sequence[Path]) -> dict[Path, PhotoMeta]:
        if not paths:
            return {}
        with tempfile.TemporaryDirectory() as tmp:
            argfile = Path(tmp) / "files.txt"
            argfile.write_text("\n".join(str(p) for p in paths) + "\n", encoding="utf-8")
            proc = subprocess.run(
                [
                    self.exe,
                    "-json",
                    "-fast",
                    "-charset",
                    "filename=utf8",
                    *_TAGS,
                    "-@",
                    str(argfile),
                ],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        output = proc.stdout.decode("utf-8", errors="replace").strip()
        stderr = proc.stderr.decode("utf-8", errors="replace").strip()
        try:
            records = json.loads(output) if output else []
        except json.JSONDecodeError as exc:
            raise ExifToolError(f"Unreadable ExifTool output: {exc}. {stderr}") from exc

        by_norm = {norm_path(p): p for p in paths}
        metas: dict[Path, PhotoMeta] = {}
        for record in records:
            path = by_norm.get(norm_path(record.get("SourceFile", "")))
            if path is not None:
                metas[path] = PhotoMeta(
                    make=_text(record.get("Make")),
                    model=_text(record.get("Model")),
                    capture_time=_date(record.get("DateTimeOriginal")),
                    subsec=_text(record.get("SubSecTimeOriginal")),
                )
        # Never guess "no EXIF" for a missing record: it would be cached and break dedup later.
        missing = [p for p in paths if p not in metas]
        if missing:
            raise ExifToolError(
                f"ExifTool returned no data for {len(missing)} of {len(paths)} files "
                f"(first: {missing[0]}, exit code {proc.returncode}). {stderr}"
            )
        return metas


def read_metadata(
    reader: MetadataReader,
    paths: Sequence[Path],
    progress: Progress | None = None,
    batch_size: int = 200,
) -> dict[Path, PhotoMeta]:
    result: dict[Path, PhotoMeta] = {}
    total = len(paths)
    for start in range(0, total, batch_size):
        result.update(reader.read(paths[start : start + batch_size]))
        if progress:
            progress(min(start + batch_size, total), total)
    return result
