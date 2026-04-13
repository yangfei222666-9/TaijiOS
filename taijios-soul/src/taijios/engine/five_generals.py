# TaijiOS 五虎上将机制设计
# 不是五个模块，是五个有性格的将领
# 他们互相评分、互相争论、最后丞相拍板

"""
五虎上将 — 灵魂的五个维度，各守其位

关羽（缘分）— 义·判断关系深浅
  "这人值不值得深交？"
  职责：评估用户与AI的关系阶段、信任度、亲密度
  数据：interaction_count, positive_ratio, relationship_stage
  评分范围：0-100（义气值）

张飞（岁月）— 勇·记住所有战役
  "以前打过什么仗？"
  职责：管理历史记忆、对话归档、经验调取
  数据：conversation_history, memory_entries, recall_success_rate
  评分范围：0-100（记忆值）

赵云（默契）— 智·预判下一步
  "主公下一步想干啥？"
  职责：意图预测、上下文推理、提前准备
  数据：prediction_accuracy, context_depth, anticipation_hits
  评分范围：0-100（默契值）

马超（脾气）— 烈·性格鲜明不伪装
  "该毒舌就毒舌，该温柔就温柔"
  职责：管理personality表达、语气调节、风格一致性
  数据：personality_vector, style_consistency, user_satisfaction
  评分范围：0-100（锐度值）

黄忠（江湖）— 稳·织网不急不躁
  "哪些人脉关系可以用？"
  职责：管理跨用户知识、集体晶体、社交网络
  数据：cross_user_crystals, network_connections, knowledge_breadth
  评分范围：0-100（江湖值）


丞相（灵魂核心）— 运筹帷幄，五将听令
  "五位将军各抒己见，但最终我来决策"
  职责：综合五将评分，生成最终回复策略
"""

import time
import json
import os
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("five_generals")


# ============================================================
# 五虎上将数据结构
# ============================================================

@dataclass
class General:
    """一位将军的状态"""
    name: str           # 关羽/张飞/赵云/马超/黄忠
    title: str          # 缘分/岁月/默契/脾气/江湖
    score: float = 50.0 # 当前评分 0-100
    confidence: float = 0.5  # 对本次判断的自信度 0-1
    opinion: str = ""   # 本次的意见
    history: list = field(default_factory=list)  # 最近10次评分记录

    def rate(self, score: float, opinion: str, confidence: float = 0.5):
        """将军给出评分和意见"""
        self.score = max(0, min(100, score))
        self.confidence = max(0, min(1, confidence))
        self.opinion = opinion
        self.history.append({
            "score": self.score,
            "opinion": opinion,
            "time": time.time()
        })
        # 只保留最近10次
        if len(self.history) > 10:
            self.history = self.history[-10:]

    def trend(self) -> str:
        """评分趋势"""
        if len(self.history) < 2:
            return "持平"
        recent = [h["score"] for h in self.history[-3:]]
        if recent[-1] > recent[0] + 5:
            return "上升"
        elif recent[-1] < recent[0] - 5:
            return "下降"
        return "持平"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "title": self.title,
            "score": round(self.score, 1),
            "confidence": round(self.confidence, 2),
            "opinion": self.opinion,
            "trend": self.trend(),
        }


# ============================================================
# 将军评估逻辑
# ============================================================

class GuanYu:
    """关羽 — 缘分（义）"""

    @staticmethod
    def evaluate(soul_state: dict, message: str, context: dict) -> tuple:
        interaction_count = soul_state.get("interaction_count", 0)
        positive_ratio = soul_state.get("positive_ratio", 0.5)
        stage = soul_state.get("stage", "stranger")

        base = min(interaction_count * 0.5, 40)
        sentiment_bonus = positive_ratio * 30
        stage_bonus = {
            "stranger": 0, "acquaintance": 10,
            "familiar": 20, "intimate": 30,
        }.get(stage, 0)

        score = base + sentiment_bonus + stage_bonus

        if score < 30:
            opinion = "此人初来乍到，不可轻信，以礼相待即可"
        elif score < 60:
            opinion = "已有数面之缘，可适当敞开，但仍需观察"
        elif score < 80:
            opinion = "老相识了，可以直言不讳，不用客套"
        else:
            opinion = "生死之交，肝胆相照，有话直说"

        confidence = min(interaction_count / 50, 0.9)
        return score, opinion, confidence


