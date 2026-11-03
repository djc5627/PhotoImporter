from __future__ import annotations

from datetime import date
from pathlib import Path

from .db import Database
from .models import safe_folder_name

DATE_FORMAT = "%Y.%m.%d"


def photos_root(db: Database) -> Path:
    stored = db.get_setting("photos_root")
    return Path(stored) if stored else Path.home() / "Pictures"


def new_import_folder(root: Path, description: str, day: date) -> Path:
    return root / safe_folder_name(f"{day.strftime(DATE_FORMAT)} {description.strip()}")
