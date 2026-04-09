#!/usr/bin/env python3
"""
颐卦自学引擎 (Yi Self-Learning Engine) — 吸收→消化→沉淀→反哺

核心职责：
- 采集：订阅震卦教训、师卦赏罚、情势干预三条经验线
- 消化：归纳同类经验为"元经验"，提升权重
- 沉淀：持久化经验库（JSONL），带权重衰减
- 反哺：被动查询 + 主动推送（weight > 0.7 时 emit yi.advisory）

经验记录格式：结构化（context→decision→outcome→lesson）
查询策略：快路径精确匹配，慢路径 LLM 语义搜索

Author: TaijiOS
Date: 2026-04-09
"""

import json
import sys
import time
import uuid
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any

from event_bus import emit, subscribe, get_event_bus

log = logging.getLogger("aios.yi_engine")


# ============================================================
# 数据结构
# ============================================================

@dataclass
class ExperienceRecord:
    """结构化经验记录"""
    exp_id: str
    source: str                     # "zhen" | "shi" | "situation"
    context: Dict[str, Any]         # 情境
    decision: Dict[str, Any]        # 决策
    outcome: Dict[str, Any]         # 结果
    lesson: str                     # 教训文本
    weight: float = 0.5
    decay: float = 0.95
    tags: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    last_hit: float = 0.0
    hit_count: int = 0
    merged_into: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict) -> "ExperienceRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ============================================================
# 颐卦自学引擎
# ============================================================