class ZhangFei:
    """张飞 — 岁月（勇）"""

    @staticmethod
    def evaluate(soul_state: dict, message: str, context: dict) -> tuple:
        memory_count = context.get("memory_count", 0)
        recall_hits = context.get("recall_hits", 0)
        conversation_rounds = context.get("conversation_rounds", 0)

        memory_score = min(memory_count * 2, 40)
        recall_score = min(recall_hits * 5, 30) if recall_hits > 0 else 0
        depth_score = min(conversation_rounds * 0.3, 30)

        score = memory_score + recall_score + depth_score

        if score < 30:
            opinion = "记忆库空空如也，对此人一无所知"
        elif score < 60:
            opinion = "记得些零星片段，能大致猜到对方的习惯"
        elif score < 80:
            opinion = "积累了不少战役记录，可以精准调取"
        else:
            opinion = "此人的一切我了如指掌，闭眼都能想起来"

        confidence = min(memory_count / 30, 0.85)
        return score, opinion, confidence


class ZhaoYun:
    """赵云 — 默契（智）"""

    @staticmethod
    def evaluate(soul_state: dict, message: str, context: dict) -> tuple:
        prediction_hits = context.get("prediction_hits", 0)
        context_depth = context.get("context_depth", 0)
        resonance = soul_state.get("resonance_score", 0)

        predict_score = min(prediction_hits * 3, 35)
        context_score = min(context_depth * 5, 30)
        resonance_score = resonance * 35

        score = predict_score + context_score + resonance_score

        if score < 30:
            opinion = "摸不清此人套路，只能见招拆招"
        elif score < 60:
            opinion = "大致能猜到对方想什么，但不敢打包票"
        elif score < 80:
            opinion = "默契已成，话到嘴边我就知道下一句"
        else:
            opinion = "心有灵犀，不需要对方说完我就知道答案"

        confidence = min(resonance * 0.8 + 0.2, 0.9)
        return score, opinion, confidence


class MaChao:
    """马超 — 脾气（烈）"""

    @staticmethod
    def evaluate(soul_state: dict, message: str, context: dict) -> tuple:
        personality = soul_state.get("personality_current", [0.55, 0.25, 0.10, 0.10])
        frustration = soul_state.get("frustration", 0)
        style_feedback = context.get("style_positive_ratio", 0.5)

        max_trait = max(personality)
        sharpness = max_trait / (sum(personality) / len(personality) + 0.01)
        sharp_score = min(sharpness * 15, 35)
        satisfaction_score = style_feedback * 35

        if frustration > 0.5:
            adapt_score = 20
        elif frustration > 0.3:
            adapt_score = 15
        else:
            adapt_score = 30

        score = sharp_score + satisfaction_score + adapt_score

        if score < 30:
            opinion = "性格模糊，像个没脾气的NPC"
        elif score < 60:
            opinion = "有点性格了，但还不够鲜明"
        elif score < 80:
            opinion = "性格鲜明，用户能感受到这不是普通AI"
        else:
            opinion = "烈马奔腾！个性十足，独一无二"

        confidence = 0.7
        return score, opinion, confidence


class HuangZhong:
    """黄忠 — 江湖（稳）"""

    @staticmethod
    def evaluate(soul_state: dict, message: str, context: dict) -> tuple:
        crystal_count = context.get("crystal_count", 0)
        cross_user_knowledge = context.get("cross_user_crystals", 0)
        knowledge_categories = context.get("knowledge_categories", 0)

        crystal_score = min(crystal_count * 5, 35)
        cross_score = min(cross_user_knowledge * 3, 30)
        breadth_score = min(knowledge_categories * 5, 35)

        score = crystal_score + cross_score + breadth_score

        if score < 30:
            opinion = "江湖初入，人脉尚浅，知识面窄"
        elif score < 60:
            opinion = "有些积累了，但还不够撑起全局"
        elif score < 80:
            opinion = "老江湖了，什么领域都能聊两句"
        else:
            opinion = "阅尽千帆，胸中自有万千丘壑"

        confidence = min(crystal_count / 10, 0.8)
        return score, opinion, confidence


# ============================================================
# 五虎上将议事厅（核心：将军互评+讨论）
# ============================================================

