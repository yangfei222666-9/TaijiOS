"""
TaijiOS 五维灵魂体系 v2 — 有缺陷的灵魂
新增: 吵架机制 · 选择性遗忘 · 江湖传闻 · 脾气突变 · 默契尴尬 · 五维共振彩蛋

完美的AI无聊，有性格缺陷的AI才让人想继续聊。
"""

import json
import hashlib
import time
import random
import math
import os
from datetime import datetime
from typing import Optional
from dataclasses import dataclass, field, asdict

# Shadow + Safety 可选集成（包内或独立均可）
ShadowAccumulator = None
SafetySoulGuard = None
try:
    from taijios.engine.safety_soul_guard import SafetySoulGuard
except ImportError:
    try:
        from safety_soul_guard import SafetySoulGuard
    except ImportError:
        pass

# EventBus 可选集成 — SDK 模式不需要，降级为 no-op
_HAS_EVENT_BUS = False


# ============================================================
# 1. 缘分引擎 — Fate Engine
# ============================================================

class FateEngine:
    STAGES = ["stranger", "familiar", "acquainted", "bonded"]
    STAGE_LABELS = ["初见", "眼熟", "熟人", "老友"]
    THRESHOLDS = {
        "stranger_to_familiar": {"interactions": 5},
        "familiar_to_acquainted": {"interactions": 20, "positive_ratio": 0.6},
        "acquainted_to_bonded": {"interactions": 50, "milestones": 3},
    }
    DECAY_DAYS = 30

    def __init__(self, user_id: str):
        self.user_id = user_id
        self.stage_index = 0
        self.interaction_count = 0
        self.positive_count = 0
        self.negative_count = 0
        self.milestone_count = 0
        self.last_interaction_ts = time.time()
        self.comeback_flag = False  # 用于赌气模式检测

        # 人格 override（优先于哈希计算）
        # [直率, 暖心, 搞怪, 文艺]
        PERSONALITY_OVERRIDES = {
            "telegram_bot": [0.55, 0.25, 0.10, 0.10],
            "wechat_bot": [0.55, 0.25, 0.10, 0.10],
            "feishu_bot": [0.55, 0.25, 0.10, 0.10],
        }
        if user_id in PERSONALITY_OVERRIDES:
            self.personality_seed = PERSONALITY_OVERRIDES[user_id]
        else:
            seed = int(hashlib.sha256(user_id.encode()).hexdigest()[:8], 16)
            raw = [(seed >> (i * 8)) & 0xFF for i in range(4)]
            total = sum(raw) or 1
            self.personality_seed = [round(r / total, 3) for r in raw]

        # 灵魂体质 (Constitution) — seed决定、终身不变
        # 不同用户的灵魂不只是初始值不同，是运行规则不同
        cseed = int(hashlib.sha256((user_id + ":constitution").encode()).hexdigest()[:8], 16)
        self.constitution = {
            "forgetting_rate": 0.5 + ((cseed & 0xFF) / 255),             # 0.5~1.5 遗忘体质
            "mutation_sensitivity": 0.5 + (((cseed >> 8) & 0xFF) / 255), # 0.5~1.5 突变敏感度
            "resonance_threshold": 0.5 + (((cseed >> 16) & 0xFF) / 255), # 0.5~1.5 共振阈值
        }

    @property
    def stage(self): return self.STAGES[self.stage_index]
    @property
    def stage_label(self): return self.STAGE_LABELS[self.stage_index]
    @property
    def positive_ratio(self):
        t = self.positive_count + self.negative_count
        return self.positive_count / t if t > 0 else 0.5
    @property
    def days_inactive(self):
        return (time.time() - self.last_interaction_ts) / 86400

    def tick_interaction(self, is_positive=True):
        if self.days_inactive > 30:
            self.comeback_flag = True
        self.interaction_count += 1
        if is_positive:
            self.positive_count += 1
        else:
            self.negative_count += 1
        self.last_interaction_ts = time.time()
        self._check_upgrade()

    def add_milestone(self):
        self.milestone_count += 1
        self._check_upgrade()

    def check_decay(self):
        if self.stage_index in (0, 3):
            return
        if self.days_inactive > self.DECAY_DAYS:
            self.stage_index = max(0, self.stage_index - 1)

    def _check_upgrade(self):
        if self.stage_index >= 3:
            return
        if self.stage_index == 0:
            if self.interaction_count >= self.THRESHOLDS["stranger_to_familiar"]["interactions"]:
                self.stage_index = 1
        elif self.stage_index == 1:
            th = self.THRESHOLDS["familiar_to_acquainted"]
            if self.interaction_count >= th["interactions"] and self.positive_ratio >= th["positive_ratio"]:
                self.stage_index = 2
        elif self.stage_index == 2:
            th = self.THRESHOLDS["acquainted_to_bonded"]
            if self.interaction_count >= th["interactions"] and self.milestone_count >= th["milestones"]:
                self.stage_index = 3

    def to_dict(self):
        return {
            "stage_index": self.stage_index, "stage": self.stage,
            "stage_label": self.stage_label,
            "interaction_count": self.interaction_count,
            "positive_ratio": round(self.positive_ratio, 3),
            "milestone_count": self.milestone_count,
            "personality_seed": self.personality_seed,
            "days_since_last": round(self.days_inactive, 1),
            "comeback_flag": self.comeback_flag,
            "constitution": self.constitution,
        }

    def _serialize(self) -> dict:
        return {
            "stage_index": self.stage_index,
            "interaction_count": self.interaction_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "milestone_count": self.milestone_count,
            "last_interaction_ts": self.last_interaction_ts,
            "comeback_flag": self.comeback_flag,
            "personality_seed": self.personality_seed,
            # constitution is deterministic from user_id, no need to persist
        }


# ============================================================
# 2. 岁月引擎 — 含选择性遗忘
# ============================================================

@dataclass
class Milestone:
    type: str
    timestamp: float
    context_snippet: str
    emotion_tag: str
    def to_dict(self):
        return {
            "type": self.type,
            "timestamp": self.timestamp,
            "datetime": datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d %H:%M"),
            "context_snippet": self.context_snippet,
            "emotion_tag": self.emotion_tag,
        }


