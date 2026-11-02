from datetime import datetime, timedelta, timezone

from main import format_resets_in_label


def test_format_resets_in_label_days_hours() -> None:
    end = datetime.now(timezone.utc) + timedelta(days=6, hours=11, minutes=30)
    label = format_resets_in_label(end.isoformat())
    assert label == "Resets in 6d 11h"
