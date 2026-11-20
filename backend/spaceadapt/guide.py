"""Move-order guide (요구사항정의서 FR-11, v4: simple ordering + temp spot on cycles)."""

from __future__ import annotations

import math

from . import geometry as g
from .score import TYPE_WEIGHT
from .validate import EPS_AREA, LABEL, josa

WALL_NAMES = ["위쪽", "오른쪽", "아래쪽", "왼쪽"]


def _moved(a: dict, b: dict) -> bool:
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"]) >= 5 or (a.get("rotation", 0) - b.get("rotation", 0)) % 360 != 0


def _where(room: dict, f: dict, pose: dict) -> str:
    fp = g.footprint(f, pose)
    pts = room["polygon"]
    dists = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        dists.append((g.LineString([a, b]).distance(fp), i))
    d, i = min(dists)
    wall = WALL_NAMES[i] if len(pts) == 4 else f"{i + 1}번"
    return f"{wall} 벽 쪽" if d < 15 else "방 가운데"


def build_guide(space: dict, poses: dict, baseline: dict | None = None) -> list[dict]:
    baseline = baseline or space["baselineLayout"]["poses"]
    room = space["room"]
    furn = {f["id"]: f for f in space["furniture"]}
    moved = [i for i in poses if i in baseline and _moved(baseline[i], poses[i])]

    # A must wait for B when A's target overlaps where B currently stands
    deps = {a: set() for a in moved}
    for a in moved:
        target = g.footprint(furn[a], poses[a])
        for b in moved:
            if a != b and target.intersection(g.footprint(furn[b], baseline[b])).area > EPS_AREA:
                deps[a].add(b)

    order, temp = [], set()
    remaining = set(moved)
    while remaining:
        ready = sorted((a for a in remaining if not (deps[a] & remaining)),
                       key=lambda i: -TYPE_WEIGHT.get(furn[i]["type"], 1))
        if not ready:  # cycle: park the lightest not-yet-parked blocker temporarily
            pool = remaining - temp
            if not pool:  # only parked items left; their mutual deps were already dropped
                order.extend(sorted(remaining))
                break
            parked = min(pool, key=lambda i: TYPE_WEIGHT.get(furn[i]["type"], 1))
            temp.add(parked)
            for a in remaining:
                deps[a].discard(parked)
            continue
        order.append(ready[0])
        remaining.discard(ready[0])

    steps = []
    for i in temp:
        steps.append({"id": i, "temporary": True,
                      "text": f"먼저 {josa(LABEL.get(furn[i]['type'], furn[i]['type']), '을/를')} 잠시 빈 바닥으로 옮겨 두세요."})
    for i in order:
        f, a, b = furn[i], baseline[i], poses[i]
        name = LABEL.get(f["type"], f["type"])
        dist = math.hypot(a["x"] - b["x"], a["y"] - b["y"]) / 100
        rot = (b.get("rotation", 0) - a.get("rotation", 0)) % 360
        parts = [f"{josa(name, '을/를')} {_where(room, f, b)}으로 옮기세요" if dist >= 0.05 else f"{josa(name, '을/를')} 제자리에서"]
        if rot:
            parts.append(f"시계 방향으로 {rot}° 돌려 놓으세요" if rot != 180 else "반대 방향으로 돌려 놓으세요")
        cautions = []
        if TYPE_WEIGHT.get(f["type"], 1) >= 3:
            cautions.append("무거운 가구라 두 사람이 옮기는 것을 권장합니다.")
        if "wheels" in f.get("attributes", []):
            cautions.append("바퀴로 밀어서 옮길 수 있습니다.")
        steps.append({"id": i, "temporary": False, "from": a, "to": b, "distanceM": round(dist, 2),
                      "rotation": rot, "text": ", ".join(parts) + ".", "cautions": cautions})
    for n, s in enumerate(steps, 1):
        s["order"] = n
    return steps
