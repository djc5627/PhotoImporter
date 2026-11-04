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
    # Imported before, then deleted from the library (known from the deleted-photos history),
    # and newer than every photo from this camera still in the library: e.g. the latest
    # import folder was deleted. Kept apart so these can be restored without old culls.
    recent_deleted: list[PhotoFile] = field(default_factory=list)
    # Imported before, then deleted from the library: the rest of the deleted-photos history.
    deleted: list[PhotoFile] = field(default_factory=list)
    # Not in the library or its history, but older than the newest library photo from this
    # camera, so most likely imported and deleted before the history existed.
    older: list[PhotoFile] = field(default_factory=list)
    # For an unregistered camera: whether its folder names came from existing library photos.
    library_match: bool = False

    def new_by_kind(self) -> Counter[str]:
        return Counter(p.kind or "other" for p in self.new)

    def photos(self, status: str | None = None) -> list[PhotoFile]:
        """Photos with one status (see STATUSES), or all of them."""
        if status is not None:
            return list(getattr(self, status))
        return [p for s in STATUSES for p in getattr(self, s)]


# Where each card photo stands, in the order they're listed; see CameraGroup.
STATUSES = ("new", "recent_deleted", "deleted", "older", "already")
STATUS_LABELS = {
    "new": "New",
    "recent_deleted": "Recently deleted",
    "deleted": "Deleted",
    "older": "Probably deleted",
    "already": "Already imported",
}


def _include(status: str) -> property:
    """A switch that ticks or unticks every photo with `status`; True when all are ticked."""

    def get(self: ImportPlan) -> bool:
        photos = self.photos(status)
        return bool(photos) and all(p.path in self.selected for p in photos)

    def set_(self: ImportPlan, on: bool) -> None:
        self.select(self.photos(status), on)

    return property(get, set_)


@dataclass
class ImportPlan:
    source: Path
    target_dir: Path
    groups: list[CameraGroup]
    # Card paths of the chosen (highlighted) photos. Starts as the new photos. Import copies
    # these, except photos already in the library unless `allow_reimport` is on.
    selected: set[Path] | None = None
    allow_reimport: bool = False

    def __post_init__(self) -> None:
        if self.selected is None:
            self.selected = {p.path for g in self.groups for p in g.new}

    include_recent_deleted = _include("recent_deleted")
    include_deleted = _include("deleted")
    include_older = _include("older")
    include_already = _include("already")

    def photos(self, status: str | None = None) -> list[PhotoFile]:
        return [p for g in self.groups for p in g.photos(status)]

    def status_of(self, photo: PhotoFile) -> str:
        for status in STATUSES:
            if any(p.path == photo.path for g in self.groups for p in getattr(g, status)):
                return status
        raise KeyError(photo.path)

    def statuses(self) -> dict[Path, str]:
        return {p.path: s for g in self.groups for s in STATUSES for p in getattr(g, s)}

    def select(self, photos: Iterable[PhotoFile], on: bool = True) -> None:
        paths = {p.path for p in photos}
        if on:
            self.selected |= paths
        else:
            self.selected -= paths

    def is_selected(self, photo: PhotoFile) -> bool:
        return photo.path in self.selected

    def selected_count(self, status: str) -> int:
        return sum(p.path in self.selected for p in self.photos(status))

    def to_copy(self, group: CameraGroup) -> list[PhotoFile]:
        already = set() if self.allow_reimport else {p.path for p in group.already}
        return [p for p in group.photos() if p.path in self.selected and p.path not in already]

    def remove(self, paths: set[Path]) -> None:
        """Forget photos that are no longer on the card (e.g. deleted)."""
        for group in self.groups:
            for status in STATUSES:
                setattr(group, status, [p for p in getattr(group, status) if p.path not in paths])
        self.groups = [g for g in self.groups if g.photos()]
        self.selected -= paths

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
    def recent_deleted_count(self) -> int:
        return sum(len(g.recent_deleted) for g in self.groups)

    @property
    def deleted_count(self) -> int:
        return sum(len(g.deleted) for g in self.groups)

    @property
    def older_count(self) -> int:
        return sum(len(g.older) for g in self.groups)

    @property
    def unregistered(self) -> list[Camera]:
        return [g.camera for g in self.groups if not g.registered and self.to_copy(g)]

    def _state(self, status: str, total: int) -> str:
        ticked = self.selected_count(status)
        if ticked == 0:
            return "skipped"
        return "included" if ticked == total else f"{ticked} included"

    def summary(self) -> str:
        if not (
            self.new_count or self.recent_deleted_count or self.deleted_count or self.older_count
        ) and not (self.allow_reimport and self.selected_count("already")):
            return f"Nothing new: all {self.already_count} photos already imported."
        new = "1 new photo" if self.new_count == 1 else f"{self.new_count} new photos"
        ticked_new = self.selected_count("new")
        if ticked_new != self.new_count:
            new += f" ({ticked_new} selected)"
        already = f"{self.already_count} already imported"
        if self.allow_reimport and self.selected_count("already"):
            already += f" ({self.selected_count('already')} to import again)"
        parts = [new, already]
        for count, status, label in (
            (self.recent_deleted_count, "recent_deleted", "recently deleted"),
            (self.deleted_count, "deleted", "deleted since import"),
            (self.older_count, "older", "probably deleted earlier"),
        ):
            if count:
                parts.append(f"{count} {label} ({self._state(status, count)})")
        return ", ".join(parts) + "."


