"""Question selection and answer → preference mapping (요구사항정의서 FR-06, §10.5).

Max 3 questions:
  1) if the photo produced life cues: ONE confirmation card listing every cue
     (each cue is accepted/rejected by the user — AI never decides alone)
  2) the remaining budget goes to unfilled slots, highest layout impact first.
The mapping from slot values to weights is deterministic (P-6).
"""

from __future__ import annotations

LABEL = {"bed": "침대", "desk": "책상", "chair": "의자", "storage": "수납장",
         "table": "테이블", "sofa": "소파", "wardrobe": "옷장", "fridge": "냉장고"}

MAX_QUESTIONS = 3

# impact = how much the slot changes the planner's output (higher first)
QUESTION_BANK = {
    "primaryActivity": {"impact": 3, "text": "방에서 가장 오래 하는 활동은 무엇인가요?",
                        "options": [("업무·공부", "work"), ("잠·휴식", "sleep"), ("취미·운동", "hobby")]},
    "mainPain": {"impact": 3, "text": "지금 방에서 가장 불편한 점은 무엇인가요?",
                 "options": [("수납이 부족해요", "storage"), ("책상 공간이 좁아요", "workspace"),
                             ("지나다니기 불편해요", "aisle"), ("잠자리가 불편해요", "sleep")]},
    "fixedItems": {"impact": 2, "text": "옮길 수 없는 가구가 있나요?", "multi": True, "options": []},
    "sleepWorkSeparation": {"impact": 2, "text": "일할 때 침대가 눈에 들어오거나 화상회의 화면에 잡히면 불편한가요?",
                            "options": [("네, 분리하고 싶어요", True), ("괜찮아요", False)]},
    "moveTolerance": {"impact": 1, "text": "무거운 가구도 옮길 수 있나요?",
                      "options": [("네, 괜찮아요", "high"), ("가벼운 것만요", "low")]},
    "hobbySpace": {"impact": 1, "text": "요가·스트레칭처럼 바닥을 펴서 쓰는 활동을 하나요?",
                   "options": [("네", True), ("아니요", False)]},
}

CUE_MEANING = {
    ("primaryActivity", "work"): "방에서 일·공부를 많이 하시는 것 같아요",
    ("primaryActivity", "sleep"): "숙면이 가장 중요해 보여요",
    ("primaryActivity", "hobby"): "취미 활동 공간이 중요해 보여요",
    ("sleepWorkSeparation", True): "업무 공간과 잠자리를 나누고 싶으실 것 같아요",
    ("mainPain", "storage"): "수납이 부족해 보여요",
    ("mainPain", "workspace"): "작업 공간이 비좁아 보여요",
    ("mainPain", "aisle"): "지나다니는 길이 막혀 보여요",
    ("mainPain", "sleep"): "잠자리 위치가 불편해 보여요",
    ("hobbySpace", True): "바닥을 펴서 쓰는 취미 공간이 필요해 보여요",
}


def _meaning(c: dict) -> str:
    if c["slot"] == "fixedItems":
        return f"{LABEL.get(c['value'], c['value'])}은(는) 옮기기 어려워 보여요"
    return CUE_MEANING.get((c["slot"], c["value"]), f"{c['slot']} = {c['value']}")


def build_questions(space: dict, cues: list[dict] | None) -> list[dict]:
    cues = cues or []
    confirmed = {k for k, v in space.get("preferences", {}).get("slots", {}).items()
                 if isinstance(v, dict) and v.get("status") == "confirmed"}
    out: list[dict] = []
    covered = set(confirmed)
    pending = [c for c in cues if c["slot"] not in confirmed]
    if pending:
        out.append({
            "id": "cues", "type": "confirm",
            "text": "사진에서 이런 점이 보였어요. 맞는 것만 남겨 주세요.",
            "items": [{"index": i, "slot": c["slot"], "value": c["value"],
                       "evidence": c["evidence"], "meaning": _meaning(c)} for i, c in enumerate(pending)],
        })
        covered |= {c["slot"] for c in pending}

    furniture_types = sorted({f["type"] for f in space["furniture"]})
    for slot, q in sorted(QUESTION_BANK.items(), key=lambda kv: -kv[1]["impact"]):
        if len(out) >= MAX_QUESTIONS:
            break
        if slot in covered:
            continue
        options = q["options"]
        if slot == "fixedItems":
            options = [(LABEL.get(t, t), t) for t in furniture_types] + [("없어요", None)]
        out.append({"id": slot, "type": "choice", "slot": slot, "text": q["text"], "multi": q.get("multi", False),
                    "options": [{"label": l, "value": v} for l, v in options]})
    return out


def apply_answers(space: dict, cue_answers: list[dict], answers: list[dict]) -> dict:
    """Write confirmed slots, activity weights, and movable flags into the space (mutates & returns)."""
    prefs = space.setdefault("preferences", {})
    slots = prefs.setdefault("slots", {})
    for c in cue_answers:
        if c.get("accepted"):
            slots[c["slot"]] = {"value": c["value"], "status": "confirmed", "fromCue": True}
    for a in answers:
        if a.get("value") is None and a["slot"] != "fixedItems":
            continue
        slots[a["slot"]] = {"value": a["value"], "status": "confirmed", "fromCue": False}

    weights = {"sleep": 3, "work": 3, "hobby": 1}
    primary = (slots.get("primaryActivity") or {}).get("value")
    if primary in weights:
        weights[primary] = 5
    if (slots.get("hobbySpace") or {}).get("value") is True:
        weights["hobby"] = max(weights["hobby"], 3)
    prefs["activityWeights"] = weights

    fixed = (slots.get("fixedItems") or {}).get("value")
    fixed_types = set(fixed if isinstance(fixed, list) else [fixed] if fixed else [])
    for f in space["furniture"]:
        if f["type"] in fixed_types or f["id"] in fixed_types:
            f["movable"] = False
    return space