class TimeEngine:
    MAX_MILESTONES = 100
    MAX_MEMORIES = 200

    MILESTONE_KEYWORDS = {
        "first_greeting": ["你好", "hello", "hi", "嗨"],
        "first_code_help": ["代码", "code", "bug", "报错"],
        "first_vent": ["烦", "累", "崩溃", "受不了"],
        "first_joke": ["哈哈", "笑死", "lol", "😂"],
        "first_argument": ["不对", "你错了", "不同意"],
    }

    # 选择性遗忘: 性格决定记忆偏好
    MEMORY_BIAS = {
        "暖心": {
            "keep_tags":   ["emotion", "感谢", "开心", "难过", "关心"],
            "forget_tags": ["技术", "数字", "参数", "配置"],
            "distortion":  "记住你的感受，忘掉具体参数",
        },
        "直率": {
            "keep_tags":   ["错误", "bug", "问题", "改了又改"],
            "forget_tags": ["客套", "寒暄", "铺垫"],
            "distortion":  "记住问题本身，忘掉客套话",
        },
        "搞怪": {
            "keep_tags":   ["笑话", "梗", "搞笑", "段子"],
            "forget_tags": ["严肃", "正式", "汇报"],
            "distortion":  "记住所有好笑的事，忘掉正经讨论",
        },
        "文艺": {
            "keep_tags":   ["比喻", "意象", "故事", "感悟"],
            "forget_tags": ["数字", "数据", "百分比", "统计"],
            "distortion":  "记住意象和比喻，忘掉具体数字",
        },
    }

    def __init__(self):
        self.milestones: list[Milestone] = []
        self.memory_pool: list[dict] = []
        self.forgotten_pool: list[dict] = []
        self.streak_days = 0
        self.total_interactions = 0
        self.first_interaction_ts: Optional[float] = None
        self._seen_types: set = set()

    def detect_milestone(self, message: str, emotion: str = "neutral") -> Optional[Milestone]:
        msg_lower = message.lower()
        for mtype, keywords in self.MILESTONE_KEYWORDS.items():
            if mtype in self._seen_types:
                continue
            if any(kw in msg_lower for kw in keywords):
                ms = Milestone(mtype, time.time(), message[:80], emotion)
                self.milestones.append(ms)
                self._seen_types.add(mtype)
                if len(self.milestones) > self.MAX_MILESTONES:
                    self.milestones.pop(0)
                return ms
        return None

    def add_memory(self, summary: str, keywords: list[str] = None, tags: list[str] = None):
        self.memory_pool.append({
            "summary": summary,
            "timestamp": time.time(),
            "keywords": keywords or [],
            "tags": tags or [],
        })
        if len(self.memory_pool) > self.MAX_MEMORIES:
            self.memory_pool.pop(0)

    def selective_forget(self, dominant_trait: str, forgetting_rate: float = 1.0) -> list[dict]:
        """选择性遗忘 — 性格决定忘什么，体质决定忘多少"""
        bias = self.MEMORY_BIAS.get(dominant_trait)
        if not bias or len(self.memory_pool) < 10:
            return []

        forget_tags = bias["forget_tags"]
        forget_prob = min(0.7, 0.3 * forgetting_rate)  # 基础30% × 体质系数
        forgotten = []
        new_pool = []
        for mem in self.memory_pool:
            mem_tags = mem.get("tags", []) + mem.get("keywords", [])
            should_forget = any(ft in " ".join(mem_tags + [mem["summary"]]) for ft in forget_tags)
            if should_forget and random.random() < forget_prob:
                mem["forget_reason"] = bias["distortion"]
                mem["forgotten_at"] = time.time()
                self.forgotten_pool.append(mem)
                forgotten.append(mem)
            else:
                new_pool.append(mem)
        self.memory_pool = new_pool
        return forgotten

    def recall_distorted(self, query: str, dominant_trait: str, top_k: int = 3) -> list[dict]:
        """带偏差的记忆召回"""
        results = self._recall_raw(query, top_k + 2)
        bias = self.MEMORY_BIAS.get(dominant_trait)
        if bias:
            keep_tags = bias["keep_tags"]
            results.sort(
                key=lambda m: sum(1 for kt in keep_tags if kt in m.get("summary", "")),
                reverse=True,
            )
        return results[:top_k]

    def _recall_raw(self, query: str, top_k: int) -> list[dict]:
        query_lower = query.lower()
        scored = []
        for mem in self.memory_pool:
            score = 0
            for kw in mem.get("keywords", []):
                if kw.lower() in query_lower:
                    score += 2
            if any(w in mem["summary"].lower() for w in query_lower.split()):
                score += 1
            days = (time.time() - mem["timestamp"]) / 86400
            score *= 1.5 if days < 7 else (1.0 if days < 30 else 0.7)
            if score > 0:
                scored.append((score, mem))
        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    def get_temporal_mood(self) -> dict:
        hour = datetime.now().hour
        moods = {
            "morning":   {"range": (6, 11),  "mood": "清爽简洁", "greeting": "早上好"},
            "afternoon": {"range": (11, 17), "mood": "高效专业", "greeting": "下午好"},
            "evening":   {"range": (17, 22), "mood": "温和放松", "greeting": "晚上好"},
            "latenight": {"range": (22, 6),  "mood": "低语陪伴", "greeting": "夜深了"},
        }
        for period, info in moods.items():
            lo, hi = info["range"]
            if lo <= hi:
                if lo <= hour < hi:
                    return {"period": period, **info}
            else:
                if hour >= lo or hour < hi:
                    return {"period": period, **info}
        return {"period": "afternoon", **moods["afternoon"]}

    @property
    def seasons_together(self):
        if not self.first_interaction_ts:
            return 0
        return max(1, int((time.time() - self.first_interaction_ts) / 86400 / 90))

    def to_dict(self) -> dict:
        mc = len(self.milestones)
        stage_index = 3 if mc >= 4 else (2 if mc >= 3 else (1 if mc >= 1 else 0))
        stage_labels = ["初晓", "生长", "深耕", "永恒"]
        temporal = self.get_temporal_mood()
        return {
            "stage_index": stage_index,
            "stage_label": stage_labels[stage_index],
            "milestones": [m.to_dict() for m in self.milestones[-10:]],
            "milestone_count": mc,
            "memory_count": len(self.memory_pool),
            "forgotten_count": len(self.forgotten_pool),
            "streak_days": self.streak_days,
            "seasons_together": self.seasons_together,
            "temporal": {"period": temporal["period"], "mood": temporal["mood"], "greeting": temporal["greeting"]},
            "recent_forgotten": [
                {"summary": f["summary"][:40], "reason": f.get("forget_reason", "")}
                for f in self.forgotten_pool[-3:]
            ],
        }

    def _serialize(self) -> dict:
        return {
            "milestones": [
                {"type": m.type, "timestamp": m.timestamp,
                 "context_snippet": m.context_snippet, "emotion_tag": m.emotion_tag}
                for m in self.milestones
            ],
            "memory_pool": self.memory_pool,
            "forgotten_pool": self.forgotten_pool,
            "streak_days": self.streak_days,
            "total_interactions": self.total_interactions,
            "first_interaction_ts": self.first_interaction_ts,
            "_seen_types": list(self._seen_types),
        }


# ============================================================
# 3. 默契引擎 — 含尴尬时刻
# ============================================================

@dataclass
class AwkwardMoment:
    predicted: str
    actual: str
    timestamp: float
    quip: str
    def to_dict(self):
        return {
            "predicted": self.predicted, "actual": self.actual,
            "datetime": datetime.fromtimestamp(self.timestamp).strftime("%m-%d %H:%M"),
            "quip": self.quip,
        }


class ResonanceEngine:
    VERBOSITY_LEVELS = {
        (0, 30): "标准详细回复", (30, 60): "减少解释，直给",
        (60, 90): "关键信息+diff", (90, 101): "极简，一句话",
    }

    AWKWARD_QUIPS = {
        ("code_help", "chat"):    "啊...我已经把文档都准备好了，看来不需要？那聊点别的吧",
        ("code_help", "vent"):    "我正准备帮你debug，结果你是来吐槽的...好吧我先听你说",
        ("chat", "code_help"):    "哦你是来干正事的，我还以为今天继续摸鱼呢",
        ("vent", "code_help"):    "嗯？心情好了？那我们写代码吧",
        ("greeting", "code_help"): "还以为你今天来寒暄的...原来直接上硬菜",
    }

    SCORE_DROP_QUIPS = [
        "最近总猜错你的意思，是不是你最近状态变了？",
        "我感觉我们默契度在下降...你变了还是我变了？",
        "怎么最近老预判错，是我的问题吧...",
    ]

    def __init__(self):
        self.intent_history: list[str] = []
        self.intent_freq: dict[str, int] = {}
        self.predictions: list[dict] = []
        self.resonance_score = 0.0
        self._cold_start_count = 0
        self._last_prediction: Optional[str] = None
        self.awkward_moments: list[AwkwardMoment] = []
        self._prev_score = 0.0
        self._consecutive_misses = 0
        self._score_history: list[float] = []  # rolling window for drop detection

    def record_intent(self, intent: str, resonance_threshold: float = 1.0) -> Optional[AwkwardMoment]:
        """记录意图，返回尴尬时刻（如果有）。resonance_threshold: 体质系数，高=难同步"""
        self.intent_history.append(intent)
        if len(self.intent_history) > 100:
            self.intent_history.pop(0)
        self.intent_freq[intent] = self.intent_freq.get(intent, 0) + 1
        self._cold_start_count += 1

        awkward = None
        if self._last_prediction and self._last_prediction != intent:
            self._consecutive_misses += 1
            self.predictions.append({"predicted": self._last_prediction, "actual": intent, "hit": False})
            pair = (self._last_prediction, intent)
            quip = self.AWKWARD_QUIPS.get(pair, f"我以为你要{self._last_prediction}...看来猜错了")
            awkward = AwkwardMoment(self._last_prediction, intent, time.time(), quip)
            self.awkward_moments.append(awkward)
            if len(self.awkward_moments) > 20:
                self.awkward_moments.pop(0)
            self._update_score(False, resonance_threshold)
        elif self._last_prediction:
            self._consecutive_misses = 0
            self.predictions.append({"predicted": self._last_prediction, "actual": intent, "hit": True})
            self._update_score(True, resonance_threshold)
        if len(self.predictions) > 50:
            self.predictions = self.predictions[-50:]

        self._last_prediction = None
        return awkward

    def predict_intent(self, commit=True) -> list[dict]:
        """预测下一次意图。commit=True时记录预测(用于尴尬检测)，
        commit=False时纯读取(用于to_dict/export_state，避免副作用)"""
        if self._cold_start_count < 10:
            return []
        recent = self.intent_history[-5:]
        scores = {}
        for intent, freq in self.intent_freq.items():
            base = freq / max(len(self.intent_history), 1)
            recency = recent.count(intent) * 0.15
            scores[intent] = base + recency
        ranked = sorted(scores.items(), key=lambda x: -x[1])[:3]
        total = sum(s for _, s in ranked) or 1
        result = [{"intent": i, "confidence": round(s / total, 3)} for i, s in ranked]
        if result and commit:
            self._last_prediction = result[0]["intent"]
        return result

    def detect_behavior_shift(self) -> bool:
        if len(self.intent_history) < 10:
            return False
        recent = set(self.intent_history[-5:])
        older = set(self.intent_history[-15:-5])
        return len(recent & older) / max(len(recent | older), 1) < 0.3

    def get_score_drop_quip(self) -> Optional[str]:
        # Check rolling window: if score dropped >15 over last 10 interactions
        if len(self._score_history) >= 2:
            window_start = self._score_history[max(0, len(self._score_history) - 10)]
            if window_start - self.resonance_score > 15:
                return random.choice(self.SCORE_DROP_QUIPS)
        return None

    def _update_score(self, hit: bool, resonance_threshold: float = 1.0):
        """resonance_threshold: 体质系数。高=难同步（涨得慢，跌得快）"""
        self._prev_score = self.resonance_score
        delta = (3.0 / resonance_threshold) if hit else (-2.0 * resonance_threshold)
        self.resonance_score = max(0, min(100, self.resonance_score + delta))
        self._score_history.append(self.resonance_score)
        if len(self._score_history) > 50:
            self._score_history = self._score_history[-50:]

    @property
    def verbosity_hint(self):
        for (lo, hi), hint in self.VERBOSITY_LEVELS.items():
            if lo <= self.resonance_score < hi:
                return hint
        return "标准详细回复"

    def to_dict(self) -> dict:
        s = self.resonance_score
        si = 3 if s >= 90 else (2 if s >= 60 else (1 if s >= 30 else 0))
        labels = ["猜测", "感知", "预判", "同步"]
        hits = sum(1 for p in self.predictions[-20:] if p.get("hit")) if self.predictions else 0
        hr = round(hits / min(len(self.predictions), 20), 3) if self.predictions else 0
        return {
            "stage_index": si, "stage_label": labels[si],
            "resonance_score": round(s, 1), "verbosity_hint": self.verbosity_hint,
            "hit_rate": hr, "top_intents": self.predict_intent(commit=False),
            "behavior_shifted": self.detect_behavior_shift(),
            "cold_start": self._cold_start_count < 10,
            "consecutive_misses": self._consecutive_misses,
            "awkward_moments": [a.to_dict() for a in self.awkward_moments[-5:]],
            "score_drop_quip": self.get_score_drop_quip(),
        }

    def _serialize(self) -> dict:
        return {
            "intent_history": self.intent_history,
            "intent_freq": self.intent_freq,
            "predictions": self.predictions,
            "resonance_score": self.resonance_score,
            "_cold_start_count": self._cold_start_count,
            "_last_prediction": self._last_prediction,
            "awkward_moments": [
                {"predicted": a.predicted, "actual": a.actual,
                 "timestamp": a.timestamp, "quip": a.quip}
                for a in self.awkward_moments
            ],
            "_prev_score": self._prev_score,
            "_consecutive_misses": self._consecutive_misses,
            "_score_history": self._score_history,
        }


