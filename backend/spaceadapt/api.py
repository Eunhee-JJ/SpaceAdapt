"""FastAPI app (요구사항정의서 §11, v4: in-memory sessions, local demo).

Run: uv run uvicorn spaceadapt.api:app --reload --port 8010
"""

from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .guide import build_guide
from .planner import plan_all
from .score import score
from .validate import validate

ROOT = Path(__file__).resolve().parents[2]
ROOMS = ROOT / "data" / "rooms"

app = FastAPI(title="SpaceAdapt")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

SESSIONS: dict[str, dict] = {}


def _room(room_id: str) -> dict:
    p = ROOMS / f"{room_id}.json"
    if not p.exists():
        raise HTTPException(404, f"unknown room {room_id}")
    return json.loads(p.read_text())


def _session(sid: str) -> dict:
    if sid not in SESSIONS:
        raise HTTPException(404, "unknown session")
    return SESSIONS[sid]


def _public(space: dict) -> dict:
    """Space without ground-truth answers (those are for measurement only)."""
    out = {k: v for k, v in space.items() if k not in ("truth", "referenceLayout")}
    return out


class NewSession(BaseModel):
    roomId: str = "room-a"


class Poses(BaseModel):
    poses: dict[str, dict]
    profile: str = "preference"


@app.get("/rooms")
def list_rooms():
    out = []
    for p in sorted(ROOMS.glob("*.json")):
        d = json.loads(p.read_text())
        out.append({"id": d["id"], "title": d.get("title", d["id"]), "scenario": d.get("scenario"),
                    "hasImage": bool(d.get("image"))})
    return out


@app.get("/rooms/{room_id}/image")
def room_image(room_id: str):
    d = _room(room_id)
    if not d.get("image"):
        raise HTTPException(404, "no image")
    return FileResponse(ROOT / d["image"])


@app.post("/sessions")
def create_session(body: NewSession):
    sid = uuid.uuid4().hex[:12]
    SESSIONS[sid] = {"id": sid, "space": _room(body.roomId), "layouts": None}
    return {"id": sid, "space": _public(SESSIONS[sid]["space"])}


@app.get("/sessions/{sid}")
def get_session(sid: str):
    s = _session(sid)
    return {"id": sid, "space": _public(s["space"])}


@app.put("/sessions/{sid}/space")
def put_space(sid: str, space: dict):
    s = _session(sid)
    truth = s["space"].get("truth")
    s["space"] = copy.deepcopy(space)
    if truth is not None:
        s["space"]["truth"] = truth
    s["layouts"] = None
    return {"ok": True}


@app.post("/sessions/{sid}/validate")
def validate_layout(sid: str, body: Poses):
    space = _session(sid)["space"]
    res = validate(space, body.poses)
    return {"validation": res, "score": score(space, body.poses, body.profile, res)}


@app.post("/sessions/{sid}/layouts")
def make_layouts(sid: str):
    s = _session(sid)
    s["layouts"] = plan_all(s["space"])
    return s["layouts"]


@app.post("/sessions/{sid}/guide")
def guide(sid: str, body: Poses):
    return {"steps": build_guide(_session(sid)["space"], body.poses)}
