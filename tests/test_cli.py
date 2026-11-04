from datetime import date

from photoimporter.cli import main


def test_plan_then_import_with_new_folder(tmp_path, card, library, reader, capsys):
    db = ["--db", str(tmp_path / "cli.db")]
    run = lambda *args: main([*db, *args], reader_factory=lambda: reader)  # noqa: E731

    assert run("config", "--root", str(library)) == 0
    assert run("plan", str(card), "--new", "Halloween Hike") == 0
    out = capsys.readouterr().out
    assert "3 new (2 jpg, 1 raw)" in out
    assert "[new camera]" in out

    assert run("import", str(card), "--new", "Halloween Hike", "--yes") == 0
    folder = library / f"{date.today():%Y.%m.%d} Halloween Hike"
    assert (folder / "ricoh gr iii" / "jpg" / "R0000002.JPG").is_file()

    assert run("import", str(card), "--new", "Halloween Hike", "--yes") == 0
    assert "Nothing new to import." in capsys.readouterr().out


def test_deleted_photos_need_include_flag(tmp_path, card, library, reader, capsys):
    db = ["--db", str(tmp_path / "cli.db")]
    run = lambda *args: main([*db, *args], reader_factory=lambda: reader)  # noqa: E731
    run("config", "--root", str(library))
    run("import", str(card), "--target", str(library / "t"), "--yes")
    jpgs = library / "t" / "ricoh gr iii" / "jpg"
    (jpgs / "R0000001.JPG").unlink()
    (jpgs / "R0000002.JPG").unlink()
    capsys.readouterr()

    assert run("import", str(card), "--target", str(library / "t"), "--yes") == 0
    out = capsys.readouterr().out
    assert "1 recently deleted (skipped), 1 deleted since import (skipped)" in out
    assert "--include-recent-deleted" in out and "--include-deleted" in out
    assert "Nothing new to import." in out

    args = ("import", str(card), "--target", str(library / "t"), "--yes")
    run(*args, "--include-recent-deleted")
    assert (jpgs / "R0000002.JPG").is_file()
    assert not (jpgs / "R0000001.JPG").exists()
    run(*args, "--include-deleted")
    assert (jpgs / "R0000001.JPG").is_file()


def test_camera_set_changes_folder_name(tmp_path, card, library, reader, capsys):
    db = ["--db", str(tmp_path / "cli.db")]
    run = lambda *args: main([*db, *args], reader_factory=lambda: reader)  # noqa: E731
    run("config", "--root", str(library))
    run(
        "camera-set",
        "--make",
        "RICOH IMAGING COMPANY, LTD.",
        "--model",
        "RICOH GR III",
        "--nickname",
        "Ricoh",
        "--folder",
        "ricoh",
    )

    run("import", str(card), "--target", str(library / "t"), "--yes")

    assert (library / "t" / "ricoh" / "raw" / "R0000001.DNG").is_file()


def test_missing_exiftool_reports_cleanly(tmp_path, library, monkeypatch, capsys):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("PHOTOIMPORTER_EXIFTOOL", raising=False)
    db = ["--db", str(tmp_path / "cli.db")]
    main([*db, "config", "--root", str(library)])

    assert main([*db, "scan"]) == 2
    assert "ExifTool was not found" in capsys.readouterr().err


def test_include_imported_copies_again(tmp_path, card, library, reader, capsys):
    db = ["--db", str(tmp_path / "cli.db")]
    run = lambda *args: main([*db, *args], reader_factory=lambda: reader)  # noqa: E731
    run("config", "--root", str(library))
    run("import", str(card), "--target", str(library / "a"), "--yes")

    run("import", str(card), "--target", str(library / "b"), "--yes", "--include-imported")

    assert (library / "b" / "ricoh gr iii" / "raw" / "R0000001.DNG").is_file()
