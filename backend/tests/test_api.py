from fastapi.testclient import TestClient

from spaceadapt.api import app

client = TestClient(app)


def test_full_manual_flow():
    """P-1 (backend part): session → validate baseline → 2 layouts → guide."""
    rooms = client.get("/rooms").json()
    assert {r["id"] for r in rooms} == {"room-a", "room-b", "room-c"}

    s = client.post("/sessions", json={"roomId": "room-c"}).json()
    sid, space = s["id"], s["space"]
    assert "truth" not in space

    base = space["baselineLayout"]["poses"]
    v = client.post(f"/sessions/{sid}/validate", json={"poses": base}).json()
    assert v["validation"]["hard"]

    layouts = client.post(f"/sessions/{sid}/layouts").json()
    for k in ("preference", "minimal_move"):
        assert layouts[k]["validation"]["hard"] == []

    steps = client.post(f"/sessions/{sid}/guide", json={"poses": layouts["minimal_move"]["poses"]}).json()["steps"]
    assert steps and all(st["text"] for st in steps)


def test_room_image_served():
    r = client.get("/rooms/room-a/image")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


def test_edit_and_revalidate():
    sid = client.post("/sessions", json={"roomId": "room-b"}).json()["id"]
    space = client.get(f"/sessions/{sid}").json()["space"]
    poses = dict(space["baselineLayout"]["poses"])
    poses["bed-1"] = {"x": 55, "y": 190, "rotation": 0}  # pull the bed away from the door
    v = client.post(f"/sessions/{sid}/validate", json={"poses": poses}).json()
    assert not any(x["type"] == "door_swing" for x in v["validation"]["hard"])
