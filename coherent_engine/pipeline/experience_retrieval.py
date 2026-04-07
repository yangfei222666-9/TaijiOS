"""
ExperienceRetrievalSkill — coherent_engine
根据 job_request + reason_code 从 EchoCore 本地索引检索可注入经验片段。

检索优先级（三层 key）：
  1. brand_rules_id + character_id + reason_code  （最精确）
  2. brand_rules_id + reason_code
  3. reason_code only（兜底）

返回格式：
  {
    "matched_key": str,
    "confidence": float,
    "inject_to": "planner_system" | "positive_prompt" | "negative_prompt",
    "content": str,
    "source_experience_id": str,
    "source_reason_code": str,
  }
  或 None（无匹配时）

设计原则：
- 无匹配时返回 None，不阻断流程
- 命中时注入 planner system prompt，run_trace 记录 experience_id
- 本地索引优先（JSON），EchoCore engine 作为扩展
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

_INDEX_PATH = Path(__file__).parent / "experience_index.json"

# 内置种子经验（bootstrap，EchoCore 尚无真实数据时使用）
_SEED_INDEX: List[Dict[str, Any]] = [
    {
        "key": "*+*+coherent.validator.character_consistency",
        "inject_to": "planner_system",
        "content": "历史经验：角色一致性失败时，强制锁定主色调，镜头间禁止色调漂移超过10%。must_keep 加入主色调约束。",
        "confidence": 0.7,
        "source_experience_id": "seed_001",
        "source_reason_code": "coherent.validator.character_consistency",
    },
    {
        "key": "*+*+coherent.validator.style_consistency",
        "inject_to": "planner_system",
        "content": "历史经验：风格一致性失败时，固定 style token，降低生成随机性，相邻镜头亮度差控制在15%以内。",
        "confidence": 0.7,
        "source_experience_id": "seed_002",
        "source_reason_code": "coherent.validator.style_consistency",
    },
    {
        "key": "*+*+coherent.validator.shot_continuity",
        "inject_to": "planner_system",
        "content": "历史经验：镜头连贯性失败时，增加衔接镜头，避免跳切，相邻镜头主体位置漂移控制在20%以内。",
        "confidence": 0.7,
        "source_experience_id": "seed_003",
        "source_reason_code": "coherent.validator.shot_continuity",
    },
    {
        "key": "*+*+coherent.validator.subtitle_safety",
        "inject_to": "negative_prompt",
        "content": "字幕安全区被占用，在 negative_prompt 加入：foreground object in subtitle zone, text overlap.",
        "confidence": 0.75,
        "source_experience_id": "seed_004",
        "source_reason_code": "coherent.validator.subtitle_safety",
    },
]


def _load_index() -> List[Dict[str, Any]]:
    """加载本地经验索引，不存在时返回种子数据。"""
    if _INDEX_PATH.exists():
        try:
            data = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return _SEED_INDEX


def _make_keys(
    brand_rules_id: str,
    character_id: str,
    reason_code: str,
) -> List[str]:
    """生成三层检索 key，优先级从高到低。"""
    b = brand_rules_id or "*"
    c = character_id or "*"
    r = reason_code or "*"
    return [
        f"{b}+{c}+{r}",      # 最精确
        f"{b}+*+{r}",         # brand + reason
        f"*+*+{r}",           # reason only
    ]


def retrieve(
    brand_rules_id: str = "",
    character_id: str = "",
    reason_code: str = "",
    index: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """
    检索最匹配的经验片段。
    Quality control: skip expired/quarantined entries, prefer higher confidence.
    无匹配返回 None，不抛异常。
    """
    import time as _time
    idx = index if index is not None else _load_index()
    keys = _make_keys(brand_rules_id, character_id, reason_code)

    # 按优先级依次匹配
    for priority, key in enumerate(keys):
        candidates = []
        for entry in idx:
            if (entry.get("key") or entry.get("matched_key")) == key:
                # Quality gate: skip quarantined
                if entry.get("quarantined", False):
                    continue
                # Quality gate: skip expired (TTL)
                ttl_days = entry.get("ttl_days", 0)
                if ttl_days > 0:
                    created = entry.get("created_at", 0)
                    if created and (_time.time() - created) > ttl_days * 86400:
                        continue
                candidates.append(entry)

        if not candidates:
            continue

        # Pick highest confidence candidate
        best = max(candidates, key=lambda e: float(e.get("confidence", 0.5)))
        return {
            "matched_key": key,
            "priority": priority,
            "confidence": float(best.get("confidence", 0.5)),
            "inject_to": best.get("inject_to", "planner_system"),
            "content": best.get("content", ""),
            "source_experience_id": best.get("source_experience_id", ""),
            "source_reason_code": best.get("source_reason_code", ""),
        }
    return None




def retrieve_experience(*, brand_rules_id: str, character_id: str, reason_code: str):
    return retrieve(brand_rules_id=brand_rules_id, character_id=character_id, reason_code=reason_code)
def retrieve_all(
    brand_rules_id: str = "",
    character_id: str = "",
    reason_codes: Optional[List[str]] = None,
    index: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """
    对多个 reason_code 批量检索，返回所有命中结果（去重）。
    用于将多个失败 check 的经验一起注入。
    """
    idx = index if index is not None else _load_index()
    results = []
    seen_ids = set()
    for rc in (reason_codes or []):
        hit = retrieve(brand_rules_id, character_id, rc, idx)
        if hit and hit["source_experience_id"] not in seen_ids:
            results.append(hit)
            seen_ids.add(hit["source_experience_id"])
    return results


def inject_to_system_prompt(
    base_prompt: str,
    experiences: List[Dict[str, Any]],
) -> str:
    """
    将 inject_to=planner_system 的经验片段追加到 system prompt。
    """
    extras = [
        e["content"] for e in experiences
        if e.get("inject_to") == "planner_system" and e.get("content")
    ]
    if not extras:
        return base_prompt
    return base_prompt + "\n\n[经验库注入]\n" + "\n".join(f"- {x}" for x in extras)


def save_to_index(entry: Dict[str, Any]) -> None:
    """
    将新经验写入本地索引（追加）。
    用于 EchoCore 经验提炼后的固化。
    """
    import time as _time
    idx = _load_index()
    # Ensure quality fields
    if "stats" not in entry:
        entry["stats"] = {"success": 0, "fail": 0, "hit_count": 0, "last_seen": ""}
    if "created_at" not in entry:
        entry["created_at"] = _time.time()
    if "ttl_days" not in entry:
        entry["ttl_days"] = 0  # 0 = no expiry
    if "quarantined" not in entry:
        entry["quarantined"] = False
    # 去重：相同 key 覆盖
    key = entry.get("key") or entry.get("matched_key")
    existing_keys = {e.get("key") or e.get("matched_key") for e in idx}
    if key in existing_keys:
        idx = [e if (e.get("key") or e.get("matched_key")) != key else entry for e in idx]
    else:
        idx.append(entry)
    _INDEX_PATH.write_text(
        json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Quality Control ────────────────────────────────────────────

def record_outcome(experience_id: str, passed: bool) -> None:
    """
    Record whether a job that used this experience passed or failed.
    Updates stats.success/fail, hit_count, confidence, and auto-quarantines.
    """
    import time as _time
    idx = _load_index()
    for entry in idx:
        if entry.get("source_experience_id") == experience_id:
            stats = entry.setdefault("stats", {"success": 0, "fail": 0, "hit_count": 0, "last_seen": ""})
            stats["hit_count"] = stats.get("hit_count", 0) + 1
            if passed:
                stats["success"] = stats.get("success", 0) + 1
            else:
                stats["fail"] = stats.get("fail", 0) + 1
            stats["last_seen"] = _time.strftime("%Y-%m-%dT%H:%M:%S+00:00", _time.gmtime())

            # Recalculate confidence from success rate
            total = stats["success"] + stats["fail"]
            if total >= 3:
                success_rate = stats["success"] / total
                # Blend: 70% empirical + 30% prior confidence
                prior = float(entry.get("confidence", 0.5))
                entry["confidence"] = round(0.7 * success_rate + 0.3 * prior, 4)

                # Auto-quarantine: success rate < 30% after 5+ uses
                if total >= 5 and success_rate < 0.30:
                    entry["quarantined"] = True

            break

    _INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")


def quarantine_experience(experience_id: str, reason: str = "") -> bool:
    """Manually quarantine an experience. It won't be retrieved until unquarantined."""
    idx = _load_index()
    for entry in idx:
        if entry.get("source_experience_id") == experience_id:
            entry["quarantined"] = True
            entry["quarantine_reason"] = reason
            _INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
    return False


