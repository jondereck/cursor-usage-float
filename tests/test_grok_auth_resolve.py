def test_resolve_prefers_grok_auth_over_cursor_token_txt(tmp_path, monkeypatch) -> None:
    from grok_app_usage import resolve_grok_auth_path

    cursor_export = tmp_path / "token.txt"
    cursor_export.write_text("eyJhbG.cursor-token.sig\n", encoding="utf-8")
    good = tmp_path / "auth.json"
    good.write_text(
        '{"https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828":{"key":"tok"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("grok_app_usage.default_grok_auth_path", lambda: good)
    assert resolve_grok_auth_path(str(cursor_export)) == good
