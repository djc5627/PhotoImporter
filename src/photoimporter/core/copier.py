from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .db import Database
from .exif import Progress
from .planner import ImportPlan, PlanItem


@dataclass
class CopyResult:
    import_id: int
    copied: int = 0
    skipped: int = 0
    renamed: list[Path] = field(default_factory=list)
    failed: list[tuple[Path, str]] = field(default_factory=list)


def _same_file(dest: Path, item: PlanItem) -> bool:
    stat = dest.stat()
    return stat.st_size == item.photo.size and abs(stat.st_mtime - item.photo.mtime) <= 2


def _free_name(dest: Path) -> Path:
    n = 1
    while True:
        candidate = dest.with_name(f"{dest.stem}_{n}{dest.suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _copy_one(item: PlanItem) -> tuple[str, Path]:
    dest = item.dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        if _same_file(dest, item):
            return "skipped", dest
        # A different photo with the same name, e.g. after the camera's file counter reset.
        dest = _free_name(dest)
    tmp = dest.with_name(dest.name + ".part")
    tmp.unlink(missing_ok=True)
    try:
        shutil.copy2(item.photo.path, tmp)
        if tmp.stat().st_size != item.photo.size:
            raise OSError("copied size does not match source")
        os.rename(tmp, dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return ("copied" if dest == item.dest else "renamed"), dest


def execute_plan(
    plan: ImportPlan,
    db: Database,
    progress: Progress | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> CopyResult:
    items = plan.items
    result = CopyResult(db.start_import(plan.source, plan.target_dir))
    for done, item in enumerate(items, 1):
        if should_cancel and should_cancel():
            break
        try:
            status, dest = _copy_one(item)
        except Exception as exc:
            result.failed.append((item.photo.path, str(exc)))
            db.log_import_file(result.import_id, item.photo.path, item.dest, f"failed: {exc}")
        else:
            if status == "skipped":
                result.skipped += 1
            else:
                result.copied += 1
                if status == "renamed":
                    result.renamed.append(dest)
            stat = dest.stat()
            db.upsert_file(dest, stat.st_size, stat.st_mtime, item.photo.filename, item.photo.meta)
            db.log_import_file(result.import_id, item.photo.path, dest, status)
        if progress:
            progress(done, len(items))
    return result
