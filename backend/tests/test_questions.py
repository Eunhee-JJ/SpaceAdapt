import json
from pathlib import Path

from fastapi.testclient import TestClient

from spaceadapt import vlm
from spaceadapt.api import app
from spaceadapt.questions import MAX_QUESTIONS, apply_answers, build_questions

ROOMS = Path(__file__).resolve().parents[2] / "data" / "rooms"


def load(rid):
    return json.loads((ROOMS / f"{rid}.json").read_text())


def test_with_cues_one_confirm_card_then_remaining_slots():
    space = load("room-a")
    cues = vlm.mock_from_truth(space)["lifeCues"]
    qs = build_questions(space, cues)
    assert len(qs) <= MAX_QUESTIONS
    assert qs[0]["type"] == "confirm" and len(qs[0]["items"]) == len(cues)
    asked = {q["slot"] for q in qs[1:]}
    assert not asked & {c["slot"] for c in cues}


def test_cues_cover_more_slots_with_same_question_budget():
    """P-8 (structure): with cues, 3 questions settle more slots than without."""
    space = load("room-a")
    cues = vlm.mock_from_truth(space)["lifeCues"]
    def slots_covered(qs):
        n = 0
        for q in qs:
            n += len(q["items"]) if q["type"] == "confirm" else 1
        return n
    assert slots_covered(build_questions(space, cues)) > slots_covered(build_questions(space, []))


def test_answers_are_deterministic():
    """P-6: same answers → same weights and movable flags."""
    ans = [{"slot": "primaryActivity", "value": "work"}, {"slot": "fixedItems", "value": ["wardrobe"]}]
    a = apply_answers(load("room-c"), [], ans)
    b = apply_answers(load("room-c"), [], ans)
    assert a["preferences"] == b["preferences"]
    assert a["preferences"]["activityWeights"]["work"] == 5
    assert all(not f["movable"] for f in a["furniture"] if f["type"] == "wardrobe")


def test_rejected_cue_is_not_applied():
    space = load("room-a")
    apply_answers(space, [{"slot": "primaryActivity", "value": "work", "accepted": False}], [])
    assert "primaryActivity" not in space["preferences"]["slots"]


def test_api_mock_flow_reaches_layouts():
    """P-5: whole flow with the VLM replaced by mock data."""
    c = TestClient(app)
    sid = c.post("/sessions", json={"roomId": "room-b"}).json()["id"]
    draft = c.post(f"/sessions/{sid}/draft/photo?mode=mock").json()
    assert draft["source"] == "mock" and draft["lifeCues"]
    qs = c.get(f"/sessions/{sid}/questions").json()["questions"]
    cue_ans = [{"slot": i["slot"], "value": i["value"], "accepted": True} for i in qs[0]["items"]]
    other = [{"slot": q["slot"], "value": q["options"][0]["value"]} for q in qs[1:] if not q["multi"]]
    c.post(f"/sessions/{sid}/answers", json={"cues": cue_ans, "answers": other})
    layouts = c.post(f"/sessions/{sid}/layouts").json()
    pref = layouts["preference"]
    assert pref and pref["validation"]["hard"] == [] and pref["score"]["goals"]
