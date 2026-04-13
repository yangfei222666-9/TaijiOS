"""
ReinforcementLoop — 实时强化学习

每条反馈立刻调整策略权重，下一条消息就不一样。
不等批量分析，不等EvolutionScheduler。

策略维度：tone_warmth / detail_level / humor / empathy / proactivity / encouragement
"""

import time
import json
import os
import math
import logging
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class StrategyWeight:
    """一个策略维度的权重"""
    name: str
    weight: float = 0.5
    positive_count: int = 0
    negative_count: int = 0
    last_updated: float = field(default_factory=time.time)

    @property
    def total(self) -> int:
        return self.positive_count + self.negative_count

    @property
    def win_rate(self) -> float:
        return self.positive_count / max(self.total, 1)

    def reinforce(self, alpha: float = 0.05):
        self.positive_count += 1
        self.weight = min(1.0, self.weight + alpha)
        self.last_updated = time.time()

    def weaken(self, beta: float = 0.08):
        self.negative_count += 1
        self.weight = max(0.0, self.weight - beta)
        self.last_updated = time.time()

    def decay(self, rate: float = 0.01):
        if self.weight > 0.5:
            self.weight -= rate
        elif self.weight < 0.5:
            self.weight += rate

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "weight": round(self.weight, 3),
            "win_rate": round(self.win_rate, 3),
            "positive": self.positive_count,
            "negative": self.negative_count,
            "total": self.total,
        }


