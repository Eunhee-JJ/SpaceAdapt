import json
import time
from pathlib import Path

import pytest

from spaceadapt.validate import validate

ROOMS = Path(__file__).resolve().parents[2] / "data" / "rooms"


def load(room_id: str) -> dict:
    return json.loads((ROOMS / f"{room_id}.json").read_text())


def types(result: dict) -> set[str]:
    return {v["type"] for v in result["hard"]}


def test_room_a_baseline_flags_door_swing_and_blocked_wardrobe():
    space = load("room-a")
    r = validate(space, space["baselineLayout"]["poses"])
    assert "door_swing" in types(r)
    blocked = [v for v in r["hard"] if v["type"] == "clearance_blocked"]
    assert any(v["objects"][0] == "wardrobe-1" and "bed-1" in v["objects"] for v in blocked)
    assert r["metrics"]["bedInWorkView"] is True


def test_room_a_reference_layout_has_no_hard_violation():
    space = load("room-a")
    r = validate(space, space["referenceLayout"]["poses"])
    assert r["hard"] == [], [v["reason"] for v in r["hard"]]


def test_room_b_baseline_bed_blocks_door():
    space = load("room-b")
    r = validate(space, space["baselineLayout"]["poses"])
    swing = [v for v in r["hard"] if v["type"] == "door_swing"]
    assert any("bed-1" in v["objects"] for v in swing)


def test_room_c_baseline_storage_cuts_off_aisle():
    space = load("room-c")
    r = validate(space, space["baselineLayout"]["poses"])
    unreachable = {v["objects"][0] for v in r["hard"] if v["type"] == "aisle_unreachable"}
    assert {"bed-1", "desk-1"} <= unreachable
    assert "collision" not in types(r)


@pytest.mark.parametrize("room_id", ["room-a", "room-b", "room-c"])
def test_every_baseline_has_at_least_one_hard_violation(room_id):
    space = load(room_id)
    assert validate(space, space["baselineLayout"]["poses"])["hard"]


def test_wider_aisle_requirement_is_stricter():
    space = load("room-a")
    poses = space["referenceLayout"]["poses"]
    assert len(validate(space, poses, aisle_width=60)["hard"]) <= len(validate(space, poses, aisle_width=110)["hard"])


def test_revalidation_is_fast():
    """NFR-02 / P-3 smoke: single validation far below the 1s budget."""
    space = load("room-a")
    poses = space["baselineLayout"]["poses"]
    t = time.perf_counter()
    for _ in range(20):
        validate(space, poses)
    assert (time.perf_counter() - t) / 20 < 0.2
