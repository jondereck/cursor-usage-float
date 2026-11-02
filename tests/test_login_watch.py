from login_watch import file_stamp


def test_file_stamp_changes_with_content(tmp_path) -> None:
    path = tmp_path / "auth.json"
    path.write_text("a", encoding="utf-8")
    first = file_stamp(path)
    path.write_text("ab", encoding="utf-8")
    second = file_stamp(path)
    assert first != second
