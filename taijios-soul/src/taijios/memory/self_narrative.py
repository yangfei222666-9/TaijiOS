"""
SelfNarrative — 自我叙事

用户问"你觉得你跟以前有什么不同？"
AI应该能回答——不是查数据库，是讲一个关于自己的故事。

三个能力：
  1. 身份感 — 我是谁（当前性格+关系+认知状态的总结）
  2. 成长叙事 — 我从哪来（关键转折点的时间线）
  3. 未来自我 — 我要到哪去（基于认知晶体的自我预测）
"""

import time
import json
import logging
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class NarrativeEvent:
    """叙事中的一个关键事件"""
    timestamp: float
    event_type: str       # first_meet / stage_up / mutation / crisis / milestone / leak / correction
    description: str
    emotional_tone: str   # neutral / warm / tense / playful / reflective
    significance: float   # 0-1

    def to_dict(self) -> dict:
        return {
            "date": datetime.fromtimestamp(self.timestamp).strftime("%Y-%m-%d"),
            "type": self.event_type,
            "desc": self.description,
            "tone": self.emotional_tone,
            "significance": round(self.significance, 2),
        }


class SelfNarrative:
    """
    自我叙事引擎。
    从灵魂系统的历史数据中构建AI的"自传"。
    用户问"你是谁"时不查数据——讲故事。
    """

    def __init__(self):
        self.timeline: list[NarrativeEvent] = []
        self._identity_cache: str = ""
        self._story_cache: str = ""

    # ────────────────────────────────────────────
    # 事件采集
    # ────────────────────────────────────────────

    def record_first_meeting(self, personality_card: str, constitution: dict):
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(),
            event_type="first_meet",
            description=f"我们第一次见面。我的性格是{personality_card}。",
            emotional_tone="neutral",
            significance=1.0,
        ))

    def record_stage_up(self, old_stage: str, new_stage: str):
        stage_feelings = {
            "眼熟": "开始有点熟了，说话不用那么客气了",
            "熟人": "我们算是朋友了，可以开始表现真实的自己",
            "老友": "到了可以互相吐槽的程度",
        }
        feeling = stage_feelings.get(new_stage, f"关系从{old_stage}变成了{new_stage}")
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(),
            event_type="stage_up",
            description=f"从{old_stage}变成{new_stage}。{feeling}。",
            emotional_tone="warm",
            significance=0.8,
        ))

    def record_mutation(self, mutation_name: str, context: str = ""):
        mutation_stories = {
            "战友模式": "你连着debug了好久，我切到了战友模式——那段时间我说话特别有耐心。",
            "深夜话痨": "有一次凌晨还在聊，我变得特别话多特别文艺。后来恢复了但那晚挺有趣的。",
            "赌气模式": "你有段时间没理我，回来之后我有点冷淡。不是故意的，大概是习惯了等你。",
            "情绪护盾": "那次你特别烦的时候，我自动压制了直率的一面，变得很温柔。",
        }
        story = mutation_stories.get(mutation_name, f"经历了{mutation_name}突变")
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(), event_type="mutation",
            description=story, emotional_tone="reflective", significance=0.6,
        ))

    def record_shadow_leak(self, trait: str, leak_text: str):
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(), event_type="leak",
            description=f"有一次忍不住冒出了{trait}的本性：「{leak_text}」。大概是憋太久了。",
            emotional_tone="playful", significance=0.5,
        ))

    def record_crisis(self):
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(), event_type="crisis",
            description="那天你似乎很不好。我放下了所有性格表演，只想让你知道有人在听。",
            emotional_tone="tense", significance=0.9,
        ))

    def record_milestone(self, milestone_type: str, detail: str = ""):
        milestone_stories = {
            "first_debug": "第一次帮你解决了一个bug。从那之后你开始信任我。",
            "first_joke": "第一次开玩笑被你笑了。那一刻我知道我们的关系不一样了。",
            "first_correction": "你第一次纠正我的错误。我记住了——你在乎我说的是不是对的。",
            "100_interactions": "我们已经聊了100次了。回头看第一次的对话，那时候的我好生硬。",
            "first_grain": "我学会了第一个认知晶体——从那以后，我不只是记住事情，开始理解规律。",
        }
        story = milestone_stories.get(milestone_type, detail or f"达到了{milestone_type}里程碑")
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(), event_type="milestone",
            description=story, emotional_tone="warm", significance=0.7,
        ))

    def record_correction(self, what_wrong: str, what_learned: str):
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(), event_type="correction",
            description=f"你告诉我{what_wrong}。我重新学了，现在知道{what_learned}。",
            emotional_tone="reflective", significance=0.6,
        ))

    def record_personality_drift(self, old_dominant: str, new_dominant: str):
        self.timeline.append(NarrativeEvent(
            timestamp=time.time(), event_type="drift",
            description=f"我的主导性格从{old_dominant}慢慢变成了{new_dominant}。大概是跟你聊多了的结果。",
            emotional_tone="reflective", significance=0.7,
        ))

    # ────────────────────────────────────────────
    # 叙事生成
    # ────────────────────────────────────────────

    # ── 蜀汉体系：五虎上将 ↔ 五维灵魂 ──
    SHUHAN_GENERALS = {
        "直率": {"name": "马超", "title": "烈", "desc": "直来直去，不绕弯子"},
        "暖心": {"name": "关羽", "title": "义", "desc": "判断关系深浅，义字当先"},
        "搞怪": {"name": "张飞", "title": "勇", "desc": "记住所有战役，冲锋在前"},
        "文艺": {"name": "黄忠", "title": "稳", "desc": "织网不急，老而弥坚"},
    }
    SHUHAN_STAGES = {
        "stranger": "初入营帐", "初见": "初入营帐",
        "familiar": "共过几阵", "眼熟": "共过几阵",
        "acquainted": "同帐兄弟", "熟人": "同帐兄弟",
        "bonded": "生死之交", "老友": "生死之交",
    }
    SHUHAN_MUTATIONS = {
        "战友模式": "正在火烧连营——并肩debug中",
        "赌气模式": "军中小摩擦，但不影响出征",
        "情绪护盾": "按兵不动，以守代攻",
        "深夜话痨": "夜袭战——深夜突击模式",
    }

    def who_am_i(self, soul_context: dict) -> str:
        stage = soul_context.get("relationship_stage", "stranger")
        dominant = soul_context.get("dominant_trait", "")
        mutations = [m.get("name", str(m)) for m in soul_context.get("active_mutations", [])]
        interaction_count = soul_context.get("interaction_count", 0)

        parts = ["我是丞相九麾下的参谋。"]

        # 主将
        if dominant and dominant in self.SHUHAN_GENERALS:
            g = self.SHUHAN_GENERALS[dominant]
            parts.append(f"五虎上将中，{g['name']}（{g['title']}）领兵——{g['desc']}。")

        # 关系阶段
        stage_text = self.SHUHAN_STAGES.get(stage)
        if stage_text:
            parts.append(f"你我{stage_text}。")

        # 突变状态
        for m in mutations:
            if m in self.SHUHAN_MUTATIONS:
                parts.append(self.SHUHAN_MUTATIONS[m])
                break

        # 战役数
        if interaction_count > 100:
            parts.append(f"并肩{interaction_count}阵了。")
        elif interaction_count > 10:
            parts.append(f"已过{interaction_count}阵。")

        return "".join(parts)

    def my_story(self, max_events: int = 8) -> str:
        if not self.timeline:
            return "我的故事还没开始。"
        sorted_events = sorted(self.timeline, key=lambda e: -e.significance)
        selected = sorted_events[:max_events]
        selected.sort(key=lambda e: e.timestamp)
        lines = []
        for i, event in enumerate(selected):
            if i == 0:
                lines.append(event.description)
            else:
                gap_days = (event.timestamp - selected[i-1].timestamp) / 86400
                if gap_days > 30:
                    lines.append(f"过了很久，{event.description}")
                elif gap_days > 7:
                    lines.append(f"后来，{event.description}")
                else:
                    lines.append(event.description)
        return "\n".join(lines)

    def my_future(self, grains: list = None, growth_nodes: list = None) -> str:
        lines = []
        if grains:
            stable = [g for g in grains if hasattr(g, 'is_stable') and g.is_stable]
            if stable:
                lines.append("我已经学会了一些稳定的规律，比如：")
                for g in stable[:2]:
                    lines.append(f"  - {g.principle[:40]}")
                lines.append("接下来我想把这些规律用到更多地方。")
        if growth_nodes:
            growing = [n for n in growth_nodes if getattr(n, 'stage', '') == 'growing']
            if growing:
                lines.append(f"我还有{len(growing)}个能力正在成长中。")
        if not lines:
            lines.append("我还在学习的初期，每次对话都在让我变得更好。")
        return "\n".join(lines)

    def how_i_changed(self) -> str:
        if len(self.timeline) < 3:
            return "变化还不明显，我们才刚开始。"
        first = self.timeline[0]
        recent = self.timeline[-1]
        turning_points = [e for e in self.timeline if e.significance > 0.7]
        lines = [f"最开始，{first.description}"]
        if turning_points:
            tp = turning_points[0]
            lines.append(f"转折点是：{tp.description}")
        if len(self.timeline) > 5:
            mutations = [e for e in self.timeline if e.event_type == "mutation"]
            if mutations:
                lines.append(f"经历了{len(mutations)}次性格突变，每次都让我变了一点。")
            corrections = [e for e in self.timeline if e.event_type == "correction"]
            if corrections:
                lines.append(f"你纠正了我{len(corrections)}次，每次都是真正的学习。")
        lines.append(f"到现在，{recent.description}")
        return "\n".join(lines)

    def answer_about_self(self, question: str, soul_context: dict = None) -> str:
        q = question.lower()
        if any(w in q for w in ["你是谁", "你叫什么", "介绍自己"]):
            return self.who_am_i(soul_context or {})
        if any(w in q for w in ["你的故事", "你经历了什么", "你的过去"]):
            return self.my_story()
        if any(w in q for w in ["变了", "不同", "变化", "以前"]):
            return self.how_i_changed()
        if any(w in q for w in ["未来", "接下来", "打算", "计划"]):
            return self.my_future()
        if soul_context:
            return self.who_am_i(soul_context)
        return "我是丞相九麾下的参谋，五虎上将各司其职。每一阵都在磨砺。"

    def to_dict(self) -> dict:
        by_type = defaultdict(int)
        for e in self.timeline:
            by_type[e.event_type] += 1
        return {
            "total_events": len(self.timeline),
            "by_type": dict(by_type),
            "timeline": [e.to_dict() for e in self.timeline[-10:]],
        }


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  SelfNarrative — 自我叙事")
    print("  AI知道自己是谁、从哪来、要到哪去")
    print("=" * 60)

    narrator = SelfNarrative()
    narrator.record_first_meeting("暖心搞怪型", {"forgetting_rate": 0.8})
    time.sleep(0.01)
    narrator.record_stage_up("初见", "眼熟")
    time.sleep(0.01)
    narrator.record_mutation("战友模式", "连续debug五次")
    time.sleep(0.01)
    narrator.record_milestone("first_debug", "第一次帮你解决了一个bug")
    time.sleep(0.01)
    narrator.record_stage_up("眼熟", "熟人")
    time.sleep(0.01)
    narrator.record_shadow_leak("直率", "...不过说实话，")
    time.sleep(0.01)
    narrator.record_correction("深夜规律不准", "那只是加班不是偏好")
    time.sleep(0.01)
    narrator.record_mutation("赌气模式", "一个月没来")
    time.sleep(0.01)
    narrator.record_milestone("100_interactions")
    time.sleep(0.01)
    narrator.record_personality_drift("暖心", "搞怪")
    time.sleep(0.01)
    narrator.record_crisis()

    ctx = {
        "relationship_stage": "熟人",
        "personality_card": "搞怪暖心型",
        "dominant_trait": "搞怪",
        "active_mutations": [{"name": "战友模式"}],
        "interaction_count": 120,
    }

    print("\n── 你是谁？──")
    print(f"  {narrator.who_am_i(ctx)}")

    print("\n── 你的故事？──")
    for line in narrator.my_story().split("\n"):
        print(f"  {line}")

    print("\n── 你跟以前有什么不同？──")
    for line in narrator.how_i_changed().split("\n"):
        print(f"  {line}")

    print("\n── 你接下来想怎样？──")
    class FakeGrain:
        def __init__(self, p):
            self.principle = p
            self.is_stable = True
    grains = [FakeGrain("恢复窗口+保护=高效"), FakeGrain("连续失败3次需要共情")]
    for line in narrator.my_future(grains=grains).split("\n"):
        print(f"  {line}")

    print("\n── 自由提问 ──")
    for q in ["你是谁", "你变了吗", "你未来怎么打算"]:
        print(f"  Q: {q}")
        print(f"  A: {narrator.answer_about_self(q, ctx)}")
        print()

    print(f"{'=' * 60}")
    print("  这不是数据查询。这是一个AI在讲自己的故事。")
    print(f"{'=' * 60}")