def unquarantine_experience(experience_id: str) -> bool:
    """Restore a quarantined experience."""
    idx = _load_index()
    for entry in idx:
        if entry.get("source_experience_id") == experience_id:
            entry["quarantined"] = False
            entry.pop("quarantine_reason", None)
            _INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
            return True
    return False


def decay_stale_experiences(max_idle_days: int = 30) -> int:
    """
    Reduce confidence of experiences not seen in max_idle_days.
    Returns count of decayed entries.
    """
    import time as _time
    idx = _load_index()
    now = _time.time()
    decayed = 0
    for entry in idx:
        stats = entry.get("stats", {})
        last_seen = stats.get("last_seen", "")
        if not last_seen:
            continue
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(last_seen.replace("+00:00", "+00:00"))
            age_days = (now - dt.timestamp()) / 86400
        except (ValueError, TypeError):
            continue
        if age_days > max_idle_days:
            old_conf = float(entry.get("confidence", 0.5))
            entry["confidence"] = round(max(0.1, old_conf * 0.8), 4)  # 20% decay
            decayed += 1
    if decayed:
        _INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
    return decayed


def get_quality_report() -> Dict[str, Any]:
    """Generate a quality report of all experiences."""
    idx = _load_index()
    total = len(idx)
    quarantined = sum(1 for e in idx if e.get("quarantined"))
    github = sum(1 for e in idx if "github_learning" in (e.get("key") or e.get("matched_key") or ""))
    with_stats = sum(1 for e in idx if e.get("stats", {}).get("hit_count", 0) > 0)
    high_conf = sum(1 for e in idx if float(e.get("confidence", 0)) >= 0.8)
    low_conf = sum(1 for e in idx if float(e.get("confidence", 0)) < 0.4)

    return {
        "total": total,
        "quarantined": quarantined,
        "active": total - quarantined,
        "github_learning": github,
        "with_usage_stats": with_stats,
        "high_confidence": high_conf,
        "low_confidence": low_conf,
    }
