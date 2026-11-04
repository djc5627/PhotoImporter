from __future__ import annotations

import os
import re
from datetime import date
from pathlib import Path

from .db import Database
from .models import safe_folder_name

# Date patterns for new import folder names. Tokens: YYYY, YY, MM, M, DD, D.
DEFAULT_DATE_FORMAT = "YYYY.MM.DD"
DATE_FORMAT_PRESETS = ["YYYY.MM.DD", "YYYY-MM-DD", "M.D.YYYY", "MM.DD.YYYY"]
_DATE_TOKENS = re.compile(r"YYYY|YY|MM|M|DD|D")


def format_date(day: date, pattern: str) -> str:
    values = {
        "YYYY": f"{day.year:04d}",
        "YY": f"{day.year % 100:02d}",
        "MM": f"{day.month:02d}",
        "M": str(day.month),
        "DD": f"{day.day:02d}",
        "D": str(day.day),
    }
    return _DATE_TOKENS.sub(lambda m: values[m.group()], pattern)


def is_valid_date_format(pattern: str) -> bool:
    """A pattern must contain a year, a month and a day."""
    tokens = set(_DATE_TOKENS.findall(pattern))
    return bool(tokens & {"YYYY", "YY"} and tokens & {"MM", "M"} and tokens & {"DD", "D"}) and bool(
        safe_folder_name(pattern) == pattern.strip(" .")
    )


def photos_root(db: Database) -> Path:
    stored = db.get_setting("photos_root")
    return Path(stored) if stored else Path.home() / "Pictures"


def date_format(db: Database) -> str:
    stored = db.get_setting("date_format")
    return stored if stored and is_valid_date_format(stored) else DEFAULT_DATE_FORMAT


def find_on_insert(db: Database) -> bool:
    """Whether inserting a card starts "Find new photos" by itself."""
    return db.get_setting("find_on_insert") != "0"


APPEARANCES = ("system", "light", "dark")


def appearance(db: Database) -> str:
    """The colour theme: "system" (follow Windows), "light" or "dark"."""
    value = db.get_setting("appearance")
    return value if value in APPEARANCES else "system"


ACCENTS = {  # name: colour; "system" is Windows' own accent colour
    "blue": "#1e88e5",
    "teal": "#00897b",
    "green": "#388e3c",
    "orange": "#ef6c00",
    "red": "#e53935",
    "pink": "#d81b60",
    "purple": "#8e24aa",
    "graphite": "#607d8b",
}
DEFAULT_ACCENT = "blue"


def accent_choice(db: Database) -> str:
    """The accent colour: a name from ACCENTS, or "system" for Windows' accent colour."""
    value = db.get_setting("accent")
    return value if value in ACCENTS or value == "system" else DEFAULT_ACCENT


def check_for_updates(db: Database) -> bool:
    """Whether the app looks for a newer release when it starts."""
    return db.get_setting("check_updates") != "0"


def exiftool_setting(db: Database) -> str | None:
    return db.get_setting("exiftool_path") or None


_ENV_EXIFTOOL = os.environ.get("PHOTOIMPORTER_EXIFTOOL")


def apply_exiftool_setting(db: Database) -> None:
    """Make the ExifTool chosen in Settings the one `find_exiftool` returns."""
    chosen = exiftool_setting(db) or _ENV_EXIFTOOL
    if chosen:
        os.environ["PHOTOIMPORTER_EXIFTOOL"] = chosen
    else:
        os.environ.pop("PHOTOIMPORTER_EXIFTOOL", None)


def new_import_folder(
    root: Path, description: str, day: date, pattern: str = DEFAULT_DATE_FORMAT
) -> Path:
    return root / safe_folder_name(f"{format_date(day, pattern)} {description.strip()}")