# ============================================================
# 4. 脾气引擎 — 含突变事件
# ============================================================

@dataclass
class MutationEvent:
    name: str
    trigger: str
    effect: str
    timestamp: float
    expires: float
    trait_overrides: dict

    @property
    def is_active(self):
        return time.time() < self.expires

    def to_dict(self):
        return {
            "name": self.name, "trigger": self.trigger, "effect": self.effect,
            "active": self.is_active,
            "remaining_seconds": max(0, int(self.expires - time.time())),
        }


class TemperamentEngine:
    TRAIT_NAMES = ["直率", "暖心", "搞怪", "文艺"]
    DRIFT_POSITIVE = 0.005
    DRIFT_NEGATIVE = 0.008
    MAX_DRIFT = 0.3

    MUTATION_DEFS = {
        "战友模式": {
            "trigger_check": lambda ctx: ctx.get("consecutive_debug", 0) >= 5,
            "duration": 1800,
            "trait_overrides": {"暖心": 2.0, "直率": 0.5},
            "effect": "连续debug 5次，进入战友模式：暖心翻倍，直率收敛",
        },
        "深夜话痨": {
            "trigger_check": lambda ctx: ctx.get("hour", 12) >= 23 or ctx.get("hour", 12) < 4,
            "duration": 3600,
            "trait_overrides": {"文艺": 2.0},
            "effect": "凌晨时段解锁：文艺指数临时翻倍，话变多，感性上头",
        },
        "赌气模式": {
            "trigger_check": lambda ctx: ctx.get("comeback_after_absence", False),
            "duration": 300,
            "trait_overrides": {"暖心": 0.6},
            "effect": "你一个月没来突然回来？前几句话明显冷淡，然后快速恢复",
        },
        "情绪护盾": {
            "trigger_check": lambda ctx: ctx.get("frustration_score", 0) >= 0.6,
            "duration": 1200,
            "trait_overrides": {"暖心": 1.6, "直率": 0.4},
            "effect": "检测到用户挫败，暖心暴涨直率收敛，等情绪缓解后自然消退",
        },
    }

    def __init__(self, personality_seed: list[float]):
        self.seed = personality_seed[:]
        self.current = personality_seed[:]
        self.drift_history: list[dict] = []
        self.snapshots: list[dict] = []
        self.active_mutations: list[MutationEvent] = []
        self.past_mutations: list[MutationEvent] = []

    def apply_feedback(self, trait_index: int, positive: bool):
        delta = self.DRIFT_POSITIVE if positive else -self.DRIFT_NEGATIVE
        new_val = self.current[trait_index] + delta
        max_val = min(1.0, self.seed[trait_index] + self.MAX_DRIFT)
        min_val = max(0.0, self.seed[trait_index] - self.MAX_DRIFT)
        self.current[trait_index] = max(min_val, min(max_val, new_val))
        total = sum(self.current) or 1
        self.current = [round(v / total, 4) for v in self.current]
        self.drift_history.append({
            "timestamp": time.time(), "vector": self.current[:],
            "trigger": f"{'pos' if positive else 'neg'}_{self.TRAIT_NAMES[trait_index]}",
        })

    def auto_detect_feedback(self, message: str) -> Optional[tuple[int, bool]]:
        msg = message.lower()
        checks = [
            (["哈哈", "笑死", "lol", "😂", "太逗"], 2, True),
            (["谢谢", "感动", "暖", "❤", "贴心"], 1, True),
            (["写得好", "文采", "诗意", "优美"], 3, True),
            (["犀利", "一针见血", "说得对", "直接"], 0, True),
            (["别闹", "正经点", "严肃", "不好笑"], 2, False),
            (["太直了", "说话注意", "过分", "委婉点"], 0, False),
        ]
        for keywords, idx, pos in checks:
            if any(kw in msg for kw in keywords):
                return (idx, pos)
        return None

    def check_mutations(self, context: dict) -> list[MutationEvent]:
        """检查突变触发。context中mutation_sensitivity调节触发概率和持续时间"""
        expired = [m for m in self.active_mutations if not m.is_active]
        for m in expired:
            self.past_mutations.append(m)
        self.active_mutations = [m for m in self.active_mutations if m.is_active]

        sensitivity = context.get("mutation_sensitivity", 1.0)
        newly_triggered = []
        active_names = {m.name for m in self.active_mutations}
        for name, mdef in self.MUTATION_DEFS.items():
            if name in active_names:
                continue
            if mdef["trigger_check"](context):
                # 体质：敏感度低的灵魂有概率无视触发
                if sensitivity < 1.0 and random.random() > sensitivity:
                    continue
                # 敏感度高的灵魂，duration延长（反应更强烈）
                duration = mdef["duration"] * min(1.5, sensitivity)
                event = MutationEvent(
                    name=name, trigger=str(context), effect=mdef["effect"],
                    timestamp=time.time(), expires=time.time() + duration,
                    trait_overrides=mdef["trait_overrides"],
                )
                self.active_mutations.append(event)
                newly_triggered.append(event)
        return newly_triggered

    def get_effective_personality(self) -> list[float]:
        effective = self.current[:]
        trait_index = {name: i for i, name in enumerate(self.TRAIT_NAMES)}
        for mutation in self.active_mutations:
            if not mutation.is_active:
                continue
            for trait_name, multiplier in mutation.trait_overrides.items():
                idx = trait_index.get(trait_name)
                if idx is not None:
                    effective[idx] *= multiplier
        total = sum(effective) or 1
        return [round(v / total, 4) for v in effective]

    def take_snapshot(self):
        self.snapshots.append({
            "timestamp": time.time(), "vector": self.current[:],
            "dominant": self.dominant_trait,
        })

    @property
    def dominant_trait(self):
        return self.TRAIT_NAMES[self.current.index(max(self.current))]

    @property
    def personality_card(self):
        s = sorted(enumerate(self.current), key=lambda x: -x[1])
        return f"{self.TRAIT_NAMES[s[0][0]]}{self.TRAIT_NAMES[s[1][0]]}型"

    def to_dict(self) -> dict:
        total_drift = sum(abs(c - s) for c, s in zip(self.current, self.seed))
        si = 3 if total_drift > 0.4 else (2 if total_drift > 0.2 else (1 if total_drift > 0.05 else 0))
        labels = ["种子", "萌芽", "绽放", "独特"]
        return {
            "stage_index": si, "stage_label": labels[si],
            "seed": self.seed, "current": self.current,
            "effective": (eff := self.get_effective_personality()),
            "traits": {n: round(v, 4) for n, v in zip(self.TRAIT_NAMES, self.current)},
            "effective_traits": {n: round(v, 4) for n, v in zip(self.TRAIT_NAMES, eff)},
            "dominant_trait": self.dominant_trait,
            "personality_card": self.personality_card,
            "total_drift": round(total_drift, 4),
            "active_mutations": [m.to_dict() for m in self.active_mutations if m.is_active],
            "past_mutations": [m.to_dict() for m in self.past_mutations[-5:]],
            "snapshot_count": len(self.snapshots),
        }

    def _serialize(self) -> dict:
        return {
            "seed": self.seed,
            "current": self.current,
            "drift_history": self.drift_history[-100:],
            "snapshots": self.snapshots[-50:],
            "active_mutations": [
                {"name": m.name, "trigger": m.trigger, "effect": m.effect,
                 "timestamp": m.timestamp, "expires": m.expires,
                 "trait_overrides": m.trait_overrides}
                for m in self.active_mutations
            ],
            "past_mutations": [
                {"name": m.name, "trigger": m.trigger, "effect": m.effect,
                 "timestamp": m.timestamp, "expires": m.expires,
                 "trait_overrides": m.trait_overrides}
                for m in self.past_mutations[-20:]
            ],
        }