class ReinforcementLoop:
    """
    实时强化学习引擎。
    每次反馈立刻调整策略权重，SoulAwareCodeAssist读取权重调整prompt。
    """

    ALPHA = 0.05
    BETA = 0.08
    DECAY_RATE = 0.005
    DECAY_INTERVAL = 600

    DIMENSIONS = [
        "tone_warmth", "detail_level", "humor",
        "empathy", "proactivity", "encouragement",
    ]

    def __init__(self, state_path: str = None):
        self.state_path = state_path or "rl_state.json"
        self.weights: dict[str, StrategyWeight] = {}
        self._last_decay = time.time()
        self._feedback_history: list[dict] = []
        self._init_weights()
        self._load()

    def _init_weights(self):
        for dim in self.DIMENSIONS:
            if dim not in self.weights:
                self.weights[dim] = StrategyWeight(name=dim)

    # ────────────────────────────────────────────
    # 核心：反馈 → 立刻调整
    # ────────────────────────────────────────────

    def feedback(self, positive: bool, snapshot: dict = None,
                  detail: str = "", context: dict = None):
        record = {
            "positive": positive, "detail": detail,
            "timestamp": time.time(),
            "snapshot": snapshot or {}, "context": context or {},
        }
        self._feedback_history.append(record)
        if len(self._feedback_history) > 500:
            self._feedback_history.pop(0)

        targeted = self._parse_feedback_detail(detail)
        if targeted:
            for dim, direction in targeted.items():
                if dim in self.weights:
                    if direction == "up":
                        self.weights[dim].reinforce(self.ALPHA * 2)
                    elif direction == "down":
                        self.weights[dim].weaken(self.BETA * 2)
        else:
            for dim, w in self.weights.items():
                if positive:
                    w.reinforce(self.ALPHA)
                else:
                    w.weaken(self.BETA)

        now = time.time()
        if now - self._last_decay > self.DECAY_INTERVAL:
            self._decay_all()
            self._last_decay = now
        self._save()

    def _parse_feedback_detail(self, detail: str) -> dict[str, str]:
        if not detail:
            return {}
        detail_lower = detail.lower()
        adjustments = {}
        if any(w in detail_lower for w in ["太长", "太啰嗦", "简短", "精简", "废话"]):
            adjustments["detail_level"] = "down"
        elif any(w in detail_lower for w in ["不够详细", "太简单", "说清楚", "展开"]):
            adjustments["detail_level"] = "up"
        if any(w in detail_lower for w in ["太冷", "冷冰冰", "不够温暖", "机器人"]):
            adjustments["tone_warmth"] = "up"
            adjustments["empathy"] = "up"
        elif any(w in detail_lower for w in ["太腻", "太甜", "正经", "别撒娇"]):
            adjustments["tone_warmth"] = "down"
        if any(w in detail_lower for w in ["别开玩笑", "正经点", "不好笑", "严肃"]):
            adjustments["humor"] = "down"
        elif any(w in detail_lower for w in ["无聊", "死板", "有趣一点"]):
            adjustments["humor"] = "up"
        if any(w in detail_lower for w in ["别问了", "太多问题", "不用建议"]):
            adjustments["proactivity"] = "down"
        elif any(w in detail_lower for w in ["主动一点", "你怎么看", "你的建议"]):
            adjustments["proactivity"] = "up"
        if any(w in detail_lower for w in ["别灌鸡汤", "不用鼓励", "别拍马屁"]):
            adjustments["encouragement"] = "down"
        if any(w in detail_lower for w in ["理解我", "懂我", "关心"]):
            adjustments["empathy"] = "up"
        return adjustments

    # ────────────────────────────────────────────
    # 隐式反馈推断
    # ────────────────────────────────────────────

    def infer_feedback(self, current_message: str,
                        previous_reply: str = "") -> Optional[bool]:
        msg = current_message.lower()
        if any(w in msg for w in [
            "谢谢", "好的", "明白了", "解决了", "搞定了", "牛",
            "可以", "不错", "厉害", "完美", "nice", "thanks",
            "对的", "就是这样", "好了",
        ]):
            return True
        if any(w in msg for w in [
            "不对", "不行", "还是报错", "没用", "不是这样",
            "错了", "不是我要的", "又错", "看错了",
            "别", "不要", "停", "算了换个方式",
        ]):
            return False
        if any(w in msg for w in ["烦", "无语", "什么鬼", "受不了", "垃圾"]):
            return False
        return None

    # ────────────────────────────────────────────
    # 输出：权重 → prompt 调整
    # ────────────────────────────────────────────

    def get_prompt_modifiers(self) -> str:
        modifiers = []
        w = self.weights["tone_warmth"].weight
        if w > 0.7:
            modifiers.append("语气要温暖亲切。多用「我们」而不是「你」。")
        elif w < 0.3:
            modifiers.append("语气简洁直接。不需要额外的温暖表达。")
        w = self.weights["detail_level"].weight
        if w > 0.7:
            modifiers.append("回复要详细。解释清楚每一步的原因。")
        elif w < 0.3:
            modifiers.append("回复要精简。只给关键结论和代码，省略解释。")
        w = self.weights["humor"].weight
        if w > 0.7:
            modifiers.append("可以适度幽默。用轻松的方式解释。")
        elif w < 0.3:
            modifiers.append("保持严肃专业。不要开玩笑。")
        w = self.weights["empathy"].weight
        if w > 0.7:
            modifiers.append("多表达理解和共情。先回应情绪再解决问题。")
        elif w < 0.3:
            modifiers.append("直接解决问题。不需要情绪回应。")
        w = self.weights["proactivity"].weight
        if w > 0.7:
            modifiers.append("主动提建议和延伸思路。不要只回答被问的。")
        elif w < 0.3:
            modifiers.append("只回答被问的问题。不要主动建议。")
        w = self.weights["encouragement"].weight
        if w > 0.7:
            modifiers.append("适时鼓励。完成时说好，困难时说加油。")
        elif w < 0.3:
            modifiers.append("不要鼓励。用户不需要安慰需要答案。")
        if not modifiers:
            return ""
        return "[强化学习调整] 以下基于用户反馈的实时偏好：\n" + "\n".join(f"- {m}" for m in modifiers)

    def take_snapshot(self) -> dict:
        return {dim: round(w.weight, 3) for dim, w in self.weights.items()}

    def _decay_all(self):
        for w in self.weights.values():
            w.decay(self.DECAY_RATE)

    def _save(self):
        try:
            data = {
                "weights": {k: v.to_dict() for k, v in self.weights.items()},
                "feedback_count": len(self._feedback_history),
                "last_updated": time.time(),
            }
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Failed to save RL state to %s: %s", self.state_path, e)

    def _load(self):
        if not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for dim, wd in data.get("weights", {}).items():
                if dim in self.weights:
                    self.weights[dim].weight = wd.get("weight", 0.5)
                    self.weights[dim].positive_count = wd.get("positive", 0)
                    self.weights[dim].negative_count = wd.get("negative", 0)
        except Exception as e:
            logger.warning("Failed to load RL state from %s: %s", self.state_path, e)

    def to_dict(self) -> dict:
        return {
            "weights": {k: v.to_dict() for k, v in self.weights.items()},
            "total_feedback": sum(w.total for w in self.weights.values()) // len(self.weights),
            "feedback_history_size": len(self._feedback_history),
        }

    def get_weight_summary(self) -> str:
        lines = ["当前策略偏好："]
        for dim, w in self.weights.items():
            bar_len = int(w.weight * 20)
            bar = "#" * bar_len + "." * (20 - bar_len)
            dim_cn = {
                "tone_warmth": "温暖度", "detail_level": "详细度",
                "humor": "幽默感", "empathy": "共情度",
                "proactivity": "主动性", "encouragement": "鼓励",
            }.get(dim, dim)
            lines.append(f"  {dim_cn:4s} [{bar}] {w.weight:.2f} ({w.win_rate:.0%}胜率, {w.total}次)")
        return "\n".join(lines)


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  ReinforcementLoop — 实时强化学习")
    print("  每条反馈立刻改变下一条回复")
    print("=" * 60)

    rl = ReinforcementLoop(state_path="/tmp/rl_test.json")

    print("\n── 模拟10轮对话 ──")
    scenarios = [
        (True,  "", "好的解决了"),
        (False, "回复太长了", "太啰嗦"),
        (False, "回复太长了", "能不能简短点"),
        (True,  "", "这次好多了"),
        (False, "语气太冷", "你能不能温暖一点"),
        (True,  "", "嗯这次舒服多了"),
        (False, "别开玩笑了", "正经点"),
        (True,  "", "谢谢"),
        (True,  "", "不错"),
        (False, "不是我要的", "看错了"),
    ]
    for i, (positive, detail, msg) in enumerate(scenarios, 1):
        implicit = rl.infer_feedback(msg)
        actual_positive = implicit if implicit is not None else positive
        snapshot = rl.take_snapshot()
        rl.feedback(positive=actual_positive, snapshot=snapshot, detail=detail)
        mark = "+" if actual_positive else "-"
        detail_str = f" ({detail})" if detail else ""
        print(f"  #{i:2d} {mark} [{msg}]{detail_str}")
        dl = rl.weights["detail_level"]
        tw = rl.weights["tone_warmth"]
        hm = rl.weights["humor"]
        print(f"      详细={dl.weight:.2f} 温暖={tw.weight:.2f} 幽默={hm.weight:.2f}")

    print(f"\n{rl.get_weight_summary()}")

    print(f"\n── prompt调整 ──")
    modifiers = rl.get_prompt_modifiers()
    if modifiers:
        print(modifiers)
    else:
        print("  （权重在中间区域，无特殊调整）")

    print(f"\n── 隐式反馈推断 ──")
    for msg in ["谢谢搞定了", "不对还是报错", "什么鬼", "嗯", "帮我看另一个问题"]:
        result = rl.infer_feedback(msg)
        mark = "+" if result is True else "-" if result is False else "?"
        print(f"  {mark} [{msg}] -> {result}")

    if os.path.exists("/tmp/rl_test.json"):
        os.remove("/tmp/rl_test.json")

    print(f"\n{'=' * 60}")
    print("  每条反馈立刻生效。这才是进化。")
    print(f"{'=' * 60}")
