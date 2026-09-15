"""The seed's numbers are thresholds, not decoration.

Each one sits just past a boundary in the API, and the whole value of the
seeded tenant is that it crosses them. If an API limit changes and these do
not, the tenant quietly stops testing the thing it exists to test - the first
page comes back short, the paging loop exits, and nobody notices for months.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from nevo.main import app

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "seed_e2e_tenant.py"


@pytest.fixture(scope="module")
def seed():
    spec = importlib.util.spec_from_file_location("seed_e2e_tenant", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _limit(path: str) -> int:
    operation = app.openapi()["paths"][path]["get"]
    parameter = next(p for p in operation["parameters"] if p["name"] == "limit")
    return parameter["schema"]["maximum"]


def test_the_adaptation_seed_forces_more_than_one_page(seed) -> None:
    # The SENCo screen pages until it sees a short page. One page of events
    # means that loop never runs.
    assert seed.ADAPTATION_EVENTS > _limit("/api/admin/adaptation-log") * 2


def test_more_flags_than_flagged_children(seed) -> None:
    # The Overview counts children, not flags. Equal numbers hide a bug that
    # counts the wrong one.
    assert seed.TOTAL_FLAGS > seed.FLAGGED_STUDENTS


def test_withdrawn_is_not_the_same_number_as_unconfirmed(seed) -> None:
    from nevo.domain.accounts.vocabulary import ConsentStatus

    mix = seed.CONSENT_MIX
    withdrawn = mix[ConsentStatus.WITHDRAWN]
    without_recorded_consent = sum(
        count for status, count in mix.items() if status is not ConsentStatus.CONFIRMED
    )
    assert withdrawn != without_recorded_consent


def test_every_consent_state_is_represented(seed) -> None:
    from nevo.domain.accounts.vocabulary import ConsentStatus

    assert set(seed.CONSENT_MIX) == set(ConsentStatus)


def test_one_learner_has_no_consent_record_at_all(seed) -> None:
    assert seed.STUDENTS_WITH_NO_CONSENT_ROW >= 1


def test_the_adaptation_window_matches_the_screen(seed) -> None:
    # "Adaptations this week" is seven days, so the events have to land inside
    # seven days or the screen shows an empty state on a full tenant.
    assert seed.ADAPTATION_WINDOW_DAYS == 7


def test_the_filterable_kinds_are_all_seeded(seed) -> None:
    from nevo.intelligence.adaptation_log import ADAPTATION_EVENT_TYPES

    # Every value the eventType filter offers should return something, or a
    # filter that silently matches nothing looks like a working empty state.
    assert set(seed.ADAPTATION_TYPES) == set(ADAPTATION_EVENT_TYPES)