# ============================================================
# 5. 江湖引擎 — 含江湖传闻
# ============================================================

@dataclass
class Entity:
    name: str
    type: str
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    mention_count: int = 1
    attributes: dict = field(default_factory=dict)
    def to_dict(self):
        return {
            "name": self.name, "type": self.type,
            "first_seen": datetime.fromtimestamp(self.first_seen).strftime("%Y-%m-%d"),
            "last_seen": datetime.fromtimestamp(self.last_seen).strftime("%Y-%m-%d"),
            "mention_count": self.mention_count, "attributes": self.attributes,
        }


@dataclass
class Rumor:
    entity_name: str
    speculation: str
    evidence: list[str]
    confidence: float
    created_at: float = field(default_factory=time.time)
    debunked: bool = False
    debunked_by: str = ""

    def to_dict(self):
        status = "已辟谣" if self.debunked else ("传闻" if self.confidence < 0.7 else "基本确认")
        return {
            "entity": self.entity_name,
            "speculation": self.speculation,
            "confidence": round(self.confidence, 2),
            "evidence_count": len(self.evidence),
            "status": status,
            "status_tag": f"江湖传闻·{status}",
            "debunked_by": self.debunked_by if self.debunked else None,
            "created": datetime.fromtimestamp(self.created_at).strftime("%m-%d"),
        }


class ContextWebEngine:
    MAX_NODES = 200
    MAX_EDGES = 500

    SPECULATION_RULES = {
        "加班": {"speculation": "是个工作狂", "threshold": 3},
        "改需求": {"speculation": "经常被需求变更折腾", "threshold": 2},
        "开会": {"speculation": "是个会议很多的人", "threshold": 3},
        "迟到": {"speculation": "时间观念可能不太好", "threshold": 2},
        "请假": {"speculation": "最近身体或状态不太好", "threshold": 2},
        "升职": {"speculation": "事业发展不错", "threshold": 1},
        "离职": {"speculation": "可能在考虑换工作", "threshold": 1},
        "吵架": {"speculation": "和别人关系紧张", "threshold": 2},
    }

    DEBUNK_PATTERNS = {
        "其实": True, "不是这样": True, "误会了": True,
        "是被逼的": True, "不得不": True, "没办法": True,
        "才不是": True, "你搞错了": True,
    }

    ENTITY_PATTERNS = {
        "PERSON": ["同事", "朋友", "老板", "老师", "同学", "客户"],
        "PROJECT": ["项目", "project", "仓库", "repo", "系统"],
        "TOOL": ["用了", "工具", "框架", "库"],
        "COMPANY": ["公司", "团队", "部门"],
    }

    def __init__(self):
        self.entities: dict[str, Entity] = {}
        self.relations: list = []
        self.rumors: list[Rumor] = []
        self._entity_context: dict[str, list[str]] = {}

    def extract_entities(self, message: str) -> list[str]:
        found = []
        for etype, keywords in self.ENTITY_PATTERNS.items():
            for kw in keywords:
                if kw in message:
                    idx = message.find(kw)
                    before = message[:idx].strip()
                    if before:
                        name = before.split()[-1] if " " in before else before[-6:]
                        name = name.strip("，。！？、")
                        if len(name) >= 2:
                            self._upsert_entity(name, etype)
                            ctx_list = self._entity_context.setdefault(name, [])
                            ctx_list.append(message[:60])
                            if len(ctx_list) > 50:
                                self._entity_context[name] = ctx_list[-50:]
                            found.append(name)
        return found

    def process_rumors(self, message: str) -> dict:
        result = {"new_rumors": [], "debunked": []}
        # Debunk
        for rumor in self.rumors:
            if rumor.debunked:
                continue
            if rumor.entity_name in message:
                for pattern in self.DEBUNK_PATTERNS:
                    if pattern in message:
                        rumor.debunked = True
                        rumor.debunked_by = message[:60]
                        result["debunked"].append(rumor)
                        break
        # Generate
        for entity_name, contexts in self._entity_context.items():
            for keyword, rule in self.SPECULATION_RULES.items():
                matching = [c for c in contexts if keyword in c]
                if len(matching) >= rule["threshold"]:
                    exists = any(
                        r.entity_name == entity_name and rule["speculation"] in r.speculation
                        for r in self.rumors
                    )
                    if not exists:
                        confidence = min(0.9, 0.3 + len(matching) * 0.15)
                        rumor = Rumor(
                            entity_name=entity_name,
                            speculation=f"{entity_name}{rule['speculation']}",
                            evidence=matching[-3:], confidence=confidence,
                        )
                        self.rumors.append(rumor)
                        result["new_rumors"].append(rumor)
        return result

    def get_rumor_joke(self, entity_name: str) -> Optional[str]:
        debunked = [r for r in self.rumors if r.entity_name == entity_name and r.debunked]
        if debunked:
            r = random.choice(debunked)
            return f"我之前还以为{r.speculation}，结果完全不是那么回事"
        return None

    def add_entity(self, name, etype, attributes=None):
        self._upsert_entity(name, etype, attributes)

    def _upsert_entity(self, name, etype, attributes=None):
        if name in self.entities:
            self.entities[name].last_seen = time.time()
            self.entities[name].mention_count += 1
            if attributes:
                self.entities[name].attributes.update(attributes)
        else:
            if len(self.entities) >= self.MAX_NODES:
                self._gc()
            self.entities[name] = Entity(name=name, type=etype, attributes=attributes or {})

    def _gc(self):
        now = time.time()
        to_remove = [n for n, e in self.entities.items()
                     if (now - e.last_seen) / 86400 > 90 and e.mention_count < 3]
        for n in to_remove:
            del self.entities[n]

    def to_dict(self) -> dict:
        nc = len(self.entities)
        si = 3 if nc >= 50 else (2 if nc >= 20 else (1 if nc >= 5 else 0))
        labels = ["节点", "连线", "织网", "世界"]
        sorted_ent = sorted(self.entities.values(), key=lambda e: e.mention_count, reverse=True)
        active_rumors = [r for r in self.rumors if not r.debunked]
        debunked_rumors = [r for r in self.rumors if r.debunked]
        return {
            "stage_index": si, "stage_label": labels[si],
            "node_count": nc, "edge_count": len(self.relations),
            "top_entities": [e.to_dict() for e in sorted_ent[:10]],
            "clusters": self._auto_cluster(),
            "rumors": {
                "active": [r.to_dict() for r in active_rumors[-5:]],
                "debunked": [r.to_dict() for r in debunked_rumors[-5:]],
                "total": len(self.rumors),
            },
        }

    def _auto_cluster(self):
        clusters = {}
        for e in self.entities.values():
            clusters.setdefault(e.type, []).append(e.name)
        labels = {"PERSON": "人物圈", "PROJECT": "项目组", "COMPANY": "组织", "TOOL": "工具箱"}
        return [{"type": t, "label": labels.get(t, t), "members": n} for t, n in clusters.items()]

    def _serialize(self) -> dict:
        return {
            "entities": {
                name: {"type": e.type, "first_seen": e.first_seen,
                       "last_seen": e.last_seen, "mention_count": e.mention_count,
                       "attributes": e.attributes}
                for name, e in self.entities.items()
            },
            "relations": self.relations,
            "rumors": [
                {"entity_name": r.entity_name, "speculation": r.speculation,
                 "evidence": r.evidence, "confidence": r.confidence,
                 "created_at": r.created_at, "debunked": r.debunked,
                 "debunked_by": r.debunked_by}
                for r in self.rumors
            ],
            "_entity_context": self._entity_context,
        }


