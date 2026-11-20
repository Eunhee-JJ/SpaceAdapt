import json
import time
from pathlib import Path

import pytest

from spaceadapt.guide import build_guide
from spaceadapt.planner import plan_all

ROOMS = Path(__file__).resolve().parents[2] / "data" / "rooms"


def load_with_truth(room_id: str) -> dict:
    """Room with preferences as if the user had confirmed every ground-truth cue."""
    space = json.loads((ROOMS / f"{room_id}.json").read_text())
    space["preferences"]["slots"] = {
        c["slot"]: {"value": c["value"], "status": "confirmed"} for c in space["truth"]["lifeCues"]
    }
    return space


@pytest.fixture(scope="module", params=["room-a", "room-b", "room-c"])
def result(request):
    space = load_with_truth(request.param)
    t = time.perf_counter()
    out = plan_all(space)
    out["_elapsed"] = time.perf_counter() - t
    out["_space"] = space
    return out


def test_two_valid_candidates(result):
    """P-2 (part): both candidates exist and have zero hard violations."""
    for k in ("preference", "minimal_move"):
        assert result[k] is not None, k
        assert result[k]["validation"]["hard"] == []


def test_candidates_are_distinct(result):
    a, b = result["preference"]["poses"], result["minimal_move"]["poses"]
    assert a != b


def test_preference_not_worse_than_baseline(result):
    """P-2: preference satisfaction of the preference candidate ≥ baseline."""
    base = result["baseline"]["score"]["breakdown"]["preference"]
    assert result["preference"]["score"]["breakdown"]["preference"] >= base
    assert result["preference"]["score"]["total"] > result["baseline"]["score"]["total"]


def test_minimal_move_moves_no_more_than_preference(result):
    assert result["minimal_move"]["score"]["movedCount"] <= result["preference"]["score"]["movedCount"]


def test_planning_time(result):
    assert result["_elapsed"] < 5


def test_guide_covers_every_moved_item(result):
    best = result["minimal_move"]
    steps = build_guide(result["_space"], best["poses"])
    final_steps = [s for s in steps if not s["temporary"]]
    assert len(final_steps) == best["score"]["movedCount"]
    assert all(s["text"] for s in steps)
