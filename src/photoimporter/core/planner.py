from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .models import Camera, PhotoFile, PhotoKey


@dataclass
class PlanItem:
    photo: PhotoFile
    dest: Path


@dataclass
class CameraGroup:
    camera: Camera
    registered: bool
    new: list[PhotoFile] = field(default_factory=list)
    already: list[PhotoFile] = field(default_factory=list)

    def new_by_kind(self) -> Counter[str]:
        return Counter(p.kind or "other" for p in self.new)


@dataclass
class ImportPlan:
    source: Path
    target_dir: Path
    groups: list[CameraGroup]

    @property
    def items(self) -> list[PlanItem]:
        return [
            PlanItem(
                p, self.target_dir / g.camera.folder_name / g.camera.subdir_for(p.kind) / p.filename
            )
            for g in self.groups
            for p in g.new
        ]

    @property
    def new_count(self) -> int:
        return sum(len(g.new) for g in self.groups)

    @property
    def already_count(self) -> int:
        return sum(len(g.already) for g in self.groups)

    @property
    def unregistered(self) -> list[Camera]:
        return [g.camera for g in self.groups if not g.registered]


def build_plan(
    source: Path,
    target_dir: Path,
    photos: Iterable[PhotoFile],
    existing_keys: set[PhotoKey],
    cameras: dict[tuple[str, str], Camera],
) -> ImportPlan:
    groups: dict[tuple[str, str], CameraGroup] = {}
    for photo in photos:
        camera_key = (photo.meta.make or "", photo.meta.model or "")
        group = groups.get(camera_key)
        if group is None:
            camera = cameras.get(camera_key)
            group = CameraGroup(
                camera=camera or Camera.default_for(*camera_key), registered=camera is not None
            )
            groups[camera_key] = group
        (group.already if photo.key in existing_keys else group.new).append(photo)
    return ImportPlan(source, target_dir, list(groups.values()))
