from __future__ import annotations

import pytest
from antigravity_usage import AntigravityError, parse_antigravity_quota


def test_parse_antigravity_quota_success():
    payload = {
        "response": {
            "groups": [
                {
                    "displayName": "Gemini Models",
                    "buckets": [
                        {
                            "bucketId": "gemini-weekly",
                            "displayName": "Weekly Limit Remaining",
                            "remainingFraction": 0.25,
                            "resetTime": "2026-11-02T12:00:00Z",
                        }
                    ],
                },
                {
                    "displayName": "Claude and GPT models",
                    "buckets": [
                        {
                            "bucketId": "3p-weekly",
                            "displayName": "Weekly Limit Remaining",
                            "remainingFraction": 0.0,
                            "resetTime": "2026-11-02T12:00:00Z",
                        }
                    ],
                },
            ]
        }
    }
    usage = parse_antigravity_quota(payload)
    assert usage.is_eligible is True
    assert usage.usage_percent == 75.0
    assert usage.gemini_percent == 75.0
    assert usage.claude_gpt_percent == 100.0
    assert usage.next_reset == "2026-11-02T12:00:00Z"
    assert len(usage.buckets) == 2


def test_parse_antigravity_quota_invalid_shape():
    with pytest.raises(AntigravityError):
        parse_antigravity_quota({"foo": "bar"})


def test_parse_antigravity_quota_empty_groups():
    with pytest.raises(AntigravityError):
        parse_antigravity_quota({"response": {"groups": []}})
