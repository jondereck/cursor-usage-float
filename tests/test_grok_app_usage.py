from grok_app_usage import parse_grok_billing


def test_format_grok_plan_label() -> None:
    from grok_app_usage import format_grok_plan_label

    assert format_grok_plan_label("SuperGrok", "premium") == "Premium"
    assert format_grok_plan_label("SuperGrok", None) == "Premium"
    assert format_grok_plan_label(None, "plus") == "Plus"

    usage = parse_grok_billing(
        {
            "config": {
                "creditUsagePercent": 38.0,
                "currentPeriod": {"end": "2026-11-08T00:00:00Z"},
            }
        }
    )
    assert usage.usage_percent == 38.0
    assert usage.period_end == "2026-11-08T00:00:00Z"


def test_read_grok_cli_auth_json(tmp_path) -> None:
    from grok_app_usage import read_grok_access_token

    path = tmp_path / "auth.json"
    path.write_text(
        '{"https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828":{"key":"eyJhbG.eyJzdWIiOiIxIn0.sig"}}',
        encoding="utf-8",
    )
    assert read_grok_access_token(path) == "eyJhbG.eyJzdWIiOiIxIn0.sig"


def test_resolve_grok_auth_falls_back_to_default(tmp_path, monkeypatch) -> None:
    from grok_app_usage import resolve_grok_auth_path

    bad = tmp_path / "token.txt"
    bad.write_text('{"broken": true}\n', encoding="utf-8")
    good = tmp_path / "auth.json"
    good.write_text(
        '{"https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828":{"key":"tok"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr("grok_app_usage.default_grok_auth_path", lambda: good)
    resolved = resolve_grok_auth_path(str(bad))
    assert resolved == good
