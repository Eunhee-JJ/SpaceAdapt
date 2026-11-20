"""2D geometry for the SpaceAdapt space model.

Conventions (요구사항정의서 §8):
- unit cm, origin top-left, x right, y down
- furniture pose (x, y) is the CENTER, rotation is clockwise degrees on screen
- at rotation 0, width runs along x, depth along y, front faces +y
Shapely's rotate() is counter-clockwise in y-up math, which is clockwise on a
y-down screen, so we pass the rotation through unchanged.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

Vec = tuple[float, float]


def _unit(v: Vec) -> Vec:
    n = math.hypot(*v)
    return (v[0] / n, v[1] / n)


def _add(a: Vec, b: Vec, k: float = 1.0) -> Vec:
    return (a[0] + b[0] * k, a[1] + b[1] * k)


def _dot(a: Vec, b: Vec) -> float:
    return a[0] * b[0] + a[1] * b[1]


def place(local: BaseGeometry, pose: dict) -> BaseGeometry:
    g = affinity.rotate(local, pose.get("rotation", 0), origin=(0, 0))
    return affinity.translate(g, pose["x"], pose["y"])


def footprint(f: dict, pose: dict) -> Polygon:
    w, d = f["width"], f["depth"]
    return place(box(-w / 2, -d / 2, w / 2, d / 2), pose)


def clearance(f: dict, pose: dict) -> BaseGeometry:
    """Union of the furniture's use-space strips (front/back/left/right)."""
    w, d = f["width"], f["depth"]
    c = f.get("clearance") or {}
    parts = []
    if c.get("front"):
        parts.append(box(-w / 2, d / 2, w / 2, d / 2 + c["front"]))
    if c.get("back"):
        parts.append(box(-w / 2, -d / 2 - c["back"], w / 2, -d / 2))
    if c.get("left"):
        parts.append(box(-w / 2 - c["left"], -d / 2, -w / 2, d / 2))
    if c.get("right"):
        parts.append(box(w / 2, -d / 2, w / 2 + c["right"], d / 2))
    if not parts:
        return Polygon()
    return place(unary_union(parts), pose)


def front_vector(pose: dict) -> Vec:
    r = math.radians(pose.get("rotation", 0))
    # local front (0, 1) rotated clockwise on a y-down screen
    return (-math.sin(r), math.cos(r))


def room_polygon(room: dict) -> Polygon:
    return Polygon(room["polygon"])


def inward_normal(room_poly: Polygon, a: Vec, b: Vec) -> Vec:
    u = _unit((b[0] - a[0], b[1] - a[1]))
    n1 = (-u[1], u[0])
    mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    return n1 if room_poly.contains(Point(_add(mid, n1))) else (u[1], -u[0])


@dataclass
class OpeningGeom:
    id: str
    type: str
    a: Vec  # opening start on the wall
    b: Vec  # opening end on the wall
    normal: Vec  # inward
    swing: BaseGeometry  # door swing sector inside the room (empty if none)
    front_strip: BaseGeometry  # strip just inside the opening

    def entry_point(self, depth: float) -> Point:
        mid = ((self.a[0] + self.b[0]) / 2, (self.a[1] + self.b[1]) / 2)
        return Point(_add(mid, self.normal, depth))


def opening_geom(room: dict, op: dict, strip_depth: float = 30) -> OpeningGeom:
    poly = room_polygon(room)
    pts = room["polygon"]
    i = op["wall"]
    wa, wb = tuple(pts[i]), tuple(pts[(i + 1) % len(pts)])
    u = _unit((wb[0] - wa[0], wb[1] - wa[1]))
    n = inward_normal(poly, wa, wb)
    a = _add(wa, u, op["offset"])
    b = _add(a, u, op["width"])
    strip = Polygon([a, b, _add(b, n, strip_depth), _add(a, n, strip_depth)])

    swing: BaseGeometry = Polygon()
    if op["type"] == "door" and op.get("swing", "in") == "in":
        # hinge side is judged by a viewer inside the room facing the door
        facing = (-n[0], -n[1])
        right = (-facing[1], facing[0])
        right_end, left_end = (b, a) if _dot(u, right) > 0 else (a, b)
        hinge = right_end if op.get("hinge", "left") == "right" else left_end
        other = left_end if hinge == right_end else right_end
        v = _unit((other[0] - hinge[0], other[1] - hinge[1]))
        r = op["width"]
        arc = [
            _add(hinge, (math.cos(t) * v[0] + math.sin(t) * n[0], math.cos(t) * v[1] + math.sin(t) * n[1]), r)
            for t in (k * (math.pi / 2) / 16 for k in range(17))
        ]
        swing = Polygon([hinge, *arc])
    return OpeningGeom(op["id"], op["type"], a, b, n, swing, strip)


def fixture_polygons(room: dict) -> list[tuple[str, Polygon]]:
    return [(fx["id"], Polygon(fx["polygon"])) for fx in room.get("fixtures", [])]


def view_cone(pose: dict, half_angle_deg: float = 35, reach: float = 400) -> Polygon:
    """Area a desk-mounted camera/monitor faces (front direction)."""
    fx, fy = front_vector(pose)
    base = math.atan2(fy, fx)
    h = math.radians(half_angle_deg)
    o = (pose["x"], pose["y"])
    pts = [o] + [
        (o[0] + reach * math.cos(base + t), o[1] + reach * math.sin(base + t))
        for t in (-h + k * (2 * h) / 8 for k in range(9))
    ]
    return Polygon(pts)


def coords(g: BaseGeometry) -> list:
    """Serialize a polygonal geometry to a list of rings (exteriors only)."""
    if g.is_empty:
        return []
    geoms = getattr(g, "geoms", [g])
    out = []
    for p in geoms:
        if isinstance(p, Polygon) and not p.is_empty:
            out.append([[round(x, 1), round(y, 1)] for x, y in p.exterior.coords])
    return out
