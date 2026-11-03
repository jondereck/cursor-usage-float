from __future__ import annotations

from pathlib import Path

import grok_cli_setup as setup


def test_grok_auth_ready_with_token_file(tmp_path: Path) -> None:
    auth = tmp_path / "auth.json"
    auth.write_text('{"access_token": "abc123token"}', encoding="utf-8")
    assert setup.grok_auth_ready(auth) is True


def test_ensure_skips_install_when_custom_path_invalid(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(setup, "install_grok_cli_via_npm", lambda: (_ for _ in ()).throw(AssertionError()))
    assert setup.ensure_grok_auth_for_usage(str(tmp_path / "missing.txt")) is None


def test_install_grok_cli_calls_npm(monkeypatch, tmp_path: Path) -> None:
    npm = tmp_path / "npm.cmd"
    npm.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(setup, "_npm_on_path", lambda: npm)
    monkeypatch.setattr(setup, "find_grok_executable", lambda: Path("C:/fake/grok.exe"))

    calls: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        calls.append(list(argv))

        class R:
            returncode = 0
            stdout = ""
            stderr = ""

        return R()

    monkeypatch.setattr(setup.subprocess, "run", fake_run)
    ok, msg = setup.install_grok_cli_via_npm()
    assert ok is True
    assert setup.GROK_NPM_PACKAGE in " ".join(calls[0])
    assert "Installed" in msg
