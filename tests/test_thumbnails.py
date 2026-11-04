import base64
import json
import subprocess

from conftest import RICOH, make_file
from test_exiftool import fake_run, needs_exiftool

from photoimporter.core.models import PhotoFile, PhotoMeta
from photoimporter.core.thumbnails import ExifToolThumbnails, Thumbnail, group_shots


def photo(path, time="2026:11:02 10:00:00", subsec=None):
    return PhotoFile(path, 1, 0, PhotoMeta(**RICOH, capture_time=time, subsec=subsec))


def test_raw_and_jpg_of_a_shot_are_paired(tmp_path):
    d = tmp_path / "DCIM"
    shots = group_shots(
        [
            photo(d / "R2.JPG", "2026:11:02 10:05:00"),
            photo(d / "R1.DNG"),
            photo(d / "R1.JPG"),
            photo(d / "R3.DNG", "2026:11:02 10:09:00"),
            photo(d / "R1.JPG", "2026:12:24 09:00:00"),  # counter reset: a different shot
        ]
    )

    assert [(s.name, s.badge, s.primary.filename) for s in shots] == [
        ("R1", "RAW+JPG", "R1.JPG"),
        ("R2", "", "R2.JPG"),
        ("R3", "RAW", "R3.DNG"),
        ("R1", "", "R1.JPG"),
    ]


def test_burst_shots_in_the_same_second_stay_apart(tmp_path):
    shots = group_shots(
        [photo(tmp_path / "A.JPG", subsec="1"), photo(tmp_path / "A.DNG", subsec="2")]
    )
    assert len(shots) == 2


def test_falls_back_to_preview_image_for_raws(tmp_path, monkeypatch):
    jpg, raw = tmp_path / "A.JPG", tmp_path / "A.DNG"
    b64 = "base64:" + base64.b64encode(b"thumb").decode()
    outputs = iter(
        [
            [
                {"SourceFile": jpg.as_posix(), "ThumbnailImage": b64, "Orientation": 6},
                {"SourceFile": raw.as_posix(), "Orientation": 8},
            ],
            [{"SourceFile": raw.as_posix(), "PreviewImage": b64}],
        ]
    )
    monkeypatch.setattr(
        subprocess, "run", lambda args, **kw: fake_run(json.dumps(next(outputs)).encode())(args)
    )

    result = ExifToolThumbnails(exe="exiftool").extract([jpg, raw, tmp_path / "gone.JPG"])

    assert result == {
        jpg: Thumbnail(b"thumb", 6),
        raw: Thumbnail(b"thumb", 8),
        tmp_path / "gone.JPG": Thumbnail(None),
    }


@needs_exiftool
def test_real_exiftool_reads_embedded_thumbnail(tmp_path):
    from PySide6.QtGui import QColor, QImage

    thumb = tmp_path / "t.jpg"
    image = QImage(160, 120, QImage.Format.Format_RGB32)
    image.fill(QColor("orange"))
    image.save(str(thumb))
    photo_path = make_file(tmp_path / "card" / "P1.JPG", b"")
    QImage(320, 240, QImage.Format.Format_RGB32).save(str(photo_path))
    subprocess.run(
        [
            "exiftool",
            "-q",
            "-overwrite_original",
            f"-ThumbnailImage<={thumb}",
            "-Orientation#=6",
            str(photo_path),
        ],
        check=True,
    )

    result = ExifToolThumbnails().extract([photo_path])[photo_path]

    assert result.orientation == 6
    assert QImage.fromData(result.data).size().width() == 160
