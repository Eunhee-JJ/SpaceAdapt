"""Measure pass criteria P-2, P-3, P-4, P-8 on the three synthetic rooms.

Run: uv run python scripts/measure.py [--no-vlm]
Writes ../data/measurements.json and prints a summary table.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from spaceadapt import vlm  # noqa: E402
from spaceadapt.planner import plan_all  # noqa: E402
from spaceadapt.questions import apply_answers, build_questions  # noqa: E402
from spaceadapt.validate import validate  # noqa: E402


def norm(slot, value, space):
    if slot == "fixedItems":
        furn = {f["id"]: f["type"] for f in space["furniture"]}
        vals = value if isinstance(value, list) else [value]
        return slot, tuple(sorted(furn.get(v, v) for v in vals))
    return slot, value


def covered(qs):
    return sum(len(q["items"]) if q["type"] == "confirm" else 1 for q in qs)


def main(use_vlm: bool):
    out = {"rooms": {}}
    for rid in ("room-a", "room-b", "room-c"):
        space = json.loads((ROOT / "data" / "rooms" / f"{rid}.json").read_text())
        r = {}

        # P-4 / P-8
        if use_vlm:
            draft = vlm.analyze(str(ROOT / space["image"]))
        else:
            draft = vlm.mock_from_truth(space)
        truth_types = {f["type"] for f in space["furniture"]}
        found = {f["type"] for f in draft["furniture"]}
        r["furnitureRecall"] = round(len(truth_types & found) / len(truth_types), 3)
        truth = {norm(c["slot"], c["value"], space) for c in space["truth"]["lifeCues"]}
        pred = {norm(c["slot"], c["value"], space) for c in draft["lifeCues"]}
        r["cueRecall"] = round(len(truth & pred) / len(truth), 3)
        r["cuePrecision"] = round(len(truth & pred) / len(pred), 3) if pred else 0.0
        r["vlmMs"] = draft.get("elapsedMs")
        r["slotsCoveredWithCues"] = covered(build_questions(space, draft["lifeCues"]))
        r["slotsCoveredWithoutCues"] = covered(build_questions(space, []))
        r["draft"] = draft

        # P-2 with the user confirming only correct cues
        cue_ans = [{"slot": c["slot"], "value": c["value"],
                    "accepted": norm(c["slot"], c["value"], space) in truth} for c in draft["lifeCues"]]
        apply_answers(space, cue_ans, [])
        layouts = plan_all(space)
        r["baseline"] = {"hard": layouts["baseline"]["score"]["hardCount"],
                         "pref": layouts["baseline"]["score"]["breakdown"]["preference"],
                         "total": layouts["baseline"]["score"]["total"]}
        for k in ("preference", "minimal_move"):
            l = layouts[k]
            r[k] = None if l is None else {"hard": l["score"]["hardCount"],
                                           "pref": l["score"]["breakdown"]["preference"],
                                           "total": l["score"]["total"], "moved": l["score"]["movedCount"]}
        r["P2"] = bool(layouts["preference"] and layouts["preference"]["score"]["hardCount"] == 0
                       and layouts["preference"]["score"]["breakdown"]["preference"] >= r["baseline"]["pref"])

        # P-3: re-validation latency
        poses = space["baselineLayout"]["poses"]
        ts = []
        for _ in range(50):
            t = time.perf_counter()
            validate(space, poses)
            ts.append((time.perf_counter() - t) * 1000)
        r["validateP95ms"] = round(statistics.quantiles(ts, n=20)[18], 1)
        out["rooms"][rid] = r

    rs = out["rooms"].values()
    out["summary"] = {
        "P2_allRooms": all(r["P2"] for r in rs),
        "P3_maxP95ms": max(r["validateP95ms"] for r in rs),
        "P4_meanFurnitureRecall": round(statistics.mean(r["furnitureRecall"] for r in rs), 3),
        "P8_meanCueRecall": round(statistics.mean(r["cueRecall"] for r in rs), 3),
        "P8_extraSlotsPer3Questions": round(statistics.mean(
            r["slotsCoveredWithCues"] - r["slotsCoveredWithoutCues"] for r in rs), 2),
        "source": "vlm" if use_vlm else "mock",
    }
    (ROOT / "data" / "measurements.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(out["summary"], ensure_ascii=False, indent=2))
    for rid, r in out["rooms"].items():
        print(rid, {k: r[k] for k in ("furnitureRecall", "cueRecall", "cuePrecision", "vlmMs",
                                       "slotsCoveredWithCues", "slotsCoveredWithoutCues", "validateP95ms", "P2")},
              "| base", r["baseline"], "| A", r["preference"], "| B", r["minimal_move"])


if __name__ == "__main__":
    main(use_vlm="--no-vlm" not in sys.argv)
