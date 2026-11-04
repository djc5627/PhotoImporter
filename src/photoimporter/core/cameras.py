"""Suggest folder names for cameras from how the library is already organised."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .db import Database
from .models import Camera, file_kind, norm_path
from .planner import ImportPlan


def _actual_name(parent: Path, name: str) -> str:
    """`name` as spelled on disk. The index stores paths lowercased on Windows."""
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name.lower() == name.lower():
                    return entry.name
    except OSError:
        pass
    return name


@dataclass
class LibraryLayout:
    """Camera and subfolder names seen in `<date folder>/<camera>/<jpg|raw>/<photo>` paths."""

    camera_folders: list[str] = field(default_factory=list)
    _folders_by_model: dict[str, Counter[str]] = field(default_factory=dict)
    _subdirs_by_model_kind: dict[tuple[str, str], Counter[str]] = field(default_factory=dict)

    @classmethod
    def from_db(cls, db: Database, root: Path) -> LibraryLayout:
        prefix = Path(norm_path(root))
        # One example location per name, to look up how it is spelled on disk.
        folder_parent: dict[str, Path] = {}
        subdir_parent: dict[str, Path] = {}
        by_model: dict[str, Counter[str]] = defaultdict(Counter)
        by_kind: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        for path, model in db.conn.execute("SELECT path, model FROM files"):
            try:
                parts = Path(path).relative_to(prefix).parts
            except ValueError:
                continue
            kind = file_kind(Path(path).suffix)
            if len(parts) != 4 or kind is None:
                continue
            camera_folder, subdir = parts[1], parts[2]
            folder_parent.setdefault(camera_folder, root / parts[0])
            if subdir not in subdir_parent:
                date_dir = root / parts[0]
                subdir_parent[subdir] = date_dir / _actual_name(date_dir, camera_folder)
            model = (model or "").strip()
            if model:
                by_model[model][camera_folder] += 1
                by_kind[(model, kind)][subdir] += 1

        def spelled(names: Counter[str], parents: dict[str, Path]) -> Counter[str]:
            result: Counter[str] = Counter()
            for name, count in names.items():
                result[_actual_name(parents[name], name)] += count
            return result

        folders = {name: _actual_name(parent, name) for name, parent in folder_parent.items()}
        return cls(
            sorted(set(folders.values()), key=str.lower),
            {m: spelled(c, folder_parent) for m, c in by_model.items()},
            {k: spelled(c, subdir_parent) for k, c in by_kind.items()},
        )

    def suggest(self, make: str, model: str) -> tuple[Camera, bool]:
        """A camera pre-filled from the library, and whether the library had a match."""
        camera = Camera.default_for(make, model)
        folders = self._folders_by_model.get(model.strip())
        if not folders:
            return camera, False
        camera.folder_name = folders.most_common(1)[0][0]
        for kind, attr in (("jpg", "jpg_dir"), ("raw", "raw_dir")):
            subdirs = self._subdirs_by_model_kind.get((model.strip(), kind))
            if subdirs:
                setattr(camera, attr, subdirs.most_common(1)[0][0])
        return camera, True


def apply_camera_suggestions(plan: ImportPlan, layout: LibraryLayout) -> None:
    """Give unregistered cameras the folder names they already use in the library."""
    for group in plan.groups:
        if not group.registered:
            group.camera, group.library_match = layout.suggest(
                group.camera.make, group.camera.model
            )
