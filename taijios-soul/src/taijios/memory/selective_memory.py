"""
SelectiveMemory — 选择性记忆

AI自己决定记什么、忘什么。
三个判断维度：重要性、独特性、情感权重
三层记忆策略：即时层→温存层(30天)→永久层
"""

import time
import json
import os
import re
import hashlib
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict
import logging

logger = logging.getLogger("selective_memory")


@dataclass
class MemoryEntry:
    """一条记忆"""
    memory_id: str
    content: str
    source_message: str
    category: str  # fact / preference / relationship / skill / emotion / event
    importance: float
    uniqueness: float
    emotional_weight: float
    recall_count: int = 0
    created_at: float = field(default_factory=time.time)
    last_recalled: float = 0
    ttl_days: int = 30
    permanent: bool = False

    @property
    def score(self) -> float:
        recall_bonus = min(self.recall_count * 0.05, 0.3)
        return (self.importance * 0.4 +
                self.uniqueness * 0.3 +
                self.emotional_weight * 0.2 +
                recall_bonus * 0.1)

    @property
    def is_expired(self) -> bool:
        if self.permanent:
            return False
        return (time.time() - self.created_at) / 86400 > self.ttl_days

    @property
    def should_promote(self) -> bool:
        return not self.permanent and self.recall_count >= 3

    def recall(self):
        self.recall_count += 1
        self.last_recalled = time.time()

    def to_dict(self) -> dict:
        return {
            "id": self.memory_id, "content": self.content,
            "category": self.category, "importance": round(self.importance, 2),
            "score": round(self.score, 2), "recall_count": self.recall_count,
            "permanent": self.permanent,
            "age_days": round((time.time() - self.created_at) / 86400, 1),
        }


