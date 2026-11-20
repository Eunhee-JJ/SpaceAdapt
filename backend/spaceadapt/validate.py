"""Constraint validation (요구사항정의서 FR-07, FR-09, §10.1).

validate(space, poses) -> {"hard": [...], "soft": [...], "metrics": {...}}
Each violation: {"type", "objects", "geometry", "reason"}.
"""

from __future__ import annotations

from itertools import combinations

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import geometry as g

EPS_AREA = 1.0  # cm²; touching edges are not collisions

WORK_TYPES = {"desk", "chair"}
SLEEP_TYPES = {"bed"}
HOBBY_TYPES = {"sofa", "table"}

LABEL = {
    "bed": "침대", "desk": "책상", "chair": "의자", "storage": "수납장",
    "table": "테이블", "sofa": "소파", "wardrobe": "옷장", "fridge": "냉장고",
}


def _name(f: dict) -> str:
    return LABEL.get(f["type"], f["type"])


def josa(word: str, pair: str) -> str:
    """Attach the right Korean particle: pair like '이/가', '을/를', '과/와'."""
    with_batchim, without = pair.split("/")
    code = ord(word[-1]) - 0xAC00
    has = 0 <= code <= 11171 and code % 28 != 0
    return word + (with_batchim if has else without)


def _v(type_: str, objects: list[str], geom: BaseGeometry, reason: str) -> dict:
    return {"type": type_, "objects": objects, "geometry": g.coords(geom), "reason": reason}


def _paired(a: dict, b: dict) -> bool:
    return a.get("pairedWith") == b["id"] or b.get("pairedWith") == a["id"]


