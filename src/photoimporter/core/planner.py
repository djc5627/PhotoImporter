from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
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
    # Imported before, then deleted from the library (known from the deleted-photos history).
    deleted: list[PhotoFile] = field(default_factory=list)
    # Not in the library or its history, but older than the newest library photo from this
    # camera, so most likely imported and deleted before the history existed.
    older: list[PhotoFile] = field(default_factory=list)

    def new_by_kind(self) -> Counter[str]:
        return Counter(p.kind or "other" for p in self.new)


@dataclass
class ImportPlan:
    source: Path
    target_dir: Path
    groups: list[CameraGroup]
    include_deleted: bool = False
    include_older: bool = False

    def to_copy(self, group: CameraGroup) -> list[PhotoFile]:
        photos = list(group.new)
        if self.include_deleted:
            photos += group.deleted
        if self.include_older:
            photos += group.older
        return photos

    @property
    def items(self) -> list[PlanItem]:
        return [
            PlanItem(
                p, self.target_dir / g.camera.folder_name / g.camera.subdir_for(p.kind) / p.filename
            )
            for g in self.groups
            for p in self.to_copy(g)
        ]

    @property
    def copy_count(self) -> int:
        return sum(len(self.to_copy(g)) for g in self.groups)

    @property
    def new_count(self) -> int:
        return sum(len(g.new) for g in self.groups)

    @property
    def already_count(self) -> int:
        return sum(len(g.already) for g in self.groups)

    @property
    def deleted_count(self) -> int:
        return sum(len(g.deleted) for g in self.groups)

    @property
    def older_count(self) -> int:
        return sum(len(g.older) for g in self.groups)

    @property
    def unregistered(self) -> list[Camera]:
        return [g.camera for g in self.groups if not g.registered and self.to_copy(g)]

    def summary(self) -> str:
        if not (self.new_count or self.deleted_count or self.older_count):
            return f"Nothing new: all {self.already_count} photos already imported."
        new = "1 new photo" if self.new_count == 1 else f"{self.new_count} new photos"
        parts = [new, f"{self.already_count} already imported"]
        for count, label, included in (
            (self.deleted_count, "deleted since import", self.include_deleted),
            (self.older_count, "probably deleted earlier", self.include_older),
        ):
            if count:
                parts.append(f"{count} {label} ({'included' if included else 'skipped'})")
        return ", ".join(parts) + "."


def build_plan(
    source: Path,
    target_dir: Path,
    photos: Iterable[PhotoFile],
    existing_keys: set[PhotoKey],
    cameras: dict[tuple[str, str], Camera],
    deleted_keys: set[PhotoKey] | None = None,
    newest_by_model: Mapping[str, str] | None = None,
) -> ImportPlan:
    deleted_keys = deleted_keys or set()
    newest_by_model = newest_by_model or {}
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
        newest = newest_by_model.get((photo.meta.model or "").strip())
        if photo.key in existing_keys:
            group.already.append(photo)
        elif photo.key in deleted_keys:
            group.deleted.append(photo)
        elif newest and photo.meta.capture_time and photo.meta.capture_time < newest:
            group.older.append(photo)
        else:
            group.new.append(photo)
    return ImportPlan(source, target_dir, list(groups.values()))