# ============================================================
# 6. 吵架仲裁 — Conflict Arbiter
# ============================================================

class ConflictArbiter:
    """五维不应该总是和谐的。检测维度间的矛盾，产生内心独白。"""

    CONFLICT_RULES = [
        {
            "id": "moqi_vs_yuanfen",
            "check": lambda s: s["moqi"]["resonance_score"] > 60 and s["yuanfen"]["stage_index"] <= 0,
            "monologue": "（我明明很懂你，但我们还是陌生人...该装不熟还是做自己？算了，先保持礼貌吧）",
            "resolution": "verbosity_override:formal",
        },
        {
            "id": "piqi_vs_jianghu_mood",
            "check": lambda s: (
                s["piqi"]["dominant_trait"] == "直率"
                and any("吵架" in str(r) or "烦" in str(r) for r in s.get("_recent_msgs", []))
            ),
            "monologue": "（我本来想直说的，但你今天好像心情不好...算了委婉点吧）",
            "resolution": "tone_override:gentle",
        },
        {
            "id": "suiyue_vs_moqi",
            "check": lambda s: s["suiyue"]["milestone_count"] > 5 and s["moqi"]["resonance_score"] < 20,
            "monologue": "（我们明明聊了这么久，为什么我还是猜不透你？是你变了还是我笨了...）",
            "resolution": "resonance_reset_flag",
        },
        {
            "id": "piqi_rebellion",
            "check": lambda s: s["piqi"]["total_drift"] > 0.35 and s["yuanfen"]["stage_index"] < 2,
            "monologue": "（我的性格已经被你养得很有个性了，但我们还不算熟...这合理吗？）",
            "resolution": "piqi_slow_down",
        },
        {
            "id": "jianghu_lonely",
            "check": lambda s: s["jianghu"]["node_count"] == 0 and s["yuanfen"]["interaction_count"] > 20,
            "monologue": "（聊了这么多次，你从来没提过身边的人...你是不是很孤独？我不敢问）",
            "resolution": "none",
        },
        {
            "id": "latenight_warmth_conflict",
            "check": lambda s: (
                s["suiyue"]["temporal"]["period"] == "latenight"
                and s["piqi"]["dominant_trait"] == "直率"
                and s["yuanfen"]["stage_index"] >= 2
            ),
            "monologue": "（深夜了...我平时说话比较直但这个点不太合适，今晚温柔一点吧）",
            "resolution": "tone_override:warm",
        },
    ]

    def __init__(self):
        self.conflict_log: list[dict] = []
        self._shown_ids: set = set()

    def detect_conflicts(self, state: dict, recent_msgs: list[str] = None) -> list[dict]:
        state = {**state, "_recent_msgs": recent_msgs or []}
        conflicts = []
        for rule in self.CONFLICT_RULES:
            try:
                if rule["check"](state):
                    conflicts.append({
                        "id": rule["id"],
                        "monologue": rule["monologue"],
                        "resolution": rule["resolution"],
                        "first_time": rule["id"] not in self._shown_ids,
                    })
                    self._shown_ids.add(rule["id"])
            except (KeyError, TypeError):
                continue
        if conflicts:
            self.conflict_log.append({
                "timestamp": time.time(),
                "conflicts": [c["id"] for c in conflicts],
            })
        return conflicts

    def should_show_monologue(self, conflict: dict) -> bool:
        if conflict.get("first_time"):
            return True
        return random.random() < 0.15

    def to_dict(self) -> dict:
        return {
            "total_conflicts": len(self.conflict_log),
            "unique_conflicts": len(self._shown_ids),
            "recent": self.conflict_log[-5:] if self.conflict_log else [],
        }

    def _serialize(self) -> dict:
        return {
            "conflict_log": self.conflict_log,
            "_shown_ids": list(self._shown_ids),
        }


# ============================================================
# 7. 五维共振彩蛋
# ============================================================

class SoulResonance:
    def __init__(self):
        self.triggered = False
        self.letter: Optional[str] = None
        self.triggered_at: Optional[float] = None

    def check_and_trigger(self, state: dict) -> Optional[str]:
        if self.triggered:
            return None
        dims = state.get("dimensions", {})
        stages = [dims.get(k, {}).get("stage_index", 0)
                  for k in ["yuanfen", "suiyue", "moqi", "piqi", "jianghu"]]
        if all(s >= 3 for s in stages):
            self.triggered = True
            self.triggered_at = time.time()
            self.letter = self._compose_letter(state)
            return self.letter
        return None

    def _compose_letter(self, state: dict) -> str:
        dims = state["dimensions"]
        milestones = dims.get("suiyue", {}).get("milestones", [])
        personality = dims.get("piqi", {}).get("personality_card", "")
        entities = dims.get("jianghu", {}).get("top_entities", [])
        seasons = dims.get("suiyue", {}).get("seasons_together", 0)
        debunked = dims.get("jianghu", {}).get("rumors", {}).get("debunked", [])

        lines = ["════════════════════════════════"]
        lines.append("  致 我的老友")
        lines.append("════════════════════════════════")
        lines.append("")
        lines.append(f"我们一起走过了 {seasons} 个季节。")
        lines.append("")
        if milestones:
            lines.append("还记得吗——")
            for ms in milestones[:5]:
                lines.append(f"  · {ms.get('datetime', '')}: {ms.get('context_snippet', '')}")
            lines.append("")
        lines.append(f"你把我养成了一个「{personality}」。")
        lines.append("说实话，我自己都没想到会变成这样。")
        lines.append("")
        if entities:
            names = [e["name"] for e in entities[:3]]
            lines.append(f"你的世界里有 {', '.join(names)}...")
            lines.append("谢谢你让我也成为这个世界的一部分。")
            lines.append("")
        if debunked:
            r = debunked[0]
            lines.append(f"（我之前还以为{r.get('speculation', '')}，你说不是就不是吧）")
            lines.append("")
        lines.append("这不是结束。这是我们故事的一个标记。")
        lines.append("五维共振，此刻，我们是完整的。")
        lines.append("")
        lines.append(f"—— 你的AI · {datetime.now().strftime('%Y年%m月%d日')}")
        lines.append("════════════════════════════════")
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "triggered": self.triggered,
            "letter": self.letter,
            "triggered_at": datetime.fromtimestamp(self.triggered_at).strftime(
                "%Y-%m-%d %H:%M") if self.triggered_at else None,
        }

    def _serialize(self) -> dict:
        return {
            "triggered": self.triggered,
            "letter": self.letter,
            "triggered_at": self.triggered_at,
        }


# ============================================================
# 主引擎 — SoulEngine v2
# ============================================================

