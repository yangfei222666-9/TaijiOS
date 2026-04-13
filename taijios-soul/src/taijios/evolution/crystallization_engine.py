"""
CrystallizationEngine — 经验结晶自动化

从 soul_outcomes.jsonl 里识别反复出现的模式，
自动生成经验结晶规则，写入 experience_crystals.json。

结晶条件（三选一）：
1. 负面模式：同类场景连续 N 次 negative → 生成"避免"规则
2. 正面模式：同类场景连续 M 次 positive → 生成"保持"规则
3. 转折模式：从 negative 翻转到 positive → 生成"发现"规则

不依赖 LLM。纯规则引擎，从数据模式到结晶规则的映射。
"""

import json
import os
import time
import hashlib
import logging
import re
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("crystallization")


class CrystallizationEngine:
    # 触发阈值
    NEGATIVE_STREAK_THRESHOLD = 3   # 连续3次负面 → 生成"避免"结晶
    POSITIVE_STREAK_THRESHOLD = 5   # 连续5次正面 → 生成"保持"结晶
    TURNAROUND_WINDOW = 5           # 5条内从负转正 → 生成"发现"结晶
    MIN_OUTCOMES = 10               # 至少10条 outcome 才开始结晶
    MAX_CRYSTALS = 20               # 最多保留20条结晶
    CONFIDENCE_DECAY = 0.01         # 每次结晶周期未被验证的规则衰减

    # 场景分类关键词
    SCENE_KEYWORDS = {
        "debug": ["bug", "报错", "error", "debug", "修复", "fix", "异常", "崩溃"],
        "learning": ["为什么", "原理", "怎么", "学习", "教我", "解释"],
        "venting": ["烦", "崩溃", "受不了", "累", "难受", "焦虑", "搞了"],
        "generating": ["帮我写", "生成", "写一个", "帮我做", "草拟"],
        "chatting": ["你好", "在吗", "聊聊", "无聊", "今天"],
        "summarizing": ["总结", "概括", "规律", "共同点", "区别"],
    }

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.outcomes_path = os.path.join(data_dir, "soul_outcomes.jsonl")
        self.crystals_path = os.path.join(data_dir, "experience_crystals.json")
        self.crystals: list[dict] = []
        self._load_crystals()

    def crystallize(self) -> list[dict]:
        """
        核心方法。扫描 outcomes，识别模式，生成新结晶。
        返回本次新增的结晶列表。
        """
        outcomes = self._load_outcomes()
        if len(outcomes) < self.MIN_OUTCOMES:
            return []

        new_crystals = []

        # 按场景分组
        scene_groups = self._group_by_scene(outcomes)

        for scene, group in scene_groups.items():
            if len(group) < 3:
                continue

            # 检测负面连续模式
            crystal = self._detect_negative_streak(scene, group)
            if crystal and not self._is_duplicate(crystal):
                new_crystals.append(crystal)

            # 检测正面连续模式
            crystal = self._detect_positive_streak(scene, group)
            if crystal and not self._is_duplicate(crystal):
                new_crystals.append(crystal)

            # 检测转折模式
            crystal = self._detect_turnaround(scene, group)
            if crystal and not self._is_duplicate(crystal):
                new_crystals.append(crystal)

        # 全局模式：frustration 相关
        crystal = self._detect_frustration_pattern(outcomes)
        if crystal and not self._is_duplicate(crystal):
            new_crystals.append(crystal)

        # 衰减旧结晶
        self._decay_confidence()

        # 合并
        for c in new_crystals:
            self.crystals.append(c)
            logger.info("[CRYSTAL] new: %s (confidence=%.2f)", c["rule"][:40], c["confidence"])

        # 裁剪
        if len(self.crystals) > self.MAX_CRYSTALS:
            self.crystals.sort(key=lambda c: c.get("confidence", 0), reverse=True)
            removed = self.crystals[self.MAX_CRYSTALS:]
            self.crystals = self.crystals[:self.MAX_CRYSTALS]
            for r in removed:
                logger.info("[CRYSTAL] evicted: %s", r["rule"][:40])

        # 移除过低置信度
        before = len(self.crystals)
        self.crystals = [c for c in self.crystals if c.get("confidence", 0) >= 0.3]
        if len(self.crystals) < before:
            logger.info("[CRYSTAL] removed %d low-confidence crystals", before - len(self.crystals))

        self._save_crystals()
        return new_crystals

    def _classify_scene(self, message: str) -> str:
        """对消息分类到场景"""
        msg = message.lower()
        best_scene, best_score = "other", 0
        for scene, keywords in self.SCENE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in msg)
            if score > best_score:
                best_score = score
                best_scene = scene
        return best_scene

    def _group_by_scene(self, outcomes: list[dict]) -> dict[str, list[dict]]:
        """按场景分组"""
        groups = defaultdict(list)
        for o in outcomes:
            msg = o.get("message", "")
            if not msg:
                continue
            scene = self._classify_scene(msg)
            groups[scene].append(o)
        return dict(groups)

    def _detect_negative_streak(self, scene: str, group: list[dict]) -> Optional[dict]:
        """检测连续负面模式"""
        streak = 0
        max_streak = 0
        streak_samples = []
        for o in group:
            if not o.get("positive", True):
                streak += 1
                if streak > max_streak:
                    max_streak = streak
                    streak_samples = [o]
            else:
                streak = 0

        if max_streak < self.NEGATIVE_STREAK_THRESHOLD:
            return None

        # 分析负面 outcome 的共同特征
        frustrations = [o.get("context", {}).get("frustration", 0) for o in group if not o.get("positive", True)]
        avg_frustration = sum(frustrations) / len(frustrations) if frustrations else 0

        sample_msgs = [o.get("message", "")[:50] for o in group if not o.get("positive", True)][:3]

        rule = self._generate_negative_rule(scene, sample_msgs, avg_frustration)
        return {
            "id": f"auto_{hashlib.md5(rule.encode()).hexdigest()[:8]}",
            "rule": rule,
            "evidence": f"{scene}场景连续{max_streak}次负面反馈，平均挫败度{avg_frustration:.2f}",
            "confidence": min(0.7 + max_streak * 0.05, 0.95),
            "category": "auto_negative",
            "trigger": f"{scene}场景",
            "auto_generated": True,
            "generated_at": time.time(),
            "source_count": len(group),
        }

    def _detect_positive_streak(self, scene: str, group: list[dict]) -> Optional[dict]:
        """检测连续正面模式"""
        streak = 0
        max_streak = 0
        for o in group:
            if o.get("positive", True):
                streak += 1
                if streak > max_streak:
                    max_streak = streak
            else:
                streak = 0

        if max_streak < self.POSITIVE_STREAK_THRESHOLD:
            return None

        sample_msgs = [o.get("message", "")[:50] for o in group if o.get("positive", True)][:3]
        rule = self._generate_positive_rule(scene, sample_msgs)
        return {
            "id": f"auto_{hashlib.md5(rule.encode()).hexdigest()[:8]}",
            "rule": rule,
            "evidence": f"{scene}场景连续{max_streak}次正面反馈",
            "confidence": min(0.6 + max_streak * 0.04, 0.90),
            "category": "auto_positive",
            "trigger": f"{scene}场景",
            "auto_generated": True,
            "generated_at": time.time(),
            "source_count": len(group),
        }

    def _detect_turnaround(self, scene: str, group: list[dict]) -> Optional[dict]:
        """检测从负转正的转折模式"""
        for i in range(len(group) - 1):
            if not group[i].get("positive", True) and group[i + 1].get("positive", True):
                # 找到转折点，看前后 context 差异
                before = group[i]
                after = group[i + 1]
                before_frust = before.get("context", {}).get("frustration", 0)
                after_frust = after.get("context", {}).get("frustration", 0)

                if before_frust > 0.1 and after_frust < before_frust:
                    before_msg = before.get("message", "")[:50]
                    after_msg = after.get("message", "")[:50]
                    rule = self._generate_turnaround_rule(scene, before_msg, after_msg)
                    return {
                        "id": f"auto_{hashlib.md5(rule.encode()).hexdigest()[:8]}",
                        "rule": rule,
                        "evidence": f"{scene}场景从负转正，挫败度{before_frust:.2f}→{after_frust:.2f}",
                        "confidence": 0.70,
                        "category": "auto_turnaround",
                        "trigger": f"{scene}场景挫败度下降时",
                        "auto_generated": True,
                        "generated_at": time.time(),
                        "source_count": 2,
                    }
        return None

    def _detect_frustration_pattern(self, outcomes: list[dict]) -> Optional[dict]:
        """检测全局挫败度模式"""
        high_frust = [o for o in outcomes
                      if o.get("context", {}).get("frustration", 0) > 0.3]
        if len(high_frust) < 3:
            return None

        # 高挫败时的正面率
        pos_count = sum(1 for o in high_frust if o.get("positive", True))
        pos_rate = pos_count / len(high_frust)

        if pos_rate < 0.4:
            rule = "用户挫败度高时，优先共情再解决问题，不要直接给方案"
            return {
                "id": f"auto_{hashlib.md5(rule.encode()).hexdigest()[:8]}",
                "rule": rule,
                "evidence": f"高挫败场景{len(high_frust)}次，正面率仅{pos_rate:.0%}",
                "confidence": 0.80,
                "category": "auto_emotional",
                "trigger": "用户挫败度>0.3时",
                "auto_generated": True,
                "generated_at": time.time(),
                "source_count": len(high_frust),
            }
        return None

    def _generate_negative_rule(self, scene: str, samples: list[str], frustration: float) -> str:
        """从负面模式生成规则"""
        rules = {
            "debug": "debug场景下不要反复追问，直接给排查方向",
            "venting": "用户发泄时不要说教，先共情再行动",
            "generating": "生成内容时不要加解释，直接给结果",
            "learning": "用户问原理时不要给代码，先讲清概念",
            "summarizing": "用户要总结时不要展开，精简回答",
            "chatting": "闲聊时不要太正式，放松语气",
        }
        return rules.get(scene, f"{scene}场景下回复方式需要调整（连续负面反馈）")

    def _generate_positive_rule(self, scene: str, samples: list[str]) -> str:
        """从正面模式生成规则"""
        rules = {
            "debug": "debug场景当前的回复策略有效，保持直接给排查步骤的风格",
            "venting": "情绪场景当前的共情方式有效，保持先回应情绪再给方案",
            "generating": "内容生成当前的输出格式有效，保持完整输出不截断",
            "learning": "学习场景当前的解释方式有效，保持类比+原理的风格",
            "summarizing": "总结场景当前的精简方式有效，保持一句话总结",
            "chatting": "闲聊场景当前的轻松语气有效，保持",
        }
        return rules.get(scene, f"{scene}场景当前回复策略有效，保持当前风格")

    def _generate_turnaround_rule(self, scene: str, before: str, after: str) -> str:
        """从转折模式生成规则"""
        return f"{scene}场景：当用户从不满到满意，关键转折是调整了回复策略"

    def _is_duplicate(self, new_crystal: dict) -> bool:
        """检查是否与已有结晶重复"""
        new_rule = new_crystal["rule"]
        for existing in self.crystals:
            existing_rule = existing["rule"]
            # 字符重叠度
            overlap = len(set(new_rule) & set(existing_rule)) / max(len(set(new_rule) | set(existing_rule)), 1)
            if overlap > 0.7:
                # 重复的情况：提升已有结晶的置信度
                existing["confidence"] = min(1.0, existing["confidence"] + 0.05)
                existing["source_count"] = existing.get("source_count", 1) + new_crystal.get("source_count", 1)
                return True
        return False

    def _decay_confidence(self):
        """对自动生成的结晶做置信度衰减"""
        for c in self.crystals:
            if c.get("auto_generated"):
                c["confidence"] = max(0.0, c["confidence"] - self.CONFIDENCE_DECAY)

    def _load_outcomes(self) -> list[dict]:
        """加载 outcomes"""
        if not os.path.exists(self.outcomes_path):
            return []
        outcomes = []
        try:
            with open(self.outcomes_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        outcomes.append(json.loads(line))
        except Exception as e:
            logger.warning("Load outcomes failed: %s", e)
        return outcomes

    def _load_crystals(self):
        """加载已有结晶"""
        if not os.path.exists(self.crystals_path):
            self.crystals = []
            return
        try:
            with open(self.crystals_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.crystals = data.get("crystals", [])
        except Exception:
            self.crystals = []

    def _save_crystals(self):
        """保存结晶"""
        os.makedirs(os.path.dirname(self.crystals_path) or ".", exist_ok=True)
        data = {
            "version": 2,
            "crystallized_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "source": "auto_crystallization",
            "total_crystals": len(self.crystals),
            "auto_count": sum(1 for c in self.crystals if c.get("auto_generated")),
            "manual_count": sum(1 for c in self.crystals if not c.get("auto_generated")),
            "crystals": self.crystals,
        }
        try:
            with open(self.crystals_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Save crystals failed: %s", e)

    def to_dict(self) -> dict:
        return {
            "total_crystals": len(self.crystals),
            "auto_count": sum(1 for c in self.crystals if c.get("auto_generated")),
            "manual_count": sum(1 for c in self.crystals if not c.get("auto_generated")),
            "crystals": [{"id": c["id"], "rule": c["rule"][:60],
                          "confidence": c.get("confidence", 0),
                          "category": c.get("category", "")}
                         for c in self.crystals],
        }
