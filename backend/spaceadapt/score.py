"""Layout scoring (요구사항정의서 §10.2–10.3).

All components are normalized to 0..1; total is 0..100.
"""

from __future__ import annotations

import math

from shapely.geometry import box

from . import geometry as g
from .validate import validate

TYPE_WEIGHT = {"bed": 3, "wardrobe": 3, "fridge": 3, "sofa": 2, "storage": 2,
               "desk": 1.5, "table": 1.5, "chair": 0.5}
ATTR_FACTOR = {"wheels": 0.5, "foldable": 0.7}

PROFILES = {
    "preference": {"pref": 0.40, "zone": 0.25, "int": 0.25, "move": 0.10},
    "minimal_move": {"pref": 0.20, "zone": 0.15, "int": 0.15, "move": 0.50},
}


def move_cost(space: dict, baseline: dict, poses: dict) -> tuple[float, int]:
    """Σ(distance m × type weight × attribute factor) + 0.5 × rotated count; also returns moved count."""
    cost, moved = 0.0, 0
    for f in space["furniture"]:
        a, b = baseline.get(f["id"]), poses.get(f["id"])
        if not a or not b:
            continue
        dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) / 100
        rotated = (a.get("rotation", 0) - b.get("rotation", 0)) % 360 != 0
        if dist < 0.05 and not rotated:
            continue
        moved += 1
        factor = 1.0
        for attr in f.get("attributes", []):
            factor *= ATTR_FACTOR.get(attr, 1.0)
        cost += dist * TYPE_WEIGHT.get(f["type"], 1) * factor + (0.5 if rotated else 0)
    return cost, moved


def _first(space: dict, type_: str) -> dict | None:
    return next((f for f in space["furniture"] if f["type"] == type_), None)


def _has_open_floor(free, size=(180, 70), step=20) -> bool:
    minx, miny, maxx, maxy = free.bounds
    for w, h in (size, size[::-1]):
        y = miny
        while y + h <= maxy:
            x = minx
            while x + w <= maxx:
                if free.contains(box(x, y, x + w, y + h)):
                    return True
                x += step
            y += step
    return False


def preference_goals(space: dict, poses: dict, result: dict) -> list[tuple[str, bool]]:
    """Goals derived from slots and activity weights; returns (label, satisfied)."""
    prefs = space.get("preferences", {})
    slots = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in prefs.get("slots", {}).items()}
    weights = prefs.get("activityWeights", {})
    room = space["room"]
    goals: list[tuple[str, bool]] = []

    desk, bed = _first(space, "desk"), _first(space, "bed")
    windows = [g.opening_geom(room, o) for o in room.get("openings", []) if o["type"] == "window"]
    doors = [g.opening_geom(room, o) for o in room.get("openings", []) if o["type"] == "door"]

    separate = slots.get("sleepWorkSeparation", weights.get("work", 0) >= 4)
    if separate:
        goals.append(("업무 중 침대가 화면에 보이지 않음", not result["metrics"]["bedInWorkView"]))

    if desk and windows and (slots.get("primaryActivity") == "work" or weights.get("work", 0) >= 4):
        p = poses[desk["id"]]
        wc = windows[0].entry_point(0)
        goals.append(("책상이 창가에 있음", math.hypot(p["x"] - wc.x, p["y"] - wc.y) <= 130))

    if bed and doors and (slots.get("primaryActivity") == "sleep" or weights.get("sleep", 0) >= 4):
        p = poses[bed["id"]]
        dc = doors[0].entry_point(0)
        fp = g.footprint(bed, p)
        goals.append(("침대가 출입문에서 떨어져 있음", fp.distance(dc) >= 80))

    if slots.get("hobbySpace"):
        free = g.room_polygon(room).difference(
            g.unary_union([g.footprint(f, poses[f["id"]]) for f in space["furniture"] if f["id"] in poses]
                          + [p for _, p in g.fixture_polygons(room)]))
        goals.append(("요가매트를 펼 바닥(180×70) 확보", _has_open_floor(free)))

    if slots.get("mainPain") == "storage":
        blocked = {v["objects"][0] for v in result["hard"] if v["type"] in ("clearance_blocked", "aisle_unreachable")}
        storage_ids = [f["id"] for f in space["furniture"] if f["type"] in ("wardrobe", "storage")]
        goals.append(("수납 가구 앞 사용 공간 확보", not any(i in blocked for i in storage_ids)))
    return goals


def score(space: dict, poses: dict, profile: str = "preference", result: dict | None = None) -> dict:
    result = result or validate(space, poses)
    baseline = space["baselineLayout"]["poses"]
    room_area = g.room_polygon(space["room"]).area
    w = PROFILES[profile]

    goals = preference_goals(space, poses, result)
    pref = sum(ok for _, ok in goals) / len(goals) if goals else 1.0
    zone = result["metrics"]["reachableRatio"]
    interference = min(1.0, result["metrics"]["interferenceArea"] / room_area * 4)
    if result["metrics"]["bedInWorkView"]:
        interference = min(1.0, interference + 0.3)
    cost, moved = move_cost(space, baseline, poses)
    move = min(1.0, cost / 10)

    total = w["pref"] * pref + w["zone"] * zone - w["int"] * interference - w["move"] * move
    # map the theoretical range [-(int+move), pref+zone] to 0..100
    lo, hi = -(w["int"] + w["move"]), w["pref"] + w["zone"]
    normalized = (total - lo) / (hi - lo) * 100
    # hard violations are shown, not hidden: each costs 10 points (§10.3)
    normalized = max(0.0, normalized - 10 * len(result["hard"]))
    return {
        "total": round(normalized, 1),
        "profile": profile,
        "breakdown": {"preference": round(pref, 3), "zone": round(zone, 3),
                      "interference": round(interference, 3), "move": round(move, 3)},
        "goals": [{"label": l, "ok": ok} for l, ok in goals],
        "moveCost": round(cost, 2),
        "movedCount": moved,
        "hardCount": len(result["hard"]),
    }