def build_plan(
    source: Path,
    target_dir: Path,
    photos: Iterable[PhotoFile],
    existing_keys: set[PhotoKey],
    cameras: dict[tuple[str, str], Camera],
    deleted_keys: set[PhotoKey] | None = None,
    newest_by_model: Mapping[str, str] | None = None,
    newest_present_by_model: Mapping[str, str] | None = None,
) -> ImportPlan:
    """Sort card photos into new, already imported and the deleted groups.

    `newest_by_model` is the newest capture time per model over current and deleted library
    photos; `newest_present_by_model` over current ones only. Without the latter, deleted
    photos are not split into recent and older.
    """
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
            if newest_present_by_model is not None and photo.meta.capture_time:
                present = newest_present_by_model.get((photo.meta.model or "").strip())
                if present is None or photo.meta.capture_time > present:
                    group.recent_deleted.append(photo)
                    continue
            group.deleted.append(photo)
        elif newest and photo.meta.capture_time and photo.meta.capture_time < newest:
            group.older.append(photo)
        else:
            group.new.append(photo)
    return ImportPlan(source, target_dir, list(groups.values()))


@dataclass
class CameraBreakdown:
    name: str
    saved_to: str
    counts: Counter[str]  # pictures per status

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass
class ImportBreakdown:
    """What an import will copy, per camera and status, for the confirmation window.

    Counts are pictures: a RAW+JPG pair counts once.
    """

    cameras: list[CameraBreakdown]
    files: int
    hidden: int  # pictures being imported that aren't in the current view
    not_importing: Counter[str]  # pictures left out, per status

    @property
    def totals(self) -> Counter[str]:
        result: Counter[str] = Counter()
        for camera in self.cameras:
            result.update(camera.counts)
        return result

    @property
    def pictures(self) -> int:
        return sum(c.total for c in self.cameras)

    @property
    def statuses(self) -> list[str]:
        """The statuses that have something to import, in display order."""
        totals = self.totals
        return [s for s in STATUSES if totals[s]]


def _shot_status(photos: list[PhotoFile], statuses: dict[Path, str]) -> str:
    found = {statuses[p.path] for p in photos}
    return next(s for s in STATUSES if s in found)


def import_breakdown(plan: ImportPlan, shown: set[Path] | None = None) -> ImportBreakdown:
    """Summarise what `plan` will import. `shown`: card paths visible in the grid."""
    from .thumbnails import group_shots  # here to avoid an import cycle

    statuses = plan.statuses()
    cameras, files, hidden = [], 0, 0
    copying: set[Path] = set()
    for group in plan.groups:
        to_copy = plan.to_copy(group)
        if not to_copy:
            continue
        files += len(to_copy)
        copying.update(p.path for p in to_copy)
        counts: Counter[str] = Counter()
        for shot in group_shots(to_copy):
            counts[_shot_status(shot.photos, statuses)] += 1
            if shown is not None and not any(p.path in shown for p in shot.photos):
                hidden += 1
        cam = group.camera
        kinds = sorted({p.kind for p in to_copy})
        saved_to = ", ".join(str(Path(cam.folder_name, cam.subdir_for(k))) for k in kinds)
        cameras.append(CameraBreakdown(cam.nickname, saved_to, counts))

    left_out = [p for p in plan.photos() if p.path not in copying]
    not_importing: Counter[str] = Counter()
    for shot in group_shots(left_out):
        not_importing[_shot_status(shot.photos, statuses)] += 1
    return ImportBreakdown(cameras, files, hidden, not_importing)
