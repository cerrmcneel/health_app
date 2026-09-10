"""Weight trends must be correct for people who weigh in irregularly.

Daily weigh-ins are not required and never should be. The trend maths therefore
has to key off calendar dates, never off list position: `entries[6]` means "seven
weigh-ins ago", which for a twice-weekly logger is three and a half weeks.
"""
from datetime import timedelta

import pytest

from app import config


def _day(offset_days: int) -> str:
    return (config.now().date() - timedelta(days=offset_days)).isoformat()


def _log(client, profile_id, offset_days, kg):
    res = client.post(
        "/api/weights",
        json={"weight_kg": kg, "day": _day(offset_days)},
        headers={"X-Profile-ID": str(profile_id)},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _fetch(client, profile_id):
    res = client.get("/api/weights", headers={"X-Profile-ID": str(profile_id)})
    assert res.status_code == 200
    return res.json()


def test_seven_day_change_spans_seven_days_not_seven_entries(client, second_profile):
    """The headline regression: sporadic logging must not stretch the window.

    Seven weigh-ins spread over 40 days would make `entries[6]` a 40-day delta
    displayed to the user as '7d change'.
    """
    pid = second_profile["id"]
    for offset, kg in [(40, 90.0), (33, 89.0), (26, 88.0), (19, 87.0),
                       (12, 86.0), (7, 85.0), (0, 84.0)]:
        _log(client, pid, offset, kg)

    data = _fetch(client, pid)
    assert data["latest_weight"] == 84.0
    # Today is 84.0, the weigh-in 7 days ago is 85.0 -> a 1.0 kg drop.
    # Reading entries[6] would compare against the 40-day-old 90.0 and report -6.0.
    assert data["change_7d"] == pytest.approx(-1.0), (
        f"change_7d={data['change_7d']}; expected -1.0 over 7 calendar days"
    )


def test_seven_day_change_works_with_only_two_weigh_ins(client, second_profile):
    """Twice a month is a perfectly reasonable cadence."""
    pid = second_profile["id"]
    _log(client, pid, 9, 80.0)
    _log(client, pid, 0, 79.0)

    data = _fetch(client, pid)
    assert data["change_7d"] is not None, (
        "a user with two weigh-ins nine days apart still deserves a trend"
    )
    assert data["change_7d"] == pytest.approx(-1.0)


def test_change_is_none_when_there_is_no_earlier_weigh_in(client, second_profile):
    """One data point is not a trend; report nothing rather than zero."""
    pid = second_profile["id"]
    _log(client, pid, 0, 77.0)
    data = _fetch(client, pid)
    assert data["change_7d"] is None


def test_comparison_span_is_reported_so_the_label_can_be_honest(client, second_profile):
    """When the nearest weigh-in is not exactly 7 days old, say so.

    The UI should be able to render 'vs 9 days ago' instead of mislabelling the
    number as a 7-day change.
    """
    pid = second_profile["id"]
    _log(client, pid, 11, 82.0)
    _log(client, pid, 0, 81.0)

    data = _fetch(client, pid)
    assert "change_span_days" in data, (
        "the API must report how many days the comparison actually covers"
    )
    assert data["change_span_days"] == 11


def test_moving_average_smooths_without_requiring_daily_entries(client, second_profile):
    pid = second_profile["id"]
    _log(client, pid, 6, 100.0)
    _log(client, pid, 3, 102.0)
    _log(client, pid, 0, 101.0)

    data = _fetch(client, pid)
    latest = data["weights"][0]
    assert latest["moving_avg_7d"] == pytest.approx(101.0, abs=0.01)


def test_logging_the_same_day_twice_updates_rather_than_duplicates(client, second_profile):
    pid = second_profile["id"]
    _log(client, pid, 0, 75.0)
    _log(client, pid, 0, 75.5)

    data = _fetch(client, pid)
    today = _day(0)
    assert sum(1 for w in data["weights"] if w["day"] == today) == 1
    assert data["latest_weight"] == 75.5
