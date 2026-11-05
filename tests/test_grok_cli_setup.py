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


def test_launch_grok_login_force(monkeypatch, tmp_path: Path) -> None:
    fake_grok = tmp_path / "grok.cmd"
    fake_grok.write_text("@echo off\n", encoding="utf-8")
    monkeypatch.setattr(setup, "find_grok_executable", lambda: fake_grok)

    calls: list[list[str]] = []

    def fake_popen(argv, **_kwargs):
        calls.append(list(argv))

    monkeypatch.setattr(setup.subprocess, "Popen", fake_popen)
    setup._state.last_login_launch = setup.time.monotonic()

    # Without force: throttled by cooldown
    ok, msg = setup.launch_grok_login(force=False)
    assert ok is True
    assert len(calls) == 0

    # With force: immediately launches
    ok, msg = setup.launch_grok_login(force=True)
    assert ok is True
    assert len(calls) == 1
    assert "grok" in " ".join(calls[0]).lower()