class YiLearningEngine:
    """颐卦：吸收→消化→沉淀→反哺"""

    def __init__(self, data_dir: str = None):
        self.data_dir = Path(data_dir) if data_dir else (
            Path(__file__).parent / "data" / "yi"
        )
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_file = self.data_dir / "experience_db.jsonl"

        self.experiences: Dict[str, ExperienceRecord] = {}
        self._load()

        self.stats = {
            "collected": 0, "queries": 0, "hits": 0,
            "advisories": 0, "digests": 0,
        }
        self.last_digest_time: float = 0

        subscribe("recovery.lesson_learned", self._on_lesson_learned)
        subscribe("shi.mandate", self._on_mandate)
        subscribe("situation.intervention", self._on_intervention)

    # ============================================================
    # 采集层
    # ============================================================

    def _on_lesson_learned(self, event: Dict):
        """震卦教训 → 经验记录"""
        data = event.get("data", {})
        record = ExperienceRecord(
            exp_id=str(uuid.uuid4())[:8],
            source="zhen",
            context={
                "agent": data.get("agent", "unknown"),
                "error_type": data.get("fault_id", "").split("_")[0] if data.get("fault_id") else "unknown",
                "severity": data.get("severity", "medium"),
            },
            decision={"strategy": "recovery", "yao_path": data.get("yao_path", [])},
            outcome={"success": data.get("success", False)},
            lesson=data.get("lesson", ""),
            weight=0.6 if data.get("success") else 0.4,
            tags=["#震卦", f"#agent/{data.get('agent', 'unknown')}"],
        )
        self._ingest(record)

    def _on_mandate(self, event: Dict):
        """师卦赏罚 → 经验记录（每个 agent 一条）"""
        data = event.get("data", {})
        for reward in data.get("rewards", []):
            agent_id = reward.get("agent_id", "unknown")
            score = reward.get("score", 0.5)
            old_rel = reward.get("old_reliability", 0.8)
            new_rel = reward.get("new_reliability", 0.8)
            change = new_rel - old_rel
            record = ExperienceRecord(
                exp_id=str(uuid.uuid4())[:8],
                source="shi",
                context={"agent": agent_id, "mission_id": data.get("mission_id", "unknown")},
                decision={"role": "mission_participant"},
                outcome={"score": score, "reliability_change": round(change, 3), "new_reliability": new_rel},
                lesson=f"{agent_id} 得分{score:.2f} 可靠度{'+' if change >= 0 else ''}{change:.2f}",
                weight=0.5 + (score - 0.5) * 0.4,
                tags=["#师卦", f"#agent/{agent_id}"],
            )
            self._ingest(record)

    def _on_intervention(self, event: Dict):
        """情势干预 → 经验记录"""
        data = event.get("data", {})
        tension = data.get("tension", {})
        record = ExperienceRecord(
            exp_id=str(uuid.uuid4())[:8],
            source="situation",
            context={"dim_a": tension.get("dim_a", ""), "dim_b": tension.get("dim_b", ""),
                      "severity": tension.get("severity", 0)},
            decision={"intervention_dim": data.get("target_dimension", ""), "action": data.get("action", "")},
            outcome={"executed": True, "risk": data.get("risk", "medium")},
            lesson=data.get("llm_advice") or tension.get("description", ""),
            weight=0.5,
            tags=["#情势", f"#tension/{tension.get('dim_a', '')}_{tension.get('dim_b', '')}"],
        )
        self._ingest(record)

    def _ingest(self, record: ExperienceRecord):
        """采集入库 + 主动推送检查"""
        self.experiences[record.exp_id] = record
        self._persist_one(record)
        self.stats["collected"] += 1
        emit("yi.experience_added", {
            "exp_id": record.exp_id, "source": record.source,
            "lesson": record.lesson[:100],
        })
        self._check_advisory(record)

    def _check_advisory(self, new_record: ExperienceRecord):
        """库中已有同类高权重经验时，主动推送 yi.advisory"""
        for exp in self.experiences.values():
            if exp.exp_id == new_record.exp_id or exp.merged_into:
                continue
            if exp.weight < 0.7 or exp.source != new_record.source:
                continue
            if self._context_matches(exp.context, new_record.context):
                self.stats["advisories"] += 1
                emit("yi.advisory", {
                    "trigger_exp_id": new_record.exp_id,
                    "related_exp_id": exp.exp_id,
                    "source": exp.source, "lesson": exp.lesson,
                    "weight": exp.weight,
                    "advice": f"历史经验(权重{exp.weight:.2f}): {exp.lesson}",
                })
                return

    @staticmethod
    def _context_matches(ctx_a: Dict, ctx_b: Dict) -> bool:
        if "error_type" in ctx_a and "error_type" in ctx_b:
            return ctx_a["error_type"] == ctx_b["error_type"]
        if "agent" in ctx_a and "agent" in ctx_b:
            return ctx_a["agent"] == ctx_b["agent"]
        if "dim_a" in ctx_a and "dim_a" in ctx_b:
            return ctx_a["dim_a"] == ctx_b["dim_a"] and ctx_a["dim_b"] == ctx_b["dim_b"]
        return False



    # ============================================================
    # 消化层 — 归纳同类经验为元经验
    # ============================================================

    def digest(self) -> Dict:
        """同类经验 >=3 条时合并为元经验"""
        groups = self._group_experiences()
        merged_count = 0
        meta_records = []

        for key, group in groups.items():
            active = [e for e in group if not e.merged_into]
            if len(active) < 3:
                continue
            meta_lesson = self._llm_digest(active)
            avg_weight = sum(e.weight for e in active) / len(active)
            meta = ExperienceRecord(
                exp_id=f"meta_{str(uuid.uuid4())[:6]}",
                source=active[0].source,
                context=active[0].context.copy(),
                decision={"type": "meta_digest", "merged_count": len(active)},
                outcome={"avg_weight": round(avg_weight, 3),
                         "total_hits": sum(e.hit_count for e in active)},
                lesson=meta_lesson,
                weight=min(1.0, avg_weight + 0.15),
                tags=active[0].tags + ["#meta"],
            )
            for e in active:
                e.merged_into = meta.exp_id
            self.experiences[meta.exp_id] = meta
            meta_records.append(meta)
            merged_count += len(active)

        self.last_digest_time = time.time()
        self.stats["digests"] += 1
        self._persist_all()

        emit("yi.digest_completed", {
            "groups_merged": len(meta_records),
            "records_merged": merged_count,
            "total_experiences": len(self.experiences),
        })
        return {
            "groups_merged": len(meta_records),
            "records_merged": merged_count,
            "meta_lessons": [m.lesson for m in meta_records],
            "total_experiences": len(self.experiences),
        }

    def _group_experiences(self) -> Dict[str, List[ExperienceRecord]]:
        groups: Dict[str, List[ExperienceRecord]] = {}
        for exp in self.experiences.values():
            if exp.merged_into:
                continue
            key = self._make_group_key(exp)
            if key not in groups:
                groups[key] = []
            groups[key].append(exp)
        return groups

    @staticmethod
    def _make_group_key(exp: ExperienceRecord) -> str:
        ctx = exp.context
        if exp.source == "zhen":
            return f"zhen:{ctx.get('error_type', '?')}"
        elif exp.source == "shi":
            return f"shi:{ctx.get('agent', '?')}"
        elif exp.source == "situation":
            return f"situation:{ctx.get('dim_a', '?')}_{ctx.get('dim_b', '?')}"
        return f"{exp.source}:unknown"

    def _llm_digest(self, records: List[ExperienceRecord]) -> str:
        """用 LLM 归纳同类经验"""
        try:
            from llm_caller import call_llm, is_llm_available
            if is_llm_available():
                lessons_text = "\n".join(
                    f"- [{r.source}] (权重{r.weight:.2f}) {r.lesson}"
                    for r in records[:10]
                )
                result = call_llm(
                    "你是 TaijiOS 颐卦自学引擎的经验归纳师。\n"
                    "将以下同类经验归纳为一条精炼的元经验（50字以内）。\n"
                    "提取共性规律，去除个例细节。只输出归纳结果。",
                    f"同类经验（{len(records)}条）:\n{lessons_text}",
                    model="claude-haiku-4-5", max_tokens=150,
                )
                if not result.startswith("[LLM_ERROR]"):
                    return result.strip()
        except Exception:
            pass
        best = max(records, key=lambda r: r.weight)
        return f"[归纳] {best.lesson}"



    # ============================================================
    # 反哺层 — 被动查询
    # ============================================================

    def query(self, context: Dict) -> List[ExperienceRecord]:
        """
        查询经验库：快路径精确匹配，慢路径 LLM 语义搜索
        """
        self.stats["queries"] += 1
        results = self._query_fast(context)
        if not results:
            results = self._query_llm(context)
        # 更新命中统计
        for r in results:
            r.last_hit = time.time()
            r.hit_count += 1
            r.weight = min(1.0, r.weight + 0.05)
        if results:
            self.stats["hits"] += 1
        return results

    def _query_fast(self, context: Dict) -> List[ExperienceRecord]:
        """快路径：精确匹配 context 字段"""
        matches = []
        for exp in self.experiences.values():
            if exp.merged_into:
                continue
            if self._context_matches(exp.context, context):
                matches.append(exp)
        matches.sort(key=lambda e: e.weight, reverse=True)
        return matches[:5]

    def _query_llm(self, context: Dict) -> List[ExperienceRecord]:
        """慢路径：LLM 语义匹配"""
        try:
            from llm_caller import call_llm_json, is_llm_available
            if not is_llm_available():
                return []
            active = [e for e in self.experiences.values() if not e.merged_into]
            if not active:
                return []
            candidates = sorted(active, key=lambda e: e.weight, reverse=True)[:20]
            lessons_indexed = {str(i): c for i, c in enumerate(candidates)}
            lessons_text = "\n".join(
                f"[{i}] {c.lesson}" for i, c in lessons_indexed.items()
            )
            ctx_text = json.dumps(context, ensure_ascii=False)
            result = call_llm_json(
                "你是经验匹配器。给定查询情境和经验列表，返回最相关的经验编号。\n"
                '返回 JSON: {"matches": [0, 3, 5]}（最多3个编号）',
                f"查询情境: {ctx_text}\n\n经验列表:\n{lessons_text}",
                model="claude-haiku-4-5", max_tokens=100,
            )
            indices = result.get("matches", [])
            return [lessons_indexed[str(i)] for i in indices if str(i) in lessons_indexed]
        except Exception:
            return []

    # ============================================================
    # 沉淀层 — 持久化
    # ============================================================

    def _persist_one(self, record: ExperienceRecord):
        """追加写一条记录"""
        with open(self.db_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")

    def _persist_all(self):
        """全量重写（消化后更新 merged_into 标记）"""
        with open(self.db_file, "w", encoding="utf-8") as f:
            for exp in self.experiences.values():
                f.write(json.dumps(exp.to_dict(), ensure_ascii=False) + "\n")

    def _load(self):
        """启动时从 JSONL 加载"""
        if not self.db_file.exists():
            return
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    record = ExperienceRecord.from_dict(d)
                    self.experiences[record.exp_id] = record
        except Exception as e:
            log.warning(f"[Yi] 加载经验库失败: {e}")

    def decay_all(self):
        """全局衰减：weight *= decay，weight < 0.1 的归档"""
        archived = []
        for exp in list(self.experiences.values()):
            exp.weight *= exp.decay
            if exp.weight < 0.1:
                archived.append(exp.exp_id)
        for eid in archived:
            del self.experiences[eid]
        if archived:
            self._persist_all()
        return {"decayed": len(self.experiences), "archived": len(archived)}

    # ============================================================
    # 状态查询
    # ============================================================

    def get_status(self) -> Dict:
        active = [e for e in self.experiences.values() if not e.merged_into]
        by_source = {}
        for e in active:
            by_source[e.source] = by_source.get(e.source, 0) + 1
        high_weight = [e for e in active if e.weight >= 0.7]
        return {
            "total": len(self.experiences),
            "active": len(active),
            "by_source": by_source,
            "high_weight_count": len(high_weight),
            "stats": self.stats,
            "last_digest": self.last_digest_time,
        }


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=== 颐卦自学引擎测试 ===\n")

    engine = YiLearningEngine()

    # 模拟震卦教训事件
    emit("recovery.lesson_learned", {
        "fault_id": "timeout_001", "agent": "coder",
        "lesson": "API超时用指数退避", "success": True, "yao_path": ["ALERT", "ASSESS", "REACT", "LEARN"],
    })
    emit("recovery.lesson_learned", {
        "fault_id": "timeout_002", "agent": "monitor",
        "lesson": "连接重置需检查网络层", "success": True, "yao_path": ["ALERT", "ASSESS", "REACT", "LEARN"],
    })

    # 模拟师卦赏罚事件
    emit("shi.mandate", {
        "mission_id": "m001",
        "rewards": [
            {"agent_id": "coder", "score": 0.85, "old_reliability": 0.9, "new_reliability": 0.95},
            {"agent_id": "analyst", "score": 0.6, "old_reliability": 0.85, "new_reliability": 0.85},
        ],
    })

    # 模拟情势干预事件
    emit("situation.intervention", {
        "target_dimension": "relationship",
        "action": "scheduler.rebalance",
        "risk": "medium",
        "llm_advice": "启动跨部门协作分担负载",
        "tension": {"dim_a": "resource", "dim_b": "initiative", "severity": 0.58},
    })

    print(f"采集完成: {engine.stats['collected']} 条经验")
    print(f"经验库状态: {json.dumps(engine.get_status(), ensure_ascii=False, indent=2)}")

    # 查询测试
    print("\n--- 查询测试 ---")
    results = engine.query({"agent": "coder"})
    print(f"查询 agent=coder: {len(results)} 条命中")
    for r in results:
        print(f"  [{r.source}] w={r.weight:.2f} {r.lesson}")

    print("\n=== 颐卦自学引擎测试完成 ===")
