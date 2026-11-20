"""Local VLM: photo → furniture list + life cues (요구사항정의서 FR-05).

Model: mlx-community/Qwen3-VL-8B-Instruct-4bit via mlx-vlm (Apple Silicon).
Set SPACEADAPT_VLM=mock to skip the model (NFR-03 fallback) and
SPACEADAPT_VLM_MODEL to swap in the 4B model.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

MODEL_ID = os.environ.get("SPACEADAPT_VLM_MODEL", "mlx-community/Qwen3-VL-8B-Instruct-4bit")
FURNITURE_TYPES = ["bed", "desk", "chair", "storage", "table", "sofa", "wardrobe", "fridge"]

# slot → allowed values (must match questions.QUESTION_BANK)
SLOTS = {
    "primaryActivity": ["work", "sleep", "hobby"],
    "sleepWorkSeparation": [True],
    "mainPain": ["storage", "workspace", "aisle", "sleep"],
    "hobbySpace": [True],
    "fixedItems": ["<furniture type>"],
}

PROMPT = """이 사진은 1인 가구의 작은 방이다. 사진을 보고 아래 JSON 하나만 출력하라. 설명 문장은 쓰지 마라.

{
  "furniture": [{"type": "<bed|desk|chair|storage|table|sofa|wardrobe|fridge>", "count": <int>}],
  "lifeCues": [
    {"evidence": "<사진에서 실제로 보이는 물건·상태를 한국어로 짧게>",
     "objectType": "<관련 가구 type 또는 null>",
     "slot": "<primaryActivity|sleepWorkSeparation|mainPain|hobbySpace|fixedItems>",
     "value": <slot에 맞는 값>}
  ]
}

slot 규칙:
- primaryActivity: 방에서 가장 많이 하는 활동. "work"(모니터·노트북·업무 흔적), "sleep"(암막 커튼·수면 안대 등 수면 환경), "hobby"(악기·운동기구 등)
- sleepWorkSeparation: true — 침대와 책상이 붙어 있거나 마주 봐서 업무와 수면이 섞여 보일 때
- mainPain: "storage"(물건·옷이 넘침), "workspace"(책상 위가 비좁음), "aisle"(바닥 가운데를 가구가 막음), "sleep"(침대가 문 바로 옆 등)
- hobbySpace: true — 요가매트 등 바닥을 펴서 쓰는 취미 도구가 보일 때
- fixedItems: 붙박이처럼 옮길 수 없어 보이는 가구의 type

사진에 실제로 보이는 것만 근거로 삼고, 단서는 최대 4개. 서로 다른 물건은 따로 적는다(예: 수면 안대와 요가매트는 별개 단서)."""

_lock = threading.Lock()
_model = None


def _load():
    global _model
    with _lock:
        if _model is None:
            from mlx_vlm import load
            from mlx_vlm.utils import load_config

            model, processor = load(MODEL_ID)
            _model = (model, processor, load_config(MODEL_ID))
    return _model


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"\{.*\}", text, flags=re.S)
    if not m:
        raise ValueError("no JSON object in model output")
    return json.loads(m.group(0))


def _clean(raw: dict) -> dict:
    furniture = [
        {"type": f["type"], "count": int(f.get("count", 1) or 1)}
        for f in raw.get("furniture", [])
        if isinstance(f, dict) and f.get("type") in FURNITURE_TYPES
    ]
    cues = []
    for c in raw.get("lifeCues", []):
        if not isinstance(c, dict) or c.get("slot") not in SLOTS or not c.get("evidence"):
            continue
        v = c.get("value")
        if c["slot"] == "fixedItems":
            v = v if isinstance(v, str) and v in FURNITURE_TYPES else c.get("objectType")
            if v not in FURNITURE_TYPES:
                continue
        elif c["slot"] in ("sleepWorkSeparation", "hobbySpace"):
            v = True
        elif v not in SLOTS[c["slot"]]:
            continue
        cues.append({"evidence": str(c["evidence"])[:60], "objectType": c.get("objectType"),
                     "slot": c["slot"], "value": v, "status": "estimated"})
    seen, uniq = set(), []
    for c in cues:
        if c["slot"] not in seen:
            seen.add(c["slot"])
            uniq.append(c)
    return {"furniture": furniture, "lifeCues": uniq[:4]}


def mock_from_truth(space: dict) -> dict:
    """NFR-03: ground-truth cues stand in for the model."""
    types: dict[str, int] = {}
    for f in space["furniture"]:
        types[f["type"]] = types.get(f["type"], 0) + 1
    furn = {f["id"]: f["type"] for f in space["furniture"]}
    cues = []
    for c in space.get("truth", {}).get("lifeCues", []):
        v = c["value"]
        if c["slot"] == "fixedItems":
            v = furn.get(v[0], v[0]) if isinstance(v, list) else v
        cues.append({"evidence": c["evidence"], "objectType": furn.get(c["objectIds"][0]) if c["objectIds"] else None,
                     "slot": c["slot"], "value": v, "status": "estimated"})
    return {"furniture": [{"type": t, "count": n} for t, n in types.items()], "lifeCues": cues,
            "source": "mock", "elapsedMs": 0}


def analyze(image_path: str, max_tokens: int = 700) -> dict:
    """Run the VLM once (one retry on bad JSON). Raises on failure; caller decides on fallback."""
    from mlx_vlm import generate
    from mlx_vlm.prompt_utils import apply_chat_template

    model, processor, config = _load()
    prompt = apply_chat_template(processor, config, PROMPT, num_images=1)
    t = time.perf_counter()
    last_err = None
    for _ in range(2):
        out = generate(model, processor, prompt, image=[image_path], max_tokens=max_tokens,
                       temperature=0.0, verbose=False)
        text = getattr(out, "text", out)
        try:
            res = _clean(_extract_json(text))
            res.update(source="vlm", model=MODEL_ID, elapsedMs=round((time.perf_counter() - t) * 1000))
            return res
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
    raise RuntimeError(f"VLM output not parseable: {last_err}")


def is_mock() -> bool:
    return os.environ.get("SPACEADAPT_VLM", "").lower() == "mock"
