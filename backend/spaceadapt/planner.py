"""Heuristic layout generation (요구사항정의서 FR-08; v4 replaces CP-SAT).

1. For each movable item, enumerate wall-snapped poses (4 rotations, 20cm step)
   plus its baseline pose, and drop poses that fail single-item checks.
2. Beam search over items (largest first), rejecting pairwise conflicts.
3. Fully validate + score the final beam and return the best hard-violation-free layout.
Chairs paired with a desk are placed in front of that desk, not searched.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from . import geometry as g
from .score import PROFILES, move_cost, score
from .validate import EPS_AREA, validate

STEP = 20
BEAM = 80
PER_ITEM = 60


@dataclass
class Cand:
    pose: dict
    fp: BaseGeometry
    cl: BaseGeometry
    local: float  # lower is better


@dataclass
class State:
    poses: dict = field(default_factory=dict)
    fps: dict = field(default_factory=dict)
    cls: dict = field(default_factory=dict)
    cost: float = 0.0


def _chair_pose(desk: dict, desk_pose: dict, chair: dict) -> dict:
    fx, fy = g.front_vector(desk_pose)
    off = desk["depth"] / 2 + (desk.get("clearance", {}).get("front", 70)) / 2
    return {"x": round(desk_pose["x"] + fx * off, 1), "y": round(desk_pose["y"] + fy * off, 1),
            "rotation": desk_pose.get("rotation", 0)}


def _static_ok(fp, cl, room_poly, blockers: BaseGeometry, swings: BaseGeometry) -> bool:
    if fp.difference(room_poly).area > EPS_AREA:
        return False
    if fp.intersection(blockers).area > EPS_AREA or fp.intersection(swings).area > EPS_AREA:
        return False
    if not cl.is_empty and (cl.difference(room_poly).area > EPS_AREA or cl.intersection(blockers).area > EPS_AREA):
        return False
    return True


def _aisle_ok(st: "State", room_poly, fixtures, door, w: float) -> bool:
    """Same rule as validate() step 6, on the items placed so far."""
    if door is None:
        return True
    free = room_poly.difference(unary_union([*st.fps.values(), fixtures]))
    core = free.buffer(-w / 2)
    if core.is_empty:
        return False
    entry = door.entry_point(w / 2 + 1)
    parts = list(getattr(core, "geoms", [core]))
    best = min(parts, key=lambda p: p.distance(entry))
    if best.distance(entry) > 2:
        return False
    reach = best.buffer(w / 2)
    for cl in st.cls.values():
        zone = cl.intersection(free)
        if zone.area > EPS_AREA and reach.intersection(zone).area / zone.area < 0.3:
            return False
    return True


def _priorities(space: dict) -> dict:
    prefs = space.get("preferences", {})
    slots = {k: (v.get("value") if isinstance(v, dict) else v) for k, v in prefs.get("slots", {}).items()}
    w = prefs.get("activityWeights", {})
    return {
        "separate": bool(slots.get("sleepWorkSeparation", w.get("work", 0) >= 4)),
        "work": slots.get("primaryActivity") == "work" or w.get("work", 0) >= 4,
        "sleep": slots.get("primaryActivity") == "sleep" or w.get("sleep", 0) >= 4,
    }


def _pref_cost(f: dict, c: "Cand", st: "State", furn: dict, space: dict, door) -> float:
    """Preference-profile search heuristic; mirrors score.preference_goals()."""
    pr = _priorities(space)
    cost = 0.0
    room = space["room"]
    if f["type"] == "desk":
        if pr["separate"]:
            cone = g.view_cone(c.pose)
            if any(furn[i]["type"] == "bed" and cone.intersection(fp).area > EPS_AREA for i, fp in st.fps.items()):
                cost += 3
        if pr["work"]:
            wins = [g.opening_geom(room, o) for o in room.get("openings", []) if o["type"] == "window"]
            if wins:
                wc = wins[0].entry_point(0)
                if math.hypot(c.pose["x"] - wc.x, c.pose["y"] - wc.y) > 130:
                    cost += 1
    if f["type"] == "bed" and pr["sleep"] and door is not None:
        if c.fp.distance(door.entry_point(0)) < 80:
            cost += 2
    return cost


def _wall_poses(f: dict, bounds) -> list[dict]:
    minx, miny, maxx, maxy = bounds
    out = []
    for rot in (0, 90, 180, 270):
        ex, ey = (f["width"], f["depth"]) if rot in (0, 180) else (f["depth"], f["width"])
        xs = [minx + ex / 2 + i * STEP for i in range(int((maxx - minx - ex) // STEP) + 1)] + [maxx - ex / 2]
        ys = [miny + ey / 2 + i * STEP for i in range(int((maxy - miny - ey) // STEP) + 1)] + [maxy - ey / 2]
        for x in xs:
            out.append({"x": x, "y": miny + ey / 2, "rotation": rot})
            out.append({"x": x, "y": maxy - ey / 2, "rotation": rot})
        for y in ys:
            out.append({"x": minx + ex / 2, "y": y, "rotation": rot})
            out.append({"x": maxx - ex / 2, "y": y, "rotation": rot})
    return out


def _local_cost(f: dict, pose: dict, base: dict, profile: str, space: dict) -> float:
    dist = math.hypot(pose["x"] - base["x"], pose["y"] - base["y"]) / 100
    rotated = (pose.get("rotation", 0) - base.get("rotation", 0)) % 360 != 0
    move = dist + (0.5 if rotated else 0)
    w_move = PROFILES[profile]["move"] * 10
    return w_move * move


def plan_ranked(space: dict, profile: str = "preference", baseline: dict | None = None) -> list[dict]:
    """All hard-violation-free layouts from the final beam, best first."""
    room = space["room"]
    room_poly = g.room_polygon(room)
    baseline = baseline or space["baselineLayout"]["poses"]
    furn = {f["id"]: f for f in space["furniture"] if f["id"] in baseline}
    fixtures = unary_union([p for _, p in g.fixture_polygons(room)])
    swings = unary_union([g.opening_geom(room, o).swing for o in room.get("openings", []) if o["type"] == "door"])

    doors = [g.opening_geom(room, o) for o in room.get("openings", []) if o["type"] == "door"]
    door = doors[0] if doors else None
    w_aisle = space.get("preferences", {}).get("minimumAisleWidth", 60)

    chairs = {f["pairedWith"]: f for f in furn.values() if f["type"] == "chair" and f.get("pairedWith") in furn}
    chair_ids = {c["id"] for c in chairs.values()}
    fixed = [f for f in furn.values() if not f.get("movable", True) and f["id"] not in chair_ids]
    movable = [f for f in furn.values() if f.get("movable", True) and f["id"] not in chair_ids]
    movable.sort(key=lambda f: -f["width"] * f["depth"])

    fixed_fp = unary_union([g.footprint(f, baseline[f["id"]]) for f in fixed]) if fixed else None
    blockers = unary_union([fixtures, fixed_fp]) if fixed_fp is not None else fixtures

    def candidates(f: dict) -> list[Cand]:
        base = baseline[f["id"]]
        poses = [dict(base)] + _wall_poses(f, room_poly.bounds)
        out, seen = [], set()
        for p in poses:
            key = (round(p["x"]), round(p["y"]), p["rotation"] % 360)
            if key in seen:
                continue
            seen.add(key)
            fp, cl = g.footprint(f, p), g.clearance(f, p)
            if f["id"] in chairs:  # desk: its chair must fit too
                cp = _chair_pose(f, p, chairs[f["id"]])
                cfp = g.footprint(chairs[f["id"]], cp)
                if not _static_ok(cfp, Polygon(), room_poly, blockers, swings):
                    continue
                fp_all = fp.union(cfp)
            else:
                fp_all = fp
            if _static_ok(fp_all, cl, room_poly, blockers, swings):
                out.append(Cand(p, fp_all, cl, _local_cost(f, p, base, profile, space)))
        out.sort(key=lambda c: c.local)
        return out

    init = State()
    for f in fixed:
        p = baseline[f["id"]]
        init.poses[f["id"]] = dict(p)
        init.fps[f["id"]] = g.footprint(f, p)
        init.cls[f["id"]] = g.clearance(f, p)

    beam = [init]
    for f in movable:
        cands = candidates(f)
        nxt: list[State] = []
        for st in beam:
            added = 0
            for c in cands:
                ok = True
                for oid, ofp in st.fps.items():
                    if c.fp.intersection(ofp).area > EPS_AREA:
                        ok = False
                        break
                    if not c.cl.is_empty and c.cl.intersection(ofp).area > EPS_AREA:
                        ok = False
                        break
                    ocl = st.cls[oid]
                    if not ocl.is_empty and c.fp.intersection(ocl).area > EPS_AREA:
                        ok = False
                        break
                if not ok:
                    continue
                extra = _pref_cost(f, c, st, furn, space, door) if profile == "preference" else 0.0
                ns = State(dict(st.poses), dict(st.fps), dict(st.cls), st.cost + c.local + extra)
                ns.poses[f["id"]] = c.pose
                ns.fps[f["id"]] = c.fp
                ns.cls[f["id"]] = c.cl
                nxt.append(ns)
                added += 1
                if added >= PER_ITEM:
                    break
        if not nxt:
            return []
        # keep the cheapest states that still leave an aisle, at most 3 per pose of this item
        nxt.sort(key=lambda s: s.cost)
        kept, per_pose = [], {}
        for s in nxt:
            k = tuple(s.poses[f["id"]].values())
            if per_pose.get(k, 0) >= 2:
                continue
            if not _aisle_ok(s, room_poly, fixtures, door, w_aisle):
                continue
            per_pose[k] = per_pose.get(k, 0) + 1
            kept.append(s)
            if len(kept) >= BEAM:
                break
        if not kept:
            return []
        beam = kept

    finals = []
    for st in beam:
        poses = dict(st.poses)
        for desk_id, chair in chairs.items():
            if poses[desk_id] == baseline[desk_id] and chair["id"] in baseline:
                poses[chair["id"]] = dict(baseline[chair["id"]])  # desk untouched → chair untouched
            else:
                poses[chair["id"]] = _chair_pose(furn[desk_id], poses[desk_id], chair)
        res = validate(space, poses)
        if res["hard"]:
            continue
        finals.append({"poses": poses, "validation": res, "score": score(space, poses, profile, res)})
    finals.sort(key=lambda r: _rank_key(r, profile))
    return finals


def _rank_key(r: dict, profile: str):
    s = r["score"]
    if profile == "minimal_move":
        return (s["movedCount"], s["moveCost"], -s["total"])
    return (-s["breakdown"]["preference"], -s["total"])


def _same(a: dict, b: dict) -> bool:
    return all(a["poses"][k] == b["poses"].get(k) for k in a["poses"])


def plan(space: dict, profile: str = "preference", baseline: dict | None = None) -> dict | None:
    finals = plan_ranked(space, profile, baseline)
    return finals[0] if finals else None


def plan_all(space: dict) -> dict:
    """Baseline + two distinct candidate layouts for the comparison screen (FR-08, FR-10)."""
    base_poses = space["baselineLayout"]["poses"]
    base_val = validate(space, base_poses)
    out = {"baseline": {"poses": base_poses, "validation": base_val,
                        "score": score(space, base_poses, "preference", base_val)}}
    minimal = plan_ranked(space, "minimal_move")
    pref = plan_ranked(space, "preference")
    out["minimal_move"] = minimal[0] if minimal else None
    choice = None
    for r in pref:
        if out["minimal_move"] is None or not _same(r, out["minimal_move"]):
            choice = r
            break
    out["preference"] = choice or (pref[0] if pref else None)
    return out


__all__ = ["plan", "plan_ranked", "plan_all", "move_cost"]
