from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .core.cards import detect_cards, scan_source
from .core.config import new_import_folder, photos_root
from .core.copier import execute_plan
from .core.db import Database, default_db_path
from .core.exif import ExifToolError, ExifToolReader, MetadataReader
from .core.indexer import scan_library
from .core.models import Camera
from .core.planner import ImportPlan, build_plan


def _progress(label: str):
    def report(done: int, total: int) -> None:
        print(f"\r{label}: {done}/{total}", end="" if done < total else "\n", file=sys.stderr)

    return report


def _resolve_source(arg: Path | None) -> Path:
    if arg is not None:
        if not arg.is_dir():
            raise SystemExit(f"Source folder not found: {arg}")
        return arg
    cards = detect_cards()
    if len(cards) == 1:
        return cards[0]
    if not cards:
        raise SystemExit("No card with a DCIM folder detected. Pass the source folder explicitly.")
    raise SystemExit(f"Several cards detected ({', '.join(map(str, cards))}). Pass one explicitly.")


def _resolve_target(args: argparse.Namespace, root: Path) -> Path:
    if args.target is not None:
        return args.target
    return new_import_folder(root, args.new, date.today())


def _print_plan(plan: ImportPlan) -> None:
    print(f"Source: {plan.source}")
    print(f"Target: {plan.target_dir}")
    for group in plan.groups:
        cam = group.camera
        kinds = ", ".join(f"{n} {kind}" for kind, n in sorted(group.new_by_kind().items()))
        label = f"{cam.nickname} ({' '.join(filter(None, (cam.make, cam.model))) or 'no EXIF'})"
        flag = "" if group.registered else " [new camera]"
        print(
            f"  {label}{flag}: {len(group.new)} new"
            + (f" ({kinds})" if kinds else "")
            + f", {len(group.already)} already imported"
        )
        if group.new:
            subdirs = sorted({cam.subdir_for(p.kind) for p in group.new})
            print("    -> " + ", ".join(str(Path(cam.folder_name) / d) for d in subdirs))
    print(f"Total: {plan.new_count} new, {plan.already_count} already imported")


def _make_plan(args: argparse.Namespace, db: Database, reader: MetadataReader) -> ImportPlan:
    root = photos_root(db)
    if not args.no_scan:
        if not root.is_dir():
            raise SystemExit(
                f"Photos folder not found: {root}. Set it with: photoimporter config --root PATH"
            )
        result = scan_library(db, root, reader, _progress("Indexing library"))
        print(
            f"Library index: {result.added} added, {result.updated} updated, "
            f"{result.removed} removed, {result.unchanged} unchanged"
        )
    source = _resolve_source(args.source)
    photos = scan_source(source, reader, _progress("Reading card"))
    return build_plan(source, _resolve_target(args, root), photos, db.existing_keys(), db.cameras())


def cmd_config(args, db, reader_factory) -> int:
    if args.root is not None:
        db.set_setting("photos_root", str(args.root.resolve()))
    print(f"Photos folder: {photos_root(db)}")
    return 0


def cmd_scan(args, db, reader_factory) -> int:
    root = photos_root(db)
    result = scan_library(db, root, reader_factory(), _progress("Indexing library"))
    print(
        f"{root}: {result.added} added, {result.updated} updated, {result.removed} removed, "
        f"{result.unchanged} unchanged ({db.file_count()} files indexed)"
    )
    return 0


def cmd_cards(args, db, reader_factory) -> int:
    cards = detect_cards()
    for card in cards:
        print(card)
    if not cards:
        print("No cards detected.")
    return 0


def cmd_cameras(args, db, reader_factory) -> int:
    cameras = db.cameras()
    if not cameras:
        print("No cameras registered yet.")
    for cam in cameras.values():
        jpg, raw = (Path(cam.folder_name, d) for d in (cam.jpg_dir, cam.raw_dir))
        print(f"{cam.make} | {cam.model} -> {cam.nickname}: {jpg}, {raw}")
    return 0


def cmd_camera_set(args, db, reader_factory) -> int:
    existing = db.cameras().get((args.make, args.model)) or Camera.default_for(
        args.make, args.model
    )
    for field in ("nickname", "folder_name", "jpg_dir", "raw_dir"):
        value = getattr(args, field)
        if value is not None:
            setattr(existing, field, value)
    db.save_camera(existing)
    print(f"Saved {existing.make} {existing.model} -> {existing.folder_name}")
    return 0


def cmd_plan(args, db, reader_factory) -> int:
    _print_plan(_make_plan(args, db, reader_factory()))
    return 0


def cmd_import(args, db, reader_factory) -> int:
    plan = _make_plan(args, db, reader_factory())
    _print_plan(plan)
    if plan.new_count == 0:
        print("Nothing new to import.")
        return 0
    if not args.yes and input("Copy these files? [y/N] ").strip().lower() != "y":
        print("Cancelled.")
        return 1
    for camera in plan.unregistered:
        db.save_camera(camera)
        print(
            f"Registered {camera.make} {camera.model} as '{camera.folder_name}' "
            "(change with: photoimporter camera-set)"
        )
    result = execute_plan(plan, db, _progress("Copying"))
    print(
        f"Copied {result.copied}, skipped {result.skipped} already present, "
        f"failed {len(result.failed)}"
    )
    for path in result.renamed:
        print(f"  Name clash, saved as {path}")
    for path, error in result.failed:
        print(f"  FAILED {path}: {error}")
    return 1 if result.failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photoimporter", description=__doc__)
    parser.add_argument(
        "--db", type=Path, default=None, help="index database (default: %%APPDATA%%)"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("config", help="show or set the photos folder")
    p.add_argument("--root", type=Path, help="folder that holds your dated import folders")
    p.set_defaults(func=cmd_config)

    sub.add_parser("scan", help="update the index of your photos folder").set_defaults(
        func=cmd_scan
    )
    sub.add_parser("cards", help="list detected SD cards").set_defaults(func=cmd_cards)
    sub.add_parser("cameras", help="list registered cameras").set_defaults(func=cmd_cameras)

    p = sub.add_parser("camera-set", help="register or edit a camera")
    p.add_argument("--make", required=True, help="EXIF Make, exactly as shown by 'cameras'")
    p.add_argument("--model", required=True, help="EXIF Model, exactly as shown by 'cameras'")
    p.add_argument("--nickname")
    p.add_argument("--folder", dest="folder_name")
    p.add_argument("--jpg-dir")
    p.add_argument("--raw-dir")
    p.set_defaults(func=cmd_camera_set)

    for name, func, help_text in (
        ("plan", cmd_plan, "dry run: show what would be imported"),
        ("import", cmd_import, "copy new photos from a card"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "source", type=Path, nargs="?", help="card or folder (default: detected card)"
        )
        target = p.add_mutually_exclusive_group(required=True)
        target.add_argument("--target", type=Path, help="existing import folder")
        target.add_argument(
            "--new", metavar="DESCRIPTION", help="new folder named 'YYYY.MM.DD DESCRIPTION'"
        )
        p.add_argument("--no-scan", action="store_true", help="skip re-indexing the photos folder")
        if name == "import":
            p.add_argument("-y", "--yes", action="store_true", help="don't ask for confirmation")
        p.set_defaults(func=func)
    return parser


def main(argv: list[str] | None = None, reader_factory=ExifToolReader) -> int:
    args = build_parser().parse_args(argv)
    db = Database(args.db or default_db_path())
    try:
        return args.func(args, db, reader_factory)
    except ExifToolError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
