from unittest.mock import MagicMock, patch

from pill_icons import load_pill_icons


def test_load_pill_icons_from_assets() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        icons, refs = load_pill_icons(root)
        assert icons["cursor"] is not None
        assert icons["xai"] is not None
        assert len(refs) >= 2
    finally:
        root.destroy()


def test_load_pill_icons_missing_file() -> None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    try:
        with patch("pill_icons.resource_path", return_value=MagicMock(is_file=lambda: False)):
            icons, refs = load_pill_icons(root)
        assert icons["cursor"] is None
        assert refs == []
    finally:
        root.destroy()