class MemoryJudge:
    SKIP_PATTERNS = [
        r'^(嗯|好|ok|okay|是|对|行|哦|啊|哈|呵|嘿|hi|hello|hey)$',
        r'^(谢谢|thanks|thx|thank you)$',
        r'^(再见|bye|晚安|早安|拜拜)$',
        r'^[\.。，,!！?？]+$',
        r'^\d+$',
    ]
    CATEGORY_SIGNALS = {
        "fact": {
            "keywords": ["是", "有", "叫", "在", "用的是", "版本", "数据", "胜率",
                         "进球", "排名", "积分", "API", "数据库", "服务器"],
            "patterns": [r'\d+%', r'\d+\.\d+', r'v\d+'],
            "base_importance": 0.6,
        },
        "preference": {
            "keywords": ["喜欢", "不喜欢", "偏好", "习惯", "风格", "不要",
                         "别给", "简短", "详细", "正经", "话少"],
            "patterns": [r'以后.*(不要|别|用)', r'我(喜欢|讨厌|偏好)'],
            "base_importance": 0.8,
        },
        "relationship": {
            "keywords": ["老张", "老李", "同事", "老板", "团队", "客户",
                         "朋友", "他说", "她说"],
            "patterns": [r'(他|她|老\w|小\w)(说|觉得|认为|要求)'],
            "base_importance": 0.5,
        },
        "skill": {
            "keywords": ["学会了", "发现了", "原来", "规律", "方法", "技巧",
                         "原理", "因果", "根因"],
            "patterns": [r'原来.*(是|因为)', r'(规律|方法|原理)是'],
            "base_importance": 0.7,
        },
        "emotion": {
            "keywords": ["烦", "崩溃", "开心", "爽", "焦虑", "压力",
                         "累", "难受", "受不了", "兴奋"],
            "patterns": [r'(好|太|真)(烦|累|难|爽|开心)'],
            "base_importance": 0.4,
        },
        "event": {
            "keywords": ["上线了", "发布了", "完成了", "出bug了", "挂了",
                         "通过了", "失败了", "deadline"],
            "patterns": [r'(已经|刚刚|终于).*(完成|上线|发布|修好)'],
            "base_importance": 0.7,
        },
    }
    FORCE_REMEMBER = ["记住", "别忘了", "以后都", "永远", "从现在起", "重要", "关键", "核心", "必须"]
    FORCE_FORGET = ["忘掉", "别记", "不用记", "随便说说"]
    MIN_LENGTH = 5
    REMEMBER_THRESHOLD = 0.3

    def judge(self, message: str, reply: str = "",
              soul_context: dict = None) -> Optional[MemoryEntry]:
        msg = message.strip()
        if len(msg) < self.MIN_LENGTH:
            return None
        msg_lower = msg.lower()
        for pattern in self.SKIP_PATTERNS:
            if re.match(pattern, msg_lower):
                return None
        if any(kw in msg for kw in self.FORCE_FORGET):
            return None
        force = any(kw in msg for kw in self.FORCE_REMEMBER)
        category, base_importance = self._classify(msg)
        importance = self._score_importance(msg, base_importance, force)
        uniqueness = self._score_uniqueness(msg)
        emotional = self._score_emotional(msg, soul_context)
        # reply 中包含用户相关信息时加分（说明这轮对话有实质内容）
        reply_bonus = 0.0
        if reply:
            if any(kw in reply for kw in ["你之前", "你说过", "你提到", "上次", "记得你"]):
                reply_bonus = 0.15
            elif len(reply) > 100:
                reply_bonus = 0.05
        total = importance * 0.4 + uniqueness * 0.3 + emotional * 0.2 + reply_bonus
        if not force and total < self.REMEMBER_THRESHOLD:
            return None
        content = msg[:50] + ("..." if len(msg) > 50 else "")
        if len(msg) > 50:
            content = f"[{category}] {content}"
        memory_id = f"mem_{hashlib.md5(msg.encode()).hexdigest()[:8]}"
        return MemoryEntry(
            memory_id=memory_id, content=content,
            source_message=msg[:200], category=category,
            importance=importance, uniqueness=uniqueness,
            emotional_weight=emotional, permanent=force,
        )

    def _classify(self, msg: str) -> tuple[str, float]:
        best_category, best_score, best_importance = "fact", 0, 0.5
        for category, signals in self.CATEGORY_SIGNALS.items():
            score = sum(1 for kw in signals["keywords"] if kw in msg)
            score += sum(2 for p in signals["patterns"] if re.search(p, msg))
            if score > best_score:
                best_score, best_category = score, category
                best_importance = signals["base_importance"]
        return best_category, best_importance

    def _score_importance(self, msg: str, base: float, force: bool) -> float:
        if force:
            return 1.0
        score = base
        if len(msg) > 50: score += 0.1
        if len(msg) > 200: score += 0.1
        if re.search(r'\d+', msg): score += 0.1
        if any(w in msg for w in ["因为", "所以", "导致", "因此"]): score += 0.15
        return min(1.0, score)

    def _score_uniqueness(self, msg: str) -> float:
        density = len(set(msg)) / max(len(msg), 1)
        length_score = min(len(msg) / 100, 1.0)
        return density * 0.5 + length_score * 0.5

    def _score_emotional(self, msg: str, soul_context: dict = None) -> float:
        score = 0.0
        if any(w in msg for w in ["烦", "崩溃", "受不了", "太难了", "焦虑", "兴奋", "感动"]):
            score = 0.8
        elif any(w in msg for w in ["累", "难", "开心", "不错"]):
            score = 0.4
        if soul_context and soul_context.get("frustration", 0) > 0.5:
            score = max(score, 0.6)
        return score


