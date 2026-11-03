from photoimporter.core.models import Camera, PhotoMeta, file_kind, photo_key, safe_folder_name


def test_same_name_and_time_match_regardless_of_case():
    meta = PhotoMeta(model="GR III", capture_time="2026:11:02 10:00:00")
    assert photo_key("R0001.JPG", 0, meta) == photo_key("r0001.jpg", 999, meta)


def test_counter_reset_same_name_different_time_is_new():
    a = PhotoMeta(model="GR III", capture_time="2026:11:02 10:00:00")
    b = PhotoMeta(model="GR III", capture_time="2027:01:05 09:00:00")
    assert photo_key("R0001.JPG", 0, a) != photo_key("R0001.JPG", 0, b)


def test_raw_and_jpg_of_same_shot_are_distinct():
    meta = PhotoMeta(model="GR III", capture_time="2026:11:02 10:00:00")
    assert photo_key("R0001.JPG", 0, meta) != photo_key("R0001.DNG", 0, meta)


def test_subseconds_distinguish_burst_shots():
    a = PhotoMeta(model="X", capture_time="2026:11:02 10:00:00", subsec="10")
    b = PhotoMeta(model="X", capture_time="2026:11:02 10:00:00", subsec="20")
    assert photo_key("A.JPG", 0, a) != photo_key("A.JPG", 0, b)


def test_mtime_fallback_tolerates_two_second_rounding():
    assert photo_key("A.JPG", 1000.0, PhotoMeta()) == photo_key("A.JPG", 1001.9, PhotoMeta())


def test_file_kind():
    assert file_kind(".JPG") == "jpg"
    assert file_kind(".cr3") == "raw"
    assert file_kind(".mov") is None


def test_default_camera_folder_is_safe_lowercase():
    cam = Camera.default_for("SONY", "DSC-RX100M7")
    assert cam.folder_name == "dsc-rx100m7"
    assert safe_folder_name("a/b:c?") == "a_b_c_"
    assert Camera.default_for("", "").folder_name == "unknown camera"
