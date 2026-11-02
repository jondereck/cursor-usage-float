from cursor_identity import CursorAccountInfo


def test_plan_label_plus_active() -> None:
    info = CursorAccountInfo(
        email="a@example.com",
        membership_type="plus",
        subscription_status="active",
    )
    assert info.plan_label == "Plus"


def test_plan_label_free() -> None:
    info = CursorAccountInfo(membership_type="free", subscription_status="active")
    assert info.plan_label == "Free"


def test_plan_label_trialing() -> None:
    info = CursorAccountInfo(membership_type="pro", subscription_status="trialing")
    assert info.plan_label == "Pro · trial"
