from unittest.mock import patch

from grok_login_launcher import launch_grok_login_terminal


def test_launch_grok_login_missing_cli() -> None:
    with patch("grok_login_launcher.shutil.which", return_value=None):
        ok, msg = launch_grok_login_terminal()
    assert ok is False
    assert "not found" in msg.lower()