class SelectiveMemory:
    MAX_MEMORIES = 200

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir or "soul_data/default"
        self.memory_file = os.path.join(self.data_dir, "selective_memory.json")
        self.judge = MemoryJudge()
        self.memories: dict[str, MemoryEntry] = {}
        self._load()

    def judge_and_store(self, message: str, reply: str = "",
                         soul_context: dict = None) -> Optional[MemoryEntry]:
        entry = self.judge.judge(message, reply, soul_context)
        if entry is None:
            return None
        for existing in self.memories.values():
            if self._is_duplicate(entry.content, existing.content):
                existing.recall()
                return None
        if len(self.memories) >= self.MAX_MEMORIES:
            self._evict_least_valuable()
        self.memories[entry.memory_id] = entry
        self._save()
        logger.info("[MEMORY] stored: [%s] %s (score=%.2f)",
                    entry.category, entry.content[:40], entry.score)
        return entry

    def recall(self, query: str, top_k: int = 5) -> list[MemoryEntry]:
        if not self.memories:
            return []
        query_chars = set(query)
        scored = []
        for entry in self.memories.values():
            if entry.is_expired:
                continue
            content_chars = set(entry.content)
            overlap = len(query_chars & content_chars) / max(len(query_chars | content_chars), 1)
            category_boost = {"preference": 0.3, "skill": 0.2, "relationship": 0.1,
                              "fact": 0.1, "event": 0.05, "emotion": 0.0}.get(entry.category, 0)
            recency = max(0, 1 - (time.time() - entry.created_at) / (720 * 3600))
            relevance = overlap * 0.5 + category_boost + recency * 0.2
            scored.append((relevance, entry))
        scored.sort(key=lambda x: -x[0])
        results = [e for _, e in scored[:top_k]]
        for e in results:
            e.recall()
        return results

    def get_context_block(self, query: str = "", top_k: int = 5) -> str:
        permanent = [e for e in self.memories.values() if e.permanent and not e.is_expired]
        relevant = self.recall(query, top_k=top_k) if query else []
        all_mem = {e.memory_id: e for e in permanent + relevant}
        if not all_mem:
            return ""
        lines = ["【记忆】以下是你记住的重要信息："]
        for entry in all_mem.values():
            prefix = "★" if entry.permanent else "-"
            lines.append(f"{prefix} {entry.content}")
        return "\n".join(lines)

    def maintain(self):
        expired, promoted = [], []
        for mid, entry in self.memories.items():
            if entry.is_expired:
                expired.append(mid)
            elif entry.should_promote:
                entry.permanent = True
                entry.ttl_days = 0
                promoted.append(entry.content[:30])
        for mid in expired:
            del self.memories[mid]
        if expired or promoted:
            self._save()
            if expired: logger.info("[MEMORY] forgot %d expired", len(expired))
            if promoted: logger.info("[MEMORY] promoted %d to permanent", len(promoted))

    def _is_duplicate(self, a: str, b: str) -> bool:
        sa, sb = set(a), set(b)
        if not sa or not sb: return False
        return len(sa & sb) / len(sa | sb) > 0.7

    def _evict_least_valuable(self):
        candidates = {m: e for m, e in self.memories.items() if not e.permanent}
        if candidates:
            worst = min(candidates, key=lambda m: candidates[m].score)
            del self.memories[worst]

    def _save(self):
        os.makedirs(os.path.dirname(self.memory_file) or ".", exist_ok=True)
        try:
            data = {mid: {
                "memory_id": e.memory_id, "content": e.content,
                "source_message": e.source_message, "category": e.category,
                "importance": e.importance, "uniqueness": e.uniqueness,
                "emotional_weight": e.emotional_weight, "recall_count": e.recall_count,
                "created_at": e.created_at, "last_recalled": e.last_recalled,
                "ttl_days": e.ttl_days, "permanent": e.permanent,
            } for mid, e in self.memories.items()}
            with open(self.memory_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Memory save failed: %s", e)

    def _load(self):
        if not os.path.exists(self.memory_file):
            return
        try:
            with open(self.memory_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for mid, d in data.items():
                self.memories[mid] = MemoryEntry(
                    memory_id=d["memory_id"], content=d["content"],
                    source_message=d.get("source_message", ""), category=d["category"],
                    importance=d["importance"], uniqueness=d.get("uniqueness", 0.5),
                    emotional_weight=d.get("emotional_weight", 0),
                    recall_count=d.get("recall_count", 0),
                    created_at=d.get("created_at", time.time()),
                    last_recalled=d.get("last_recalled", 0),
                    ttl_days=d.get("ttl_days", 30), permanent=d.get("permanent", False),
                )
        except Exception as e:
            logger.warning("Memory load failed: %s", e)

    def to_dict(self) -> dict:
        permanent = sum(1 for e in self.memories.values() if e.permanent)
        by_cat = defaultdict(int)
        for e in self.memories.values():
            by_cat[e.category] += 1
        return {"total": len(self.memories), "permanent": permanent,
                "by_category": dict(by_cat)}
