import os
from datetime import date
from pathlib import Path

import pytest

from photoimporter.core import config
from photoimporter.core.config import (
    apply_exiftool_setting,
    date_format,
    format_date,
    is_valid_date_format,
    new_import_folder,
)


@pytest.mark.parametrize(
    "pattern, expected",
    [
        ("YYYY.MM.DD", "2026.03.07"),
        ("M.D.YYYY", "3.7.2026"),
        ("YYYY-MM-DD", "2026-03-07"),
        ("YY_MM_DD", "26_03_07"),
    ],
)
def test_format_date(pattern, expected):
    assert format_date(date(2026, 3, 7), pattern) == expected


def test_date_format_needs_year_month_and_day():
    assert is_valid_date_format("YYYY.MM.DD")
    assert not is_valid_date_format("YYYY.MM")
    assert not is_valid_date_format("YYYY/MM/DD")  # not allowed in a folder name
    assert not is_valid_date_format("")


def test_new_folder_uses_the_chosen_format(tmp_path):
    folder = new_import_folder(tmp_path, " Hike ", date(2026, 3, 7), "M.D.YYYY")
    assert folder == tmp_path / "3.7.2026 Hike"


def test_stored_date_format_falls_back_when_invalid(db):
    assert date_format(db) == "YYYY.MM.DD"
    db.set_setting("date_format", "M.D.YYYY")
    assert date_format(db) == "M.D.YYYY"
    db.set_setting("date_format", "nonsense")
    assert date_format(db) == "YYYY.MM.DD"


def test_exiftool_setting_overrides_environment(db, monkeypatch):
    monkeypatch.setattr(config, "_ENV_EXIFTOOL", r"C:\from\env\exiftool.exe")
    monkeypatch.delenv("PHOTOIMPORTER_EXIFTOOL", raising=False)

    apply_exiftool_setting(db)
    assert os.environ["PHOTOIMPORTER_EXIFTOOL"] == r"C:\from\env\exiftool.exe"

    db.set_setting("exiftool_path", str(Path("D:/tools/exiftool.exe")))
    apply_exiftool_setting(db)
    assert os.environ["PHOTOIMPORTER_EXIFTOOL"] == str(Path("D:/tools/exiftool.exe"))

    monkeypatch.setattr(config, "_ENV_EXIFTOOL", None)
    db.set_setting("exiftool_path", "")
    apply_exiftool_setting(db)
    assert "PHOTOIMPORTER_EXIFTOOL" not in os.environ
