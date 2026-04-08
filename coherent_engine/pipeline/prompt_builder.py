"""
PromptBuilderSkill — coherent_engine
将 planner shot 结构化输出转换为生成模型可消费的 prompt 结构。

设计原则：
- 纯函数，无外部依赖，同输入同输出
- 缺字段用空值/默认映射，不阻断
- 映射表从本地 JSON 加载（可版本化）
- 输出落盘到 run_trace/artifact，不直接影响生成链路
"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

_MAPPINGS_PATH = Path(__file__).parent / "prompt_mappings.json"

# 默认映射（当 prompt_mappings.json 不存在时使用）
_DEFAULT_MAPPINGS: Dict[str, Any] = {
    "camera_framing": {
        "close":    "close-up shot",
        "medium":   "medium shot",
        "wide":     "wide shot",
        "extreme":  "extreme close-up",
    },
    "camera_angle": {
        "eye":   "eye level",
        "low":   "low angle",
        "high":  "high angle",
        "bird":  "bird's eye view",
    },
    "camera_movement": {
        "static": "static camera",
        "pan":    "camera pan",
        "tilt":   "camera tilt",
        "zoom":   "zoom in",
        "dolly":  "dolly shot",
    },
    "brand_rules": {
        "brand.example.v1": {
            "style_prompt": "clean minimalist style, brand consistent",
            "positive_extra": "professional lighting, sharp focus",
            "negative_extra": "watermark, logo, text overlay",
        }
    },
    "character": {
        "char.xiaojiu.v1": {
            "positive_extra": "consistent character appearance, same outfit",
            "negative_extra": "character inconsistency, different face",
        }
    },
    "scene_tag_map": {
        "室内": "indoor",
        "室外": "outdoor",
        "白天": "daytime, natural lighting",
        "夜景": "nighttime, artificial lighting",
        "客厅": "living room",
        "办公室": "office",
        "街道": "street",
    },
    "defaults": {
        "negative_prompt_base": "blurry, low quality, distorted, deformed, ugly, bad anatomy",
        "cfg": 7.0,
        "steps": 20,
        "seed": -1,
    }
}


def _load_mappings() -> Dict[str, Any]:
    if _MAPPINGS_PATH.exists():
        try:
            return json.loads(_MAPPINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return _DEFAULT_MAPPINGS


def build_prompt(shot: Dict[str, Any], mappings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    将单个 shot dict 转换为 prompt 结构。
    缺字段用默认值，不抛异常。
    """
    m = mappings or _load_mappings()
    defaults = m.get("defaults", _DEFAULT_MAPPINGS["defaults"])

    positive_parts: List[str] = []
    negative_parts: List[str] = [defaults.get("negative_prompt_base", "")]

    # scene
    scene = (shot.get("scene") or "").strip()
    if scene:
        positive_parts.append(scene)

    # scene_tags
    tag_map = m.get("scene_tag_map", _DEFAULT_MAPPINGS["scene_tag_map"])
    for tag in (shot.get("scene_tags") or []):
        mapped = tag_map.get(tag, "")
        if mapped:
            positive_parts.append(mapped)

    # action
    action = (shot.get("action") or "").strip()
    if action:
        positive_parts.append(action)

    # camera
    framing = m.get("camera_framing", {}).get(
        shot.get("camera_framing", "medium"), "medium shot")
    angle = m.get("camera_angle", {}).get(
        shot.get("camera_angle", "eye"), "eye level")
    movement = m.get("camera_movement", {}).get(
        shot.get("camera_movement", "static"), "static camera")
    positive_parts += [framing, angle, movement]

    # must_keep → positive
    for item in (shot.get("must_keep") or []):
        if item:
            positive_parts.append(str(item))

    # must_avoid → negative
    for item in (shot.get("must_avoid") or []):
        if item:
            negative_parts.append(str(item))

    # brand_rules mapping
    brand_id = (shot.get("brand_rules_id") or "").strip()
    brand_map = m.get("brand_rules", {}).get(brand_id, {})
    style_prompt = brand_map.get("style_prompt", (shot.get("style") or "").strip())
    if brand_map.get("positive_extra"):
        positive_parts.append(brand_map["positive_extra"])
    if brand_map.get("negative_extra"):
        negative_parts.append(brand_map["negative_extra"])

    # character mapping
    char_id = (shot.get("character_id") or "").strip()
    char_map = m.get("character", {}).get(char_id, {})
    if char_map.get("positive_extra"):
        positive_parts.append(char_map["positive_extra"])
    if char_map.get("negative_extra"):
        negative_parts.append(char_map["negative_extra"])

    positive_prompt = ", ".join(p for p in positive_parts if p)
    negative_prompt = ", ".join(n for n in negative_parts if n)

    result = {
        "shot_id": shot.get("shot_id", ""),
        "positive_prompt": positive_prompt,
        "negative_prompt": negative_prompt,
        "style_prompt": style_prompt,
        "seed": int(defaults.get("seed", -1)),
        "cfg": float(defaults.get("cfg", 7.0)),
        "steps": int(defaults.get("steps", 20)),
        "builder_version": "1.0",
    }
    # stable hash for dedup / evidence
    h = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    result["prompt_hash"] = h
    return result


def build_prompts(shots: List[Dict[str, Any]], mappings: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """批量处理 shots 列表。"""
    m = mappings or _load_mappings()
    return [build_prompt(shot, m) for shot in shots]
