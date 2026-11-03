from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .models import Camera, PhotoFile, PhotoKey, PhotoMeta, norm_path, photo_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    filename TEXT NOT NULL,
    make TEXT,
    model TEXT,
    capture_time TEXT,
    subsec TEXT
);
CREATE INDEX IF NOT EXISTS files_key ON files (filename, capture_time);
CREATE TABLE IF NOT EXISTS cameras (
    make TEXT NOT NULL,
    model TEXT NOT NULL,
    nickname TEXT NOT NULL,
    folder_name TEXT NOT NULL,
    jpg_dir TEXT NOT NULL,
    raw_dir TEXT NOT NULL,
    PRIMARY KEY (make, model)
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    started_at TEXT NOT NULL,
    source TEXT NOT NULL,
    target_dir TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS import_files (
    import_id INTEGER NOT NULL REFERENCES imports (id),
    src TEXT NOT NULL,
    dest TEXT NOT NULL,
    status TEXT NOT NULL
);
"""


def default_db_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / "PhotoImporter" / "library.db"


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)

    def close(self) -> None:
        self.conn.close()

    # Library index

    def file_stats(self) -> dict[str, tuple[int, float]]:
        rows = self.conn.execute("SELECT path, size, mtime FROM files")
        return {path: (size, mtime) for path, size, mtime in rows}

    def upsert_file(
        self, path: Path, size: int, mtime: float, filename: str, meta: PhotoMeta
    ) -> None:
        """Index a file. `filename` is the name it had on the card, which may differ from path."""
        self.conn.execute(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                norm_path(path),
                size,
                mtime,
                filename,
                meta.make,
                meta.model,
                meta.capture_time,
                meta.subsec,
            ),
        )
        self.conn.commit()

    def upsert_files(self, photos: Iterable[PhotoFile]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    norm_path(p.path),
                    p.size,
                    p.mtime,
                    p.filename,
                    p.meta.make,
                    p.meta.model,
                    p.meta.capture_time,
                    p.meta.subsec,
                )
                for p in photos
            ],
        )
        self.conn.commit()

    def delete_files(self, paths: Iterable[str]) -> None:
        self.conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in paths])
        self.conn.commit()

    def existing_keys(self) -> set[PhotoKey]:
        rows = self.conn.execute(
            "SELECT filename, mtime, make, model, capture_time, subsec FROM files"
        )
        return {
            photo_key(filename, mtime, PhotoMeta(make, model, capture_time, subsec))
            for filename, mtime, make, model, capture_time, subsec in rows
        }

    def file_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    # Settings

    def get_setting(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value))
        self.conn.commit()

    # Cameras

    def cameras(self) -> dict[tuple[str, str], Camera]:
        rows = self.conn.execute(
            "SELECT make, model, nickname, folder_name, jpg_dir, raw_dir FROM cameras"
        )
        return {(row[0], row[1]): Camera(*row) for row in rows}

    def save_camera(self, camera: Camera) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO cameras VALUES (?, ?, ?, ?, ?, ?)",
            (
                camera.make,
                camera.model,
                camera.nickname,
                camera.folder_name,
                camera.jpg_dir,
                camera.raw_dir,
            ),
        )
        self.conn.commit()

    # Import log

    def start_import(self, source: Path, target_dir: Path) -> int:
        cur = self.conn.execute(
            "INSERT INTO imports (started_at, source, target_dir) VALUES (?, ?, ?)",
            (datetime.now().isoformat(timespec="seconds"), str(source), str(target_dir)),
        )
        self.conn.commit()
        return cur.lastrowid

    def log_import_file(self, import_id: int, src: Path, dest: Path, status: str) -> None:
        self.conn.execute(
            "INSERT INTO import_files VALUES (?, ?, ?, ?)", (import_id, str(src), str(dest), status)
        )
        self.conn.commit()