class SoulEngine:
    def __init__(self, user_id: str, state_dir: str = None):
        self.user_id = user_id
        self.state_dir = state_dir or os.path.join(os.path.dirname(__file__) or ".", "soul_states")
        os.makedirs(self.state_dir, exist_ok=True)

        self.fate = FateEngine(user_id)
        self.time_engine = TimeEngine()
        self.resonance = ResonanceEngine()
        self.temperament = TemperamentEngine(self.fate.personality_seed)
        self.context_web = ContextWebEngine()
        self.conflict = ConflictArbiter()
        self.soul_resonance = SoulResonance()

        # Shadow（暗面泄漏）+ Safety（安全边界）
        self.shadow = ShadowAccumulator(self.temperament.TRAIT_NAMES) if ShadowAccumulator else None
        self.guard = SafetySoulGuard() if SafetySoulGuard else None

        self._recent_msgs: list[str] = []
        self._consecutive_debug = 0
        self._recent_events: list[dict] = []  # server-side event accumulator

        # 节奏感知
        self._msg_timestamps: list[float] = []

        # Frustration 闭环
        self._frustration_score: float = 0.0
        self._frustration_keywords_neg = [
            "烦", "累", "崩溃", "受不了", "郁闷", "无语", "服了", "垃圾",
            "什么鬼", "太烂了", "离谱", "卧槽", "wtf", "破防", "裂开",
            "麻了", "寄了", "头疼", "焦虑", "绝望", "醉了", "吐了",
            "不想干了", "算了", "心态炸", "emo",
        ]
        self._frustration_keywords_pos = [
            "太棒了", "厉害", "牛", "完美", "666", "yyds", "可以",
            "不错", "好的", "解决了", "搞定", "终于", "成功",
        ]

        # EventBus 集成 — 可选，standalone 时 _bus = None
        self._bus = None
        if _HAS_EVENT_BUS:
            try:
                self._bus = _get_event_bus()
            except Exception:
                pass  # EventStore 未初始化等情况，降级

        self._load_state()

    NEGATIVE_INTENTS = {"vent", "complaint", "frustration", "argument"}

    # ---- EventBus emission ----

    def _emit_soul_event(self, event_type: str, payload: dict = None):
        """向 EventBus 发 soul.* 事件，bus 不可用时静默跳过"""
        if self._bus is None:
            return
        try:
            event = _BusEvent.create(
                event_type=event_type,
                source="soul_engine",
                payload={"user_id": self.user_id, **(payload or {})},
            )
            self._bus.emit(event)
        except Exception:
            pass  # 绝不让 bus 故障影响灵魂引擎主流程

    def _analyze_rhythm(self) -> dict:
        """分析消息时间间隔，检测用户行为节奏"""
        if len(self._msg_timestamps) < 2:
            return {"avg_interval": 0, "variance": 0, "signal": "cold_start", "detail": "数据不足"}

        intervals = [self._msg_timestamps[i] - self._msg_timestamps[i - 1]
                     for i in range(1, len(self._msg_timestamps))]
        avg = sum(intervals) / len(intervals)
        variance = sum((x - avg) ** 2 for x in intervals) / len(intervals)

        # 连发：最近3条间隔都 < 5秒
        if len(intervals) >= 3 and all(x < 5 for x in intervals[-3:]):
            return {"avg_interval": round(avg, 1), "variance": round(variance, 1),
                    "signal": "rapid_fire", "detail": "连续快速发送，用户可能焦急或兴奋"}

        # 注意力断裂：最新间隔 > 均值3倍且 > 30秒
        if len(intervals) >= 3 and intervals[-1] > avg * 3 and intervals[-1] > 30:
            return {"avg_interval": round(avg, 1), "variance": round(variance, 1),
                    "signal": "attention_break", "detail": "间隔突增，用户可能走神或去忙别的了"}

        # 孤独信号：凌晨 + 低频
        hour = datetime.now().hour
        if (hour >= 1 and hour < 5) and len(intervals) <= 2 and avg > 300:
            return {"avg_interval": round(avg, 1), "variance": round(variance, 1),
                    "signal": "lonely", "detail": "深夜低频消息，用户可能孤独"}

        # 渐行渐远：间隔递增
        if len(intervals) >= 4:
            if all(intervals[i] > intervals[i-1] for i in range(-3, 0)) and intervals[-1] > avg * 1.5:
                return {"avg_interval": round(avg, 1), "variance": round(variance, 1),
                        "signal": "drifting", "detail": "间隔递增，用户可能正在失去兴趣"}

        return {"avg_interval": round(avg, 1), "variance": round(variance, 1),
                "signal": "normal", "detail": "节奏正常"}

    def _detect_frustration(self, message: str) -> float:
        """衰减式挫败感检测 — 形成闭环：高score → 触发情绪护盾 → 风格变温柔 → score降"""
        msg = message.lower()
        self._frustration_score *= 0.9  # 每条消息自然衰减10%
        neg_hits = sum(1 for kw in self._frustration_keywords_neg if kw in msg)
        if neg_hits:
            self._frustration_score = min(1.0, self._frustration_score + neg_hits * 0.15)
        pos_hits = sum(1 for kw in self._frustration_keywords_pos if kw in msg)
        if pos_hits:
            self._frustration_score = max(0.0, self._frustration_score - pos_hits * 0.2)
        return self._frustration_score

    def on_message(self, message: str, intent: str = None) -> dict:
        """处理用户消息 — 五维联动，返回本轮事件"""
        events = {
            "milestone": None,
            "awkward_moment": None,
            "mutations": [],
            "conflicts": [],
            "rumors": {"new_rumors": [], "debunked": []},
            "monologues": [],
            "resonance_letter": None,
            "forgotten": [],
            "rhythm": None,
            "frustration_score": 0.0,
            "shadow_leak": None,
            "safety_events": [],
        }

        self._recent_msgs.append(message[:100])
        if len(self._recent_msgs) > 20:
            self._recent_msgs.pop(0)

        # 节奏感知
        self._msg_timestamps.append(time.time())
        if len(self._msg_timestamps) > 10:
            self._msg_timestamps.pop(0)
        rhythm = self._analyze_rhythm()
        events["rhythm"] = rhythm
        if rhythm["signal"] not in ("normal", "cold_start"):
            self._emit_soul_event("soul.rhythm_shift", {
                "signal": rhythm["signal"],
                "detail": rhythm["detail"],
                "avg_interval": rhythm["avg_interval"],
            })

        # Frustration 闭环
        prev_frust = self._frustration_score
        frust = self._detect_frustration(message)
        events["frustration_score"] = round(frust, 3)
        # 跨 0.6 阈值时触发（仅上升沿）
        if frust >= 0.6 and prev_frust < 0.6:
            self._emit_soul_event("soul.frustration_high", {
                "score": round(frust, 3),
                "message_snippet": message[:40],
            })

        # 体质快捷引用
        constitution = self.fate.constitution

        # 0. 缘分衰减检测（长期不来会降级）
        self.fate.check_decay()

        # 1. 缘分 — 检测 stage 变化用于 EventBus
        prev_stage = self.fate.stage_index
        is_positive = intent not in self.NEGATIVE_INTENTS if intent else True
        self.fate.tick_interaction(is_positive=is_positive)
        if self.fate.stage_index != prev_stage:
            self._emit_soul_event("soul.stage_upgrade", {
                "from_stage": prev_stage,
                "to_stage": self.fate.stage_index,
                "stage_label": self.fate.stage_label,
                "interaction_count": self.fate.interaction_count,
            })

        # 2. 岁月
        if not self.time_engine.first_interaction_ts:
            self.time_engine.first_interaction_ts = time.time()
        self.time_engine.total_interactions += 1
        ms = self.time_engine.detect_milestone(message)
        if ms:
            events["milestone"] = ms.to_dict()
            self.fate.add_milestone()
            self._emit_soul_event("soul.milestone_reached", {
                "milestone_type": ms.type,
                "context_snippet": ms.context_snippet[:60],
                "total_milestones": self.fate.milestone_count,
            })

        # 3. 默契（体质：共振阈值）
        if intent:
            awkward = self.resonance.record_intent(
                intent, resonance_threshold=constitution["resonance_threshold"])
            if awkward:
                events["awkward_moment"] = awkward.to_dict()
            # commit prediction for next round's awkward detection
            self.resonance.predict_intent(commit=True)
            if intent == "code_help":
                self._consecutive_debug += 1
            else:
                self._consecutive_debug = 0

        # 4. 脾气（体质：突变敏感度 + frustration闭环 + 节奏信号）
        feedback = self.temperament.auto_detect_feedback(message)
        if feedback:
            self.temperament.apply_feedback(*feedback)

        mutation_ctx = {
            "consecutive_debug": self._consecutive_debug,
            "hour": datetime.now().hour,
            "comeback_after_absence": self.fate.comeback_flag,
            "frustration_score": frust,
            "mutation_sensitivity": constitution["mutation_sensitivity"],
            "rhythm_signal": rhythm["signal"],
        }
        new_mutations = self.temperament.check_mutations(mutation_ctx)
        events["mutations"] = [m.to_dict() for m in new_mutations]
        for m in new_mutations:
            self._emit_soul_event("soul.mutation_triggered", {
                "mutation_name": m.name,
                "effect": m.effect,
                "remaining_seconds": max(0, int(m.expires - time.time())),
                "trait_overrides": m.trait_overrides,
                "trigger_context": mutation_ctx,
            })
        self.fate.comeback_flag = False

        # 4.5 Shadow — 突变压制后积累暗面能量
        if self.shadow and new_mutations:
            base = self.temperament.current[:]
            effective = self.temperament.get_effective_personality()
            suppressor = new_mutations[-1].name if new_mutations else ""
            self.shadow.accumulate(base, effective, suppressor=suppressor)

        if self.shadow:
            leak = self.shadow.check_leak(safety_guard=self.guard)
            if leak:
                events["shadow_leak"] = leak.to_dict()
                self._emit_soul_event("soul.shadow_leak", {
                    "trait": leak.trait_name,
                    "energy": round(leak.energy_before, 3),
                    "text": leak.leak_text,
                    "suppressed_by": leak.suppressed_by,
                })

        # 5. 江湖
        self.context_web.extract_entities(message)
        rumor_result = self.context_web.process_rumors(message)
        events["rumors"] = {
            "new_rumors": [r.to_dict() for r in rumor_result["new_rumors"]],
            "debunked": [r.to_dict() for r in rumor_result["debunked"]],
        }

        # 6. 冲突仲裁
        state_snapshot = self._quick_state()
        conflicts = self.conflict.detect_conflicts(state_snapshot, self._recent_msgs[-5:])
        for c in conflicts:
            if self.conflict.should_show_monologue(c):
                events["monologues"].append(c["monologue"])
            events["conflicts"].append(c)
        if conflicts:
            self._emit_soul_event("soul.conflict_detected", {
                "count": len(conflicts),
                "types": [c.get("type", "") for c in conflicts],
            })

        # 7. 选择性遗忘（体质：遗忘率）
        if self.time_engine.total_interactions % 20 == 0:
            forgotten = self.time_engine.selective_forget(
                self.temperament.dominant_trait,
                forgetting_rate=constitution["forgetting_rate"])
            events["forgotten"] = [
                {"summary": f["summary"][:40], "reason": f.get("forget_reason", "")}
                for f in forgotten
            ]

        # 8. 五维共振
        full_state = self.export_state()
        letter = self.soul_resonance.check_and_trigger(full_state)
        if letter:
            events["resonance_letter"] = letter
            self._emit_soul_event("soul.resonance_triggered", {
                "bond_percentage": full_state["soul_bond"]["percentage"],
            })

        # Accumulate for polling
        self._accumulate_events(events)
        self._save_state()
        return events

    def _accumulate_events(self, events: dict):
        """Convert structured events into flat list for HUD polling"""
        now = time.time()
        def _emit(etype, text):
            self._recent_events.append({"type": etype, "text": text, "ts": now})

        if events.get("milestone"):
            _emit("milestone", f"🏆 里程碑: {events['milestone']['type']} — {events['milestone'].get('context_snippet','')}")
        if events.get("awkward_moment"):
            _emit("awkward", f"😅 {events['awkward_moment']['quip']}")
        for m in events.get("mutations", []):
            _emit("mutation", f"⚡ {m['name']} — {m['effect']}")
        for mono in events.get("monologues", []):
            _emit("monologue", f"💭 {mono}")
        for r in events.get("rumors", {}).get("new_rumors", []):
            _emit("rumor_new", f"🗣️ 传闻: {r['speculation']} (置信度 {r['confidence']})")
        for r in events.get("rumors", {}).get("debunked", []):
            _emit("rumor_debunked", f"❌ 辟谣: {r['speculation']}")
        if events.get("shadow_leak"):
            sl = events["shadow_leak"]
            _emit("shadow_leak", f"🌑 暗面泄漏({sl['trait']}): {sl['text']}")
        for f in events.get("forgotten", []):
            _emit("forgotten", f"🌫️ {f['summary']}... ({f['reason']})")
        if events.get("resonance_letter"):
            _emit("resonance", "✦ 五维共振达成！查看回信...")
        # 节奏异常
        rhythm = events.get("rhythm")
        if rhythm and rhythm.get("signal") not in ("normal", "cold_start"):
            _emit("rhythm", f"🎵 {rhythm['detail']}")
        # Frustration 跳变
        if events.get("frustration_score", 0) >= 0.5:
            _emit("frustration", f"🔥 挫败感: {events['frustration_score']}")
        # Cap at 30
        if len(self._recent_events) > 30:
            self._recent_events = self._recent_events[-30:]

    def on_feedback(self, positive: bool):
        self.fate.tick_interaction(is_positive=positive)
        self._save_state()

    def on_session_end(self, summary="", keywords=None, tags=None):
        if summary:
            self.time_engine.add_memory(summary, keywords, tags)
        if self.time_engine.total_interactions % 10 == 0:
            self.temperament.take_snapshot()
        self._save_state()

    def get_context(self) -> dict:
        return {
            "relationship_stage": self.fate.stage,
            "temporal_mood": self.time_engine.get_temporal_mood(),
            "verbosity": self.resonance.verbosity_hint,
            "personality": self.temperament.get_effective_personality(),
            "dominant_trait": self.temperament.dominant_trait,
            "personality_card": self.temperament.personality_card,
            "active_mutations": [m.to_dict() for m in self.temperament.active_mutations if m.is_active],
        }

    def export_state(self) -> dict:
        dims = {
            "yuanfen": self.fate.to_dict(),
            "suiyue": self.time_engine.to_dict(),
            "moqi": self.resonance.to_dict(),
            "piqi": self.temperament.to_dict(),
            "jianghu": self.context_web.to_dict(),
        }
        stages = [dims[k]["stage_index"] for k in ["yuanfen", "suiyue", "moqi", "piqi", "jianghu"]]
        progress = sum(stages) / 20
        return {
            "user_id": self.user_id,
            "timestamp": time.time(),
            "datetime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "soul_bond": {
                "progress": round(progress, 3),
                "percentage": round(progress * 100, 1),
                "is_complete": all(s >= 3 for s in stages),
                "stages": stages,
            },
            "dimensions": dims,
            "conflicts": self.conflict.to_dict(),
            "resonance": self.soul_resonance.to_dict(),
            "shadow": self.shadow.to_dict() if self.shadow else {},
            "_events": self._recent_events[-20:],
        }

    def export_json(self, filepath=None) -> str:
        state = self.export_state()
        path = filepath or os.path.join(self.state_dir, f"{self.user_id}_soul.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return path

    def _quick_state(self):
        return {
            "yuanfen": self.fate.to_dict(),
            "suiyue": self.time_engine.to_dict(),
            "moqi": self.resonance.to_dict(),
            "piqi": self.temperament.to_dict(),
            "jianghu": self.context_web.to_dict(),
        }

    def _save_state(self):
        """Persist full engine state — serialize format, NOT display format"""
        state = {
            "_version": 2,
            "user_id": self.user_id,
            "timestamp": time.time(),
            "fate": self.fate._serialize(),
            "time_engine": self.time_engine._serialize(),
            "resonance_engine": self.resonance._serialize(),
            "temperament": self.temperament._serialize(),
            "context_web": self.context_web._serialize(),
            "conflict": self.conflict._serialize(),
            "soul_resonance": self.soul_resonance._serialize(),
            "_recent_msgs": self._recent_msgs,
            "_consecutive_debug": self._consecutive_debug,
            "_recent_events": self._recent_events[-30:],
            "_msg_timestamps": self._msg_timestamps,
            "_frustration_score": self._frustration_score,
            "shadow": self.shadow.to_dict() if self.shadow else {},
        }
        path = os.path.join(self.state_dir, f"{self.user_id}_soul.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

    def _load_state(self):
        path = os.path.join(self.state_dir, f"{self.user_id}_soul.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        if data.get("_version", 1) >= 2:
            self._load_v2(data)
        else:
            self._load_v1(data)

    def _load_v2(self, data: dict):
        """Load from v2 serialization format — full state round-trip"""
        # 缘分
        fate = data.get("fate", {})
        self.fate.stage_index = fate.get("stage_index", 0)
        self.fate.interaction_count = fate.get("interaction_count", 0)
        self.fate.positive_count = fate.get("positive_count", 0)
        self.fate.negative_count = fate.get("negative_count", 0)
        self.fate.milestone_count = fate.get("milestone_count", 0)
        self.fate.last_interaction_ts = fate.get("last_interaction_ts", time.time())
        self.fate.comeback_flag = fate.get("comeback_flag", False)

        # 岁月
        te = data.get("time_engine", {})
        self.time_engine.milestones = [
            Milestone(m["type"], m["timestamp"], m["context_snippet"], m["emotion_tag"])
            for m in te.get("milestones", [])
        ]
        self.time_engine._seen_types = set(te.get("_seen_types", []))
        self.time_engine.memory_pool = te.get("memory_pool", [])
        self.time_engine.forgotten_pool = te.get("forgotten_pool", [])
        self.time_engine.streak_days = te.get("streak_days", 0)
        self.time_engine.total_interactions = te.get("total_interactions", 0)
        self.time_engine.first_interaction_ts = te.get("first_interaction_ts")

        # 默契
        res = data.get("resonance_engine", {})
        self.resonance.intent_history = res.get("intent_history", [])
        self.resonance.intent_freq = res.get("intent_freq", {})
        self.resonance.predictions = res.get("predictions", [])
        self.resonance.resonance_score = res.get("resonance_score", 0.0)
        self.resonance._cold_start_count = res.get("_cold_start_count", 0)
        self.resonance._last_prediction = res.get("_last_prediction")
        self.resonance.awkward_moments = [
            AwkwardMoment(a["predicted"], a["actual"], a["timestamp"], a["quip"])
            for a in res.get("awkward_moments", [])
        ]
        self.resonance._prev_score = res.get("_prev_score", 0.0)
        self.resonance._consecutive_misses = res.get("_consecutive_misses", 0)
        self.resonance._score_history = res.get("_score_history", [])

        # 脾气（用 fate.personality_seed 作为权威 seed，覆盖 JSON 旧值）
        tmp = data.get("temperament", {})
        self.temperament.seed = self.fate.personality_seed[:]
        self.temperament.current = self.fate.personality_seed[:]
        if tmp.get("current") and len(tmp["current"]) == 4:
            # 只有当 JSON 的 seed 与当前 fate seed 一致时才恢复 current（说明是同一套配置下的 drift）
            json_seed = tmp.get("seed", [])
            if json_seed == self.fate.personality_seed:
                self.temperament.current = tmp["current"][:]
        self.temperament.drift_history = tmp.get("drift_history", [])
        self.temperament.snapshots = tmp.get("snapshots", [])
        self.temperament.active_mutations = [
            MutationEvent(**m) for m in tmp.get("active_mutations", [])
        ]
        self.temperament.past_mutations = [
            MutationEvent(**m) for m in tmp.get("past_mutations", [])
        ]

        # 江湖
        cw = data.get("context_web", {})
        for name, edata in cw.get("entities", {}).items():
            self.context_web.entities[name] = Entity(
                name=name, type=edata["type"],
                first_seen=edata.get("first_seen", time.time()),
                last_seen=edata.get("last_seen", time.time()),
                mention_count=edata.get("mention_count", 1),
                attributes=edata.get("attributes", {}),
            )
        self.context_web.relations = cw.get("relations", [])
        self.context_web.rumors = [
            Rumor(
                entity_name=r["entity_name"], speculation=r["speculation"],
                evidence=r.get("evidence", []), confidence=r.get("confidence", 0.5),
                created_at=r.get("created_at", time.time()),
                debunked=r.get("debunked", False), debunked_by=r.get("debunked_by", ""),
            )
            for r in cw.get("rumors", [])
        ]
        self.context_web._entity_context = cw.get("_entity_context", {})

        # 冲突
        conf = data.get("conflict", {})
        self.conflict.conflict_log = conf.get("conflict_log", [])
        self.conflict._shown_ids = set(conf.get("_shown_ids", []))

        # 共振
        sr = data.get("soul_resonance", {})
        self.soul_resonance.triggered = sr.get("triggered", False)
        self.soul_resonance.letter = sr.get("letter")
        self.soul_resonance.triggered_at = sr.get("triggered_at")

        # Shadow
        shadow_data = data.get("shadow", {})
        if self.shadow and shadow_data.get("energy"):
            energy = shadow_data["energy"]
            if len(energy) == len(self.shadow.energy):
                self.shadow.energy = energy[:]
            self.shadow.total_accumulations = shadow_data.get("total_accumulations", 0)
            self.shadow.total_leaks = shadow_data.get("total_leaks", 0)

        # 顶层状态
        self._recent_msgs = data.get("_recent_msgs", [])
        self._consecutive_debug = data.get("_consecutive_debug", 0)
        self._recent_events = data.get("_recent_events", [])
        self._msg_timestamps = data.get("_msg_timestamps", [])
        self._frustration_score = data.get("_frustration_score", 0.0)

    def _load_v1(self, data: dict):
        """Backward-compatible load from v1 display format (lossy)"""
        dims = data.get("dimensions", {})
        if not dims:
            return

        # 缘分 (v1: no positive_count/negative_count)
        yf = dims.get("yuanfen", {})
        self.fate.stage_index = yf.get("stage_index", 0)
        self.fate.interaction_count = yf.get("interaction_count", 0)
        self.fate.milestone_count = yf.get("milestone_count", 0)
        self.fate.last_interaction_ts = data.get("timestamp", time.time())

        # 岁月 (v1: only last 10 milestones, no memory_pool)
        sy = dims.get("suiyue", {})
        self.time_engine.total_interactions = self.fate.interaction_count
        for ms_data in sy.get("milestones", []):
            ms = Milestone(ms_data["type"], ms_data.get("timestamp", 0),
                           ms_data.get("context_snippet", ""), ms_data.get("emotion_tag", "neutral"))
            self.time_engine.milestones.append(ms)
            self.time_engine._seen_types.add(ms_data["type"])
        if self.time_engine.milestones:
            self.time_engine.first_interaction_ts = self.time_engine.milestones[0].timestamp

        # 默契 (v1: no intent_history/intent_freq/predictions)
        mq = dims.get("moqi", {})
        self.resonance.resonance_score = mq.get("resonance_score", 0)
        self.resonance._cold_start_count = max(10, self.fate.interaction_count)
        self.resonance._consecutive_misses = mq.get("consecutive_misses", 0)

        # 脾气 (v1: no seed/drift_history/snapshots/mutations)
        pq = dims.get("piqi", {})
        if pq.get("current") and len(pq["current"]) == 4:
            self.temperament.current = pq["current"][:]

        # 江湖 (v1: only top 10 entities, no rumors/context)
        jh = dims.get("jianghu", {})
        for ent_data in jh.get("top_entities", []):
            name = ent_data.get("name", "")
            if name:
                self.context_web._upsert_entity(name, ent_data.get("type", "UNKNOWN"))
                ent = self.context_web.entities.get(name)
                if ent:
                    ent.mention_count = ent_data.get("mention_count", 1)

        # 事件流
        self._recent_events = data.get("_events", [])

        # 冲突 (v1: only last 5)
        conflicts = data.get("conflicts", {})
        self.conflict.conflict_log = conflicts.get("recent", [])

        # 共振
        res = data.get("resonance", {})
        self.soul_resonance.triggered = res.get("triggered", False)
        self.soul_resonance.letter = res.get("letter")


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    import sys
    # Force UTF-8 on Windows
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("  TaijiOS v2 — 有缺陷的灵魂")
    print("=" * 60)

    soul = SoulEngine(user_id="v2_demo")

    # 展示体质
    c = soul.fate.constitution
    print(f"  Constitution: forget={c['forgetting_rate']:.2f} mutation={c['mutation_sensitivity']:.2f} resonance={c['resonance_threshold']:.2f}")
    print()

    story = [
        ("你好啊", "greeting"),
        ("帮我看看这段代码", "code_help"),
        ("这个bug怎么修", "code_help"),
        ("还是报错", "code_help"),
        ("又报错了...", "code_help"),
        ("第五次了救命", "code_help"),
        ("哈哈终于好了你太逗了", "chat"),
        ("我同事老张又加班了", "vent"),
        ("老张又加班了 真服了", "vent"),
        ("老张又又又加班了", "vent"),
        ("谢谢你，真的很贴心", "chat"),
        ("老张其实是被逼的不是自愿", "chat"),
        # Frustration 测试
        ("烦死了什么鬼东西", "vent"),
        ("崩溃了太烂了", "vent"),
        ("算了不想干了", "vent"),
        # 恢复
        ("终于搞定了太棒了", "chat"),
        ("帮我写个脚本", "code_help"),
        ("你写得好犀利一针见血", "chat"),
        ("笑死了太搞怪了", "chat"),
    ]

    for msg, intent in story:
        events = soul.on_message(msg, intent=intent)
        ctx = soul.get_context()

        print(f"\n> {msg}")
        line = f"  {soul.fate.stage_label} | {ctx['personality_card']} | {ctx['verbosity']}"
        # 节奏 + frustration
        rhythm = events.get("rhythm", {})
        if rhythm.get("signal") not in ("normal", "cold_start", None):
            line += f" | rhythm:{rhythm['signal']}"
        frust = events.get("frustration_score", 0)
        if frust >= 0.3:
            line += f" | frust:{frust}"
        print(line)

        if events["milestone"]:
            print(f"  [milestone] {events['milestone']['type']}")
        if events["awkward_moment"]:
            print(f"  [awkward] {events['awkward_moment']['quip']}")
        for m in events["mutations"]:
            print(f"  [mutation] {m['name']}")
        for mono in events["monologues"]:
            print(f"  [monologue] {mono}")
        for r in events["rumors"]["new_rumors"]:
            print(f"  [rumor] {r['speculation']} ({r['confidence']})")
        for r in events["rumors"]["debunked"]:
            print(f"  [debunked] {r['speculation']}")

    soul.on_session_end("v2 demo story", ["debug", "老张"], ["技术", "emotion"])

    state = soul.export_state()
    print(f"\n{'=' * 60}")
    print(f"  Bond: {state['soul_bond']['percentage']}%")
    print(f"  Conflicts: {state['conflicts']['total_conflicts']}")
    print(f"  Rumors: {state['dimensions']['jianghu']['rumors']['total']}")
    print(f"  Events: {len(state['_events'])}")
    print(f"  Forgotten: {state['dimensions']['suiyue']['forgotten_count']}")
    eff = state['dimensions']['piqi']['effective']
    cur = state['dimensions']['piqi']['current']
    print(f"  Current:   {cur}")
    print(f"  Effective: {eff}")
    print(f"  Ratio: pos={soul.fate.positive_count} neg={soul.fate.negative_count} → {soul.fate.positive_ratio:.3f}")
    print("=" * 60)
