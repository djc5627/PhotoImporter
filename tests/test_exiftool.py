import json
import shutil
import subprocess

import pytest

from photoimporter.core.exif import ExifToolError, ExifToolReader
from photoimporter.core.models import PhotoMeta

needs_exiftool = pytest.mark.skipif(
    shutil.which("exiftool") is None, reason="ExifTool not installed"
)


def fake_run(stdout: bytes, returncode: int = 0, stderr: bytes = b""):
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)

    return run


def test_missing_records_raise_instead_of_caching_blank_metadata(tmp_path, monkeypatch):
    path = tmp_path / "A.JPG"
    monkeypatch.setattr(subprocess, "run", fake_run(b"", 1, b"Error: something broke"))

    with pytest.raises(ExifToolError, match="something broke"):
        ExifToolReader(exe="exiftool").read([path])


def test_records_are_matched_back_to_requested_paths(tmp_path, monkeypatch):
    path = tmp_path / "A.JPG"
    record = {
        "SourceFile": path.as_posix(),
        "Make": "SONY",
        "Model": "DSC-RX100M7",
        "DateTimeOriginal": "2026:11:02 10:00:00",
        "SubSecTimeOriginal": 45,
    }
    monkeypatch.setattr(subprocess, "run", fake_run(json.dumps([record]).encode()))

    meta = ExifToolReader(exe="exiftool").read([path])[path]

    assert meta == PhotoMeta("SONY", "DSC-RX100M7", "2026:11:02 10:00:00", "45")


@needs_exiftool
def test_real_exiftool_on_file_without_exif(tmp_path):
    path = tmp_path / "not a photo é.jpg"
    path.write_bytes(b"not really a jpeg")

    assert ExifToolReader().read([path]) == {path: PhotoMeta()}