def validate(space: dict, poses: dict, aisle_width: float | None = None) -> dict:
    room = space["room"]
    room_poly = g.room_polygon(room)
    furniture = [f for f in space["furniture"] if f["id"] in poses]
    w_aisle = aisle_width or space.get("preferences", {}).get("minimumAisleWidth", 60)

    fp = {f["id"]: g.footprint(f, poses[f["id"]]) for f in furniture}
    cl = {f["id"]: g.clearance(f, poses[f["id"]]) for f in furniture}
    fixtures = g.fixture_polygons(room)
    openings = [g.opening_geom(room, op) for op in room.get("openings", [])]
    doors = [o for o in openings if o.type == "door"]
    windows = {op["id"]: op for op in room.get("openings", []) if op["type"] == "window"}

    hard: list[dict] = []
    soft: list[dict] = []

    # 1. inside room
    for f in furniture:
        out = fp[f["id"]].difference(room_poly)
        if out.area > EPS_AREA:
            hard.append(_v("outside_room", [f["id"]], out, f"{josa(_name(f), "이/가")} 방 밖으로 나갑니다."))

    # 2. furniture-furniture collision
    for a, b in combinations(furniture, 2):
        inter = fp[a["id"]].intersection(fp[b["id"]])
        if inter.area > EPS_AREA:
            hard.append(_v("collision", [a["id"], b["id"]], inter, f"{josa(_name(a), "과/와")} {josa(_name(b), "이/가")} 겹칩니다."))

    # 3. fixture collision
    for f in furniture:
        for fx_id, fx in fixtures:
            inter = fp[f["id"]].intersection(fx)
            if inter.area > EPS_AREA:
                hard.append(_v("fixture_collision", [f["id"], fx_id], inter, f"{josa(_name(f), "이/가")} 고정 구조물을 침범합니다."))

    # 4. door swing
    for d in doors:
        if d.swing.is_empty:
            continue
        for f in furniture:
            inter = fp[f["id"]].intersection(d.swing)
            if inter.area > EPS_AREA:
                hard.append(_v("door_swing", [f["id"], d.id], inter, f"{josa(_name(f), "이/가")} 문이 열리는 영역을 막습니다."))

    # 5. use-space (clearance) blocked by other furniture, fixtures, or walls
    for f in furniture:
        zone = cl[f["id"]]
        if zone.is_empty:
            continue
        blockers: list[BaseGeometry] = []
        names: list[str] = []
        for o in furniture:
            if o["id"] == f["id"] or _paired(f, o):
                continue
            inter = zone.intersection(fp[o["id"]])
            if inter.area > EPS_AREA:
                blockers.append(inter)
                names.append(o["id"])
        for fx_id, fx in fixtures:
            inter = zone.intersection(fx)
            if inter.area > EPS_AREA:
                blockers.append(inter)
                names.append(fx_id)
        out = zone.difference(room_poly)
        if out.area > EPS_AREA:
            blockers.append(out)
            names.append("wall")
        if blockers:
            hard.append(_v("clearance_blocked", [f["id"], *names], unary_union(blockers),
                           f"{josa(_name(f), "을/를")} 사용할 공간이 막혀 있습니다."))

    # 6. aisle: door → every furniture use-space must be reachable with width w_aisle
    obstacles = unary_union([*fp.values(), *(fx for _, fx in fixtures)])
    free = room_poly.difference(obstacles)
    core = free.buffer(-w_aisle / 2)
    reach: BaseGeometry = Polygon()
    if doors and not core.is_empty:
        entry = doors[0].entry_point(w_aisle / 2 + 1)
        parts = list(getattr(core, "geoms", [core]))
        best = min(parts, key=lambda p: p.distance(entry))
        if best.distance(entry) <= 2:
            reach = best.buffer(w_aisle / 2)
    if doors and reach.is_empty:
        hard.append(_v("door_blocked", [doors[0].id], doors[0].front_strip,
                       f"출입문 앞에 폭 {w_aisle:.0f}cm 통로가 없습니다."))
    else:
        for f in furniture:
            # only the unoccupied part of the use-space counts (a tucked-in chair is fine)
            zone = cl[f["id"]].intersection(free)
            if zone.area <= EPS_AREA:
                continue
            ratio = reach.intersection(zone).area / zone.area
            if ratio < 0.3:
                hard.append(_v("aisle_unreachable", [f["id"]], zone,
                               f"출입문에서 {_name(f)}까지 폭 {w_aisle:.0f}cm 통로가 없습니다."))

    # soft: window blocked by tall furniture
    for o in openings:
        if o.type != "window":
            continue
        sill = windows[o.id].get("sillHeight", 0)
        for f in furniture:
            if f.get("height", 0) > sill and fp[f["id"]].intersection(o.front_strip).area > EPS_AREA:
                soft.append(_v("window_blocked", [f["id"], o.id], fp[f["id"]].intersection(o.front_strip),
                               f"{josa(_name(f), "이/가")} 창문을 가립니다."))

    # activity zones and interference (FR-07)
    def zone_of(types: set[str]) -> BaseGeometry:
        parts = [fp[f["id"]].union(cl[f["id"]]) for f in furniture if f["type"] in types]
        return unary_union(parts).intersection(room_poly) if parts else Polygon()

    zones = {"sleep": zone_of(SLEEP_TYPES), "work": zone_of(WORK_TYPES), "hobby": zone_of(HOBBY_TYPES)}
    interference = zones["sleep"].buffer(30).intersection(zones["work"].buffer(30)).intersection(room_poly)

    bed_in_view = False
    for f in furniture:
        if f["type"] != "desk":
            continue
        cone = g.view_cone(poses[f["id"]]).intersection(room_poly)
        for b in furniture:
            if b["type"] in SLEEP_TYPES:
                seen = cone.intersection(fp[b["id"]])
                if seen.area > EPS_AREA:
                    bed_in_view = True
                    soft.append(_v("sleep_in_work_view", [f["id"], b["id"]], seen,
                                   f"책상에 앉으면 {josa(_name(b), "이/가")} 화면(카메라) 시야에 들어옵니다."))

    free_area = free.area
    metrics = {
        "hardCount": len(hard),
        "softCount": len(soft),
        "interferenceArea": round(interference.area, 1),
        "bedInWorkView": bed_in_view,
        "freeArea": round(free_area, 1),
        "reachableRatio": round(reach.intersection(free).area / free_area, 3) if free_area else 0.0,
    }
    return {
        "hard": hard,
        "soft": soft,
        "metrics": metrics,
        "zones": {k: g.coords(v) for k, v in zones.items()},
        "interference": g.coords(interference),
        "doorSwings": {d.id: g.coords(d.swing) for d in doors},
    }