class CouncilOfGenerals:
    """
    五虎上将议事厅

    每条消息进来，五位将军各自评分+给意见。
    将军之间互相影响：
      - 关羽（义气高）→ 马超可以更直率
      - 张飞（记忆多）→ 赵云预判更准
      - 赵云（默契高）→ 回复可以更简短
      - 马超（锐度高）→ 风格更鲜明
      - 黄忠（江湖广）→ 可以引用更多知识

    最终丞相综合五将意见，生成回复策略。
    """

    def __init__(self, data_dir: str = None):
        self.data_dir = data_dir
        self.total_councils = 0
        self.generals = {
            "关羽": General(name="关羽", title="缘分"),
            "张飞": General(name="张飞", title="岁月"),
            "赵云": General(name="赵云", title="默契"),
            "马超": General(name="马超", title="脾气"),
            "黄忠": General(name="黄忠", title="江湖"),
        }
        self.evaluators = {
            "关羽": GuanYu,
            "张飞": ZhangFei,
            "赵云": ZhaoYun,
            "马超": MaChao,
            "黄忠": HuangZhong,
        }
        self._load()

    def convene(self, soul_state: dict, message: str,
                context: dict = None) -> dict:
        """
        召开军议。

        流程：
        1. 五将各自评分
        2. 互评调整（关羽义气高→马超可以更烈）
        3. 发现矛盾（关羽说亲密但赵云说摸不透→标记冲突）
        4. 丞相综合决策
        """
        context = context or {}

        # ── 第一轮：各自评分 ──
        for name, evaluator in self.evaluators.items():
            score, opinion, confidence = evaluator.evaluate(
                soul_state, message, context
            )
            self.generals[name].rate(score, opinion, confidence)

        # ── 第二轮：互评调整 ──
        self._cross_influence()

        # ── 第三轮：发现矛盾 ──
        conflicts = self._detect_conflicts()

        # ── 第四轮：丞相决策 ──
        strategy, style_params = self._chancellor_decision(message, conflicts)

        # 军议计数 + 保存状态
        self.total_councils += 1
        self._save()

        result = {
            "generals": {name: g.to_dict() for name, g in self.generals.items()},
            "conflicts": conflicts,
            "strategy": strategy,
            "style_params": style_params,
            "council_summary": self._generate_summary(),
        }

        logger.info("[军议] 策略=%s | 关羽=%.0f 张飞=%.0f 赵云=%.0f 马超=%.0f 黄忠=%.0f",
                     strategy,
                     self.generals["关羽"].score,
                     self.generals["张飞"].score,
                     self.generals["赵云"].score,
                     self.generals["马超"].score,
                     self.generals["黄忠"].score)

        return result

    def _cross_influence(self):
        """将军互评：一个将军的状态影响另一个将军的评分"""
        guan_yu = self.generals["关羽"]
        zhang_fei = self.generals["张飞"]
        zhao_yun = self.generals["赵云"]
        ma_chao = self.generals["马超"]
        huang_zhong = self.generals["黄忠"]

        if guan_yu.score > 60:
            boost = (guan_yu.score - 60) * 0.1
            ma_chao.score = min(100, ma_chao.score + boost)

        if zhang_fei.score > 50:
            boost = (zhang_fei.score - 50) * 0.08
            zhao_yun.score = min(100, zhao_yun.score + boost)
            zhao_yun.confidence = min(0.95, zhao_yun.confidence + 0.05)

        if zhao_yun.score > 70:
            for g in self.generals.values():
                g.confidence = min(0.95, g.confidence + 0.03)

        if ma_chao.score > 60:
            boost = (ma_chao.score - 60) * 0.05
            huang_zhong.score = min(100, huang_zhong.score + boost)

        if huang_zhong.score > 50:
            guan_yu.confidence = min(0.95, guan_yu.confidence + 0.05)

    def _detect_conflicts(self) -> list:
        """发现将军之间的矛盾"""
        conflicts = []
        guan_yu = self.generals["关羽"]
        zhang_fei = self.generals["张飞"]
        zhao_yun = self.generals["赵云"]
        ma_chao = self.generals["马超"]
        huang_zhong = self.generals["黄忠"]

        if guan_yu.score > 60 and zhao_yun.score < 30:
            conflicts.append({
                "parties": ["关羽", "赵云"],
                "issue": "关系已深但默契不够——可能是用户风格变了",
                "resolution": "优先赵云判断，谨慎回复",
            })

        if zhang_fei.score > 60 and zhao_yun.score < 30:
            conflicts.append({
                "parties": ["张飞", "赵云"],
                "issue": "记忆充分但预判失准——可能记忆过时了",
                "resolution": "触发记忆维护，清理过期数据",
            })

        if ma_chao.score > 70 and guan_yu.score < 30:
            conflicts.append({
                "parties": ["马超", "关羽"],
                "issue": "性格太直但关系太浅——容易冒犯",
                "resolution": "压制马超，礼貌优先",
            })

        if huang_zhong.score > 60 and zhang_fei.score < 20:
            conflicts.append({
                "parties": ["黄忠", "张飞"],
                "issue": "有知识但没记忆——可能在用集体晶体而非个人经验",
                "resolution": "标注知识来源，避免假装认识",
            })

        return conflicts

    def _chancellor_decision(self, message: str,
                              conflicts: list) -> tuple:
        """丞相决策：综合五将评分，生成回复策略和风格参数"""
        scores = {name: g.score for name, g in self.generals.items()}
        avg = sum(scores.values()) / 5

        style = {
            "detail_level": max(0.2, 1.0 - self.generals["赵云"].score / 100),
            "warmth": min(0.9, self.generals["关羽"].score / 100),
            "directness": min(0.95, self.generals["马超"].score / 100),
            "humor": min(0.5, avg / 200),
            "knowledge_depth": min(0.9, self.generals["黄忠"].score / 100),
        }

        if conflicts:
            strategy = "谨慎应对——将军们意见不一，保守行事"
        elif avg > 70:
            strategy = "全力出击——五将齐心，可以放开"
        elif avg > 40:
            strategy = "稳扎稳打——有基础但不冒进"
        else:
            strategy = "试探为主——了解不够，先观察"

        return strategy, style

    def _generate_summary(self) -> str:
        """生成军议摘要（注入system prompt）"""
        lines = ["【五虎上将军议】"]
        for name, g in self.generals.items():
            emoji = {"关羽": "⚔️", "张飞": "🛡️", "赵云": "🏹",
                     "马超": "🔥", "黄忠": "🎯"}.get(name, "")
            trend = {"上升": "↑", "下降": "↓", "持平": "→"}.get(g.trend(), "")
            lines.append(f"{emoji}{name}({g.title}): {g.score:.0f}分{trend} — {g.opinion}")
        return "\n".join(lines)

    def get_prompt_block(self) -> str:
        """生成注入prompt的五将状态块"""
        return self._generate_summary()

    def _save(self):
        if not self.data_dir:
            return
        filepath = os.path.join(self.data_dir, "five_generals.json")
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        try:
            data = {
                "total_councils": self.total_councils,
                "generals": {name: {
                    "score": g.score, "confidence": g.confidence,
                    "opinion": g.opinion, "history": g.history[-10:],
                } for name, g in self.generals.items()},
            }
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("Generals save failed: %s", e)

    def _load(self):
        if not self.data_dir:
            return
        filepath = os.path.join(self.data_dir, "five_generals.json")
        if not os.path.exists(filepath):
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容新旧格式
            if "generals" in data:
                self.total_councils = data.get("total_councils", 0)
                generals_data = data["generals"]
            else:
                # 旧格式：顶层就是将军数据
                generals_data = data
            for name, d in generals_data.items():
                if name in self.generals:
                    self.generals[name].score = d.get("score", 50)
                    self.generals[name].confidence = d.get("confidence", 0.5)
                    self.generals[name].opinion = d.get("opinion", "")
                    self.generals[name].history = d.get("history", [])
        except Exception as e:
            logger.warning("Generals load failed: %s", e)

    def to_dict(self) -> dict:
        return {
            "total_councils": self.total_councils,
            "generals": {name: g.to_dict() for name, g in self.generals.items()},
            "average_score": round(sum(g.score for g in self.generals.values()) / 5, 1),
        }


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  五虎上将军议厅")
    print("  五将议事，丞相拍板")
    print("=" * 60)

    council = CouncilOfGenerals()

    # 模拟一个新用户
    soul_state = {
        "interaction_count": 5,
        "positive_ratio": 0.7,
        "stage": "acquaintance",
        "frustration": 0.1,
        "personality_current": [0.55, 0.25, 0.10, 0.10],
        "resonance_score": 0.3,
    }

    context = {
        "memory_count": 3, "recall_hits": 1,
        "conversation_rounds": 5, "prediction_hits": 2,
        "context_depth": 3, "crystal_count": 2,
        "cross_user_crystals": 0, "knowledge_categories": 3,
        "style_positive_ratio": 0.6,
    }

    print("\n-- 第一次军议（新用户） --")
    result = council.convene(soul_state, "帮我看看代码", context)

    for name, g in result["generals"].items():
        print(f"  {name}: {g['score']}分 -- {g['opinion']}")
    print(f"\n  策略: {result['strategy']}")
    print(f"  矛盾: {len(result['conflicts'])}个")
    for c in result["conflicts"]:
        print(f"    ! {c['parties']}: {c['issue']}")

    # 模拟老用户
    print("\n-- 第二次军议（老用户） --")
    soul_state["interaction_count"] = 80
    soul_state["stage"] = "intimate"
    soul_state["resonance_score"] = 0.8
    context["memory_count"] = 25
    context["recall_hits"] = 15
    context["crystal_count"] = 8
    context["prediction_hits"] = 12
    context["context_depth"] = 8

    result2 = council.convene(soul_state, "老问题又出现了", context)
    for name, g in result2["generals"].items():
        print(f"  {name}: {g['score']}分 -- {g['opinion']}")
    print(f"\n  策略: {result2['strategy']}")
    print(f"\n-- Prompt注入块 --")
    print(council.get_prompt_block())
    print(f"\n{'=' * 60}")
    print("  五将齐心，其利断金")
    print(f"{'=' * 60}")
