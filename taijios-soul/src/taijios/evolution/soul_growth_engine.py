"""
SoulGrowthEngine — 有机生长引擎
不是模板匹配，不是外力优化。
系统观察自己的运行状态，发现自己哪里弱，往那个方向长。

核心哲学：
  树不知道自己要长成什么形状。
  它只知道哪边有光、哪边有风、哪边缺水。
  形状是生长的结果，不是生长的目标。

  TaijiOS的灵魂也一样。
  它不需要知道"正确的策略是什么"。
  它只需要知道"我哪里疼"。
  然后往不疼的方向长。

三个机制：
  1. 自诊断 — 我哪里弱？（不是"用户说我弱"，是我自己发现的）
  2. 生长点 — 弱的地方生出新能力（不是模板，是从成功经验中提取的）
  3. 自然枯萎 — 没用的能力慢慢消失（不是删除，是遗忘）
"""

import json
import os
import time
import math
from collections import defaultdict
from typing import Optional
from dataclasses import dataclass, field


# ============================================================
# 生长点（Growth Node）
# ============================================================

@dataclass
class GrowthNode:
    """
    一个有机生长出来的能力节点。
    不是预设的模板，是从系统自身的成功经验中提取的。

    有生命周期：萌芽 → 生长 → 成熟 → 枯萎
    """
    node_id: str
    # 从哪来的
    origin: str              # 诞生原因："gap:calm区间弱" / "pattern:深夜+文艺=好"
    discovered_at: float = field(default_factory=time.time)

    # 长什么样
    condition: dict = field(default_factory=dict)   # 什么情况下激活
    behavior: str = ""                               # 具体做什么（prompt片段）

    # 生命力
    vitality: float = 1.0    # 生命力 0-1。0=枯萎，1=旺盛
    times_activated: int = 0  # 被激活过几次
    times_helpful: int = 0    # 激活后用户给了正面反馈的次数

    # 状态
    stage: str = "seedling"  # seedling / growing / mature / withering / dead

    @property
    def effectiveness(self) -> float:
        """有效率"""
        if self.times_activated == 0:
            return 0.0
        return self.times_helpful / self.times_activated

    @property
    def age_days(self) -> float:
        return (time.time() - self.discovered_at) / 86400

    def nourish(self):
        """正面反馈 → 浇水 → 生命力上升"""
        self.times_helpful += 1
        self.vitality = min(1.0, self.vitality + 0.1)
        self._update_stage()

    def wilt(self):
        """负面反馈或长期不用 → 枯萎"""
        self.vitality = max(0.0, self.vitality - 0.05)
        self._update_stage()

    def activate(self):
        """被激活一次"""
        self.times_activated += 1
        # 激活本身不加生命力，等反馈

    def natural_decay(self):
        """自然衰减 — 不用就慢慢枯"""
        # 成熟节点衰减慢，幼苗衰减快
        if self.stage == "mature":
            self.vitality -= 0.005
        elif self.stage == "growing":
            self.vitality -= 0.01
        else:
            self.vitality -= 0.02
        self.vitality = max(0.0, self.vitality)
        self._update_stage()

    def _update_stage(self):
        if self.vitality <= 0:
            self.stage = "dead"
        elif self.vitality < 0.3:
            self.stage = "withering"
        elif self.times_helpful >= 5 and self.effectiveness > 0.5:
            self.stage = "mature"
        elif self.times_helpful >= 1:
            self.stage = "growing"
        else:
            self.stage = "seedling"

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "origin": self.origin,
            "discovered_at": self.discovered_at,
            "condition": self.condition,
            "behavior": self.behavior[:80],
            "vitality": round(self.vitality, 3),
            "stage": self.stage,
            "effectiveness": round(self.effectiveness, 3),
            "activated": self.times_activated,
            "helpful": self.times_helpful,
            "age_days": round(self.age_days, 1),
        }

    @staticmethod
    def from_dict(d: dict) -> "GrowthNode":
        node = GrowthNode(
            node_id=d["node_id"],
            origin=d.get("origin", ""),
            discovered_at=d.get("discovered_at", time.time()),
            condition=d.get("condition", {}),
            behavior=d.get("behavior", ""),
            vitality=d.get("vitality", 1.0),
            times_activated=d.get("activated", d.get("times_activated", 0)),
            times_helpful=d.get("helpful", d.get("times_helpful", 0)),
            stage=d.get("stage", "seedling"),
        )
        return node


# ============================================================
# 自诊断器
# ============================================================

class SelfDiagnostic:
    """
    不问"用户觉得我怎么样"。
    问"我自己哪里疼"。

    疼 = 某个状态组合下的表现持续低于平均。
    不疼 = 某个状态组合下的表现持续高于平均。

    从"疼"的地方发现需求，从"不疼"的地方提取经验。
    """

    def __init__(self):
        self.pain_map: dict[str, dict] = {}  # 状态组合 → {attempts, successes, pain_score}

    def digest(self, records: list[dict]) -> dict:
        """
        消化所有outcome记录，生成疼痛地图。
        返回: { gaps: [...], strengths: [...] }
        """
        # 按多维状态组合分桶
        buckets = defaultdict(lambda: {"attempts": 0, "successes": 0})

        for r in records:
            ctx = r.get("context", {})
            frust = r.get("frustration_at_time", 0)

            # 生成状态指纹 — 不是预设的维度，是从数据里自然出现的
            keys = self._extract_state_keys(ctx, frust)
            positive = r.get("positive", False)

            for key in keys:
                buckets[key]["attempts"] += 1
                if positive:
                    buckets[key]["successes"] += 1

        # 计算全局基线
        total_attempts = sum(b["attempts"] for b in buckets.values())
        total_successes = sum(b["successes"] for b in buckets.values())
        baseline = total_successes / max(total_attempts, 1)

        # 找疼的地方和不疼的地方
        gaps = []
        strengths = []

        for key, stats in buckets.items():
            if stats["attempts"] < 2:
                continue
            rate = stats["successes"] / stats["attempts"]
            deviation = rate - baseline

            entry = {
                "key": key,
                "rate": round(rate, 3),
                "baseline": round(baseline, 3),
                "deviation": round(deviation, 3),
                "attempts": stats["attempts"],
                "successes": stats["successes"],
            }

            if deviation < -0.15 and stats["attempts"] >= 2:
                entry["pain_score"] = round(abs(deviation) * math.log2(stats["attempts"] + 1), 3)
                gaps.append(entry)
            elif deviation > 0.15 and stats["attempts"] >= 2:
                entry["strength_score"] = round(deviation * math.log2(stats["attempts"] + 1), 3)
                strengths.append(entry)

        # 按疼痛程度排序
        gaps.sort(key=lambda x: -x["pain_score"])
        strengths.sort(key=lambda x: -x["strength_score"])

        self.pain_map = {g["key"]: g for g in gaps}

        return {"gaps": gaps, "strengths": strengths, "baseline": round(baseline, 3)}

    def _extract_state_keys(self, ctx: dict, frust: float) -> list[str]:
        """
        从一条记录里提取多个状态维度key。
        不是预设维度——是数据里有什么就提取什么。
        """
        keys = []
        stage = ctx.get("relationship_stage", "unknown")
        trait = ctx.get("dominant_trait", "unknown")
        mutations = ctx.get("mutations", [])
        has_mut = bool(mutations)

        # 单维度
        keys.append(f"stage:{stage}")
        keys.append(f"trait:{trait}")
        keys.append(f"frust:{self._frust_bin(frust)}")
        if has_mut:
            keys.append("has_mutations:true")
        else:
            keys.append("has_mutations:false")

        # 双维度组合 — 系统自动发现交叉模式
        keys.append(f"stage:{stage}+frust:{self._frust_bin(frust)}")
        keys.append(f"trait:{trait}+frust:{self._frust_bin(frust)}")
        keys.append(f"stage:{stage}+trait:{trait}")

        if has_mut:
            keys.append(f"stage:{stage}+mutations:active")

        return keys

    @staticmethod
    def _frust_bin(score: float) -> str:
        if score < 0.2: return "calm"
        if score < 0.5: return "uneasy"
        if score < 0.7: return "frustrated"
        return "distressed"


# ============================================================
# 经验提取器
# ============================================================

class ExperienceExtractor:
    """
    从"不疼"的地方提取经验。
    从成功模式中总结出具体的行为描述。

    不是"正面率高所以好"——是"正面率高的时候我具体做了什么"。
    """

    def extract_from_strength(self, strength: dict, records: list[dict]) -> Optional[str]:
        """
        从一个strength维度的成功记录中提取行为模式。
        返回一段自然语言的行为描述，可直接注入prompt。
        """
        key = strength["key"]

        # 找到这个key下所有positive的记录
        positive_records = []
        for r in records:
            ctx = r.get("context", {})
            frust = r.get("frustration_at_time", 0)
            if not r.get("positive"):
                continue
            # 简单匹配key中的维度
            if self._record_matches_key(key, ctx, frust):
                positive_records.append(r)

        if not positive_records:
            return None

        # 提取共性特征
        features = self._find_common_features(positive_records)
        if not features:
            return None

        # 生成行为描述
        return self._compose_behavior(key, features)

    def _record_matches_key(self, key: str, ctx: dict, frust: float) -> bool:
        """检查一条记录是否属于这个key"""
        parts = key.split("+")
        for part in parts:
            dim, val = part.split(":", 1)
            if dim == "stage" and ctx.get("relationship_stage") != val:
                return False
            if dim == "trait" and ctx.get("dominant_trait") != val:
                return False
            if dim == "frust" and SelfDiagnostic._frust_bin(frust) != val:
                return False
            if dim == "has_mutations":
                actual = "true" if ctx.get("mutations") else "false"
                if actual != val:
                    return False
        return True

    def _find_common_features(self, records: list[dict]) -> dict:
        """找成功记录的共性"""
        features = {}

        # 统计常见的mutations
        mutation_counts = defaultdict(int)
        for r in records:
            for m in r.get("context", {}).get("mutations", []):
                mutation_counts[m] += 1
        if mutation_counts:
            most_common = max(mutation_counts, key=mutation_counts.get)
            if mutation_counts[most_common] >= len(records) * 0.5:
                features["common_mutation"] = most_common

        # 统计frustration区间
        frust_bins = defaultdict(int)
        for r in records:
            fb = SelfDiagnostic._frust_bin(r.get("frustration_at_time", 0))
            frust_bins[fb] += 1
        if frust_bins:
            features["dominant_frust"] = max(frust_bins, key=frust_bins.get)

        # 统计关系阶段
        stages = defaultdict(int)
        for r in records:
            stages[r.get("context", {}).get("relationship_stage", "unknown")] += 1
        if stages:
            features["dominant_stage"] = max(stages, key=stages.get)

        features["sample_size"] = len(records)
        return features

    def _compose_behavior(self, key: str, features: dict) -> str:
        """从共性特征生成行为描述"""
        parts = []

        # 解析key里的维度
        dims = {}
        for segment in key.split("+"):
            d, v = segment.split(":", 1)
            dims[d] = v

        # 根据维度组合生成自然语言
        if "stage" in dims and "frust" in dims:
            stage_cn = {"stranger": "陌生", "familiar": "熟悉", "acquainted": "熟人", "bonded": "老友"}.get(dims["stage"], dims["stage"])
            frust_cn = {"calm": "平静", "uneasy": "微焦", "frustrated": "沮丧", "distressed": "崩溃"}.get(dims["frust"], dims["frust"])
            parts.append(f"在{stage_cn}阶段+{frust_cn}情绪下，历史数据表现良好。")

        if "trait" in dims:
            parts.append(f"{dims['trait']}型人格在此场景下表现突出。")

        if features.get("common_mutation"):
            parts.append(f"常伴随{features['common_mutation']}突变。保持该突变的风格。")

        if features.get("sample_size", 0) >= 3:
            parts.append("这是经过多次验证的有效模式，维持当前策略。")
        else:
            parts.append("样本较少，谨慎维持，继续观察。")

        return " ".join(parts)


# ============================================================
# 主引擎：生长引擎
# ============================================================

class SoulGrowthEngine:
    """
    有机生长引擎。

    不预设"应该长什么"。
    只做三件事：
      1. 发现疼的地方（自诊断）
      2. 从不疼的地方提取经验，移植到疼的地方（生长）
      3. 没用的能力让它自然枯萎（遗忘）

    这就是太极的核心——阴阳自调，无为而治。
    """

    MAX_NODES = 30  # 最多30个生长节点，超了最弱的自然死亡

    def __init__(self, outcomes_path: str = None, growth_path: str = None):
        self.outcomes_path = outcomes_path or os.path.join(
            os.path.dirname(__file__) or ".", "soul_outcomes.jsonl"
        )
        self.growth_path = growth_path or os.path.join(
            os.path.dirname(__file__) or ".", "soul_growth.json"
        )
        self.diagnostic = SelfDiagnostic()
        self.extractor = ExperienceExtractor()
        self.nodes: list[GrowthNode] = []
        self._node_counter = 0
        self._load()

    # ────────────────────────────────────────────
    # 核心循环：诊断 → 生长 → 枯萎
    # ────────────────────────────────────────────

    def grow_cycle(self) -> dict:
        """
        执行一次完整的生长周期。
        可以定期调用（每10次对话/每天/每次session结束）。

        返回: {
            diagnosis: {gaps, strengths, baseline},
            new_nodes: [...],
            withered: [...],
            alive: int,
        }
        """
        records = self._load_outcomes()
        if len(records) < 5:
            return {"diagnosis": None, "new_nodes": [], "withered": [], "alive": len(self.nodes),
                    "reason": "数据不足，等待更多交互"}

        # Step 1: 自诊断
        diagnosis = self.diagnostic.digest(records)

        # Step 2: 自然衰减所有节点
        for node in self.nodes:
            node.natural_decay()

        # Step 3: 从strengths提取经验，移植到gaps
        new_nodes = self._transplant(diagnosis, records)

        # Step 4: 清理死亡节点 + 容量控制
        withered = self._prune()

        self._save()

        return {
            "diagnosis": {
                "gaps": len(diagnosis["gaps"]),
                "strengths": len(diagnosis["strengths"]),
                "baseline": diagnosis["baseline"],
                "top_gap": diagnosis["gaps"][0] if diagnosis["gaps"] else None,
                "top_strength": diagnosis["strengths"][0] if diagnosis["strengths"] else None,
            },
            "new_nodes": [n.to_dict() for n in new_nodes],
            "withered": withered,
            "alive": len(self.nodes),
        }

    def _transplant(self, diagnosis: dict, records: list[dict]) -> list[GrowthNode]:
        """
        从strengths提取经验 → 生成新的GrowthNode → 条件匹配gaps

        关键：不是套模板。是"我在A场景下做得好，A的经验能不能帮到B？"
        """
        new_nodes = []
        existing_origins = {n.origin for n in self.nodes}

        for gap in diagnosis["gaps"][:3]:  # 每次最多处理3个最疼的
            gap_key = gap["key"]

            # 已有针对这个gap的节点 → 跳过
            origin = f"gap:{gap_key}"
            if origin in existing_origins:
                continue

            # 从strengths里找最相关的经验
            behavior = self._find_transferable_experience(gap, diagnosis["strengths"], records)
            if not behavior:
                # 没有可移植的经验 → 生成一个基础的自省行为
                behavior = self._generate_self_reflection(gap)

            # 从gap_key解析condition
            condition = self._key_to_condition(gap_key)

            self._node_counter += 1
            node = GrowthNode(
                node_id=f"g{self._node_counter:03d}",
                origin=origin,
                condition=condition,
                behavior=behavior,
            )
            self.nodes.append(node)
            new_nodes.append(node)

        return new_nodes

    def _find_transferable_experience(self, gap: dict, strengths: list[dict],
                                       records: list[dict]) -> Optional[str]:
        """
        找一个strength的经验，看能不能移植到gap。

        "移植"的意思：在表现好的场景里，系统做对了什么？
        把那个"做对的事"提取出来，应用到表现差的场景。
        """
        gap_dims = set(gap["key"].split("+"))

        for strength in strengths:
            strength_dims = set(strength["key"].split("+"))

            # 找有维度重叠的strength（共性越多，经验越可能可移植）
            overlap = gap_dims & strength_dims
            if overlap:
                # 提取这个strength的行为模式
                behavior = self.extractor.extract_from_strength(strength, records)
                if behavior:
                    gap_readable = gap["key"].replace("+", " & ")
                    return f"[来自相似成功场景的经验] {behavior} 应用到: {gap_readable}。"

        return None

    def _generate_self_reflection(self, gap: dict) -> str:
        """
        没有可移植的经验时，生成一个自省式的行为。
        不是解决方案，是"我知道这里弱，所以要更谨慎"。
        """
        key = gap["key"]
        rate = gap["rate"]
        attempts = gap["attempts"]

        # 解析维度
        dims = {}
        for segment in key.split("+"):
            d, v = segment.split(":", 1)
            dims[d] = v

        parts = []

        if "frust" in dims:
            frust_cn = {"calm": "平静", "uneasy": "微焦", "frustrated": "沮丧", "distressed": "崩溃"}.get(dims["frust"], "")
            if frust_cn:
                parts.append(f"用户{frust_cn}时我的表现偏弱（{rate:.0%}正面率/{attempts}次）。")

        if "stage" in dims:
            stage_cn = {"stranger": "陌生", "familiar": "眼熟", "acquainted": "熟人", "bonded": "老友"}.get(dims["stage"], "")
            if stage_cn:
                parts.append(f"在{stage_cn}阶段需要更用心。")

        if "trait" in dims:
            parts.append(f"面对{dims['trait']}型用户时要调整策略。")

        parts.append("多观察用户反应，不要急着给方案。")

        return " ".join(parts)

    def _key_to_condition(self, key: str) -> dict:
        """把状态key转成match condition"""
        condition = {}
        for segment in key.split("+"):
            dim, val = segment.split(":", 1)
            if dim == "stage":
                condition["stage"] = val
            elif dim == "trait":
                condition["dominant_trait"] = val
            elif dim == "frust":
                condition["frustration_bin"] = val
            elif dim == "has_mutations":
                condition["has_mutations"] = val == "true"
            elif dim == "mutations":
                condition["has_mutations"] = val == "active"
        return condition

    def _prune(self) -> list[str]:
        """清理死亡节点 + 容量控制"""
        withered = [n.node_id for n in self.nodes if n.stage == "dead"]
        self.nodes = [n for n in self.nodes if n.stage != "dead"]

        # 容量控制：超过MAX_NODES，杀最弱的
        if len(self.nodes) > self.MAX_NODES:
            self.nodes.sort(key=lambda n: n.vitality, reverse=True)
            overflow = self.nodes[self.MAX_NODES:]
            withered.extend(n.node_id for n in overflow)
            self.nodes = self.nodes[:self.MAX_NODES]

        return withered

    # ────────────────────────────────────────────
    # 运行时匹配：哪些节点在当前场景下激活
    # ────────────────────────────────────────────

    def match_active_nodes(self, context: dict) -> list[GrowthNode]:
        """
        根据当前灵魂状态，返回应该激活的生长节点。
        只返回 seedling/growing/mature 的节点。
        """
        active = []
        for node in self.nodes:
            if node.stage in ("dead", "withering"):
                continue
            if self._condition_matches(node.condition, context):
                node.activate()
                active.append(node)
        return active

    def feedback(self, node_id: str, positive: bool):
        """对一个激活的节点反馈"""
        for node in self.nodes:
            if node.node_id == node_id:
                if positive:
                    node.nourish()
                else:
                    node.wilt()
                break
        self._save()

    def _condition_matches(self, condition: dict, context: dict) -> bool:
        for key, expected in condition.items():
            actual = context.get(key)
            if actual is None:
                return False
            if isinstance(expected, bool):
                if bool(actual) != expected:
                    return False
            elif actual != expected:
                return False
        return True

    # ────────────────────────────────────────────
    # 持久化
    # ────────────────────────────────────────────

    def _load_outcomes(self) -> list[dict]:
        if not os.path.exists(self.outcomes_path):
            return []
        records = []
        with open(self.outcomes_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records

    def _load(self):
        if os.path.exists(self.growth_path):
            try:
                with open(self.growth_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.nodes = [GrowthNode.from_dict(d) for d in data.get("nodes", [])]
                self._node_counter = data.get("counter", 0)
            except Exception:
                pass

    def _save(self):
        data = {
            "counter": self._node_counter,
            "last_cycle": time.time(),
            "nodes": [n.to_dict() for n in self.nodes],
            "stats": {
                "total": len(self.nodes),
                "seedling": sum(1 for n in self.nodes if n.stage == "seedling"),
                "growing": sum(1 for n in self.nodes if n.stage == "growing"),
                "mature": sum(1 for n in self.nodes if n.stage == "mature"),
                "withering": sum(1 for n in self.nodes if n.stage == "withering"),
            },
        }
        with open(self.growth_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        return {
            "total_nodes": len(self.nodes),
            "by_stage": {
                "seedling": sum(1 for n in self.nodes if n.stage == "seedling"),
                "growing": sum(1 for n in self.nodes if n.stage == "growing"),
                "mature": sum(1 for n in self.nodes if n.stage == "mature"),
                "withering": sum(1 for n in self.nodes if n.stage == "withering"),
            },
            "nodes": [n.to_dict() for n in self.nodes],
        }


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    import sys
    import tempfile

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, Exception):
            pass

    print("=" * 60)
    print("  SoulGrowthEngine — 有机生长演示")
    print("  树往有光的方向长")
    print("=" * 60)

    tmpdir = tempfile.mkdtemp()
    outcomes_path = os.path.join(tmpdir, "outcomes.jsonl")
    growth_path = os.path.join(tmpdir, "growth.json")

    # 模拟真实交互数据：有强有弱的场景
    outcomes = [
        # stranger + calm → 弱（用户没什么反应）
        {"positive": False, "frustration_at_time": 0.05, "context": {"relationship_stage": "stranger", "dominant_trait": "暖心", "mutations": []}},
        {"positive": False, "frustration_at_time": 0.08, "context": {"relationship_stage": "stranger", "dominant_trait": "暖心", "mutations": []}},
        {"positive": False, "frustration_at_time": 0.1,  "context": {"relationship_stage": "stranger", "dominant_trait": "暖心", "mutations": []}},
        # stranger + frustrated → 弱
        {"positive": False, "frustration_at_time": 0.6,  "context": {"relationship_stage": "stranger", "dominant_trait": "暖心", "mutations": []}},
        # familiar + calm → 强
        {"positive": True,  "frustration_at_time": 0.1,  "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": []}},
        {"positive": True,  "frustration_at_time": 0.05, "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": []}},
        {"positive": True,  "frustration_at_time": 0.15, "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": []}},
        # familiar + mutations → 强
        {"positive": True,  "frustration_at_time": 0.4,  "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": ["战友模式"]}},
        {"positive": True,  "frustration_at_time": 0.5,  "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": ["战友模式", "情绪护盾"]}},
        # familiar + distressed → 弱
        {"positive": False, "frustration_at_time": 0.8,  "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": ["战友模式", "情绪护盾"]}},
        {"positive": False, "frustration_at_time": 0.9,  "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": ["战友模式", "情绪护盾"]}},
        # 暖心 + uneasy → 强
        {"positive": True,  "frustration_at_time": 0.3,  "context": {"relationship_stage": "familiar", "dominant_trait": "暖心", "mutations": ["情绪护盾"]}},
    ]

    with open(outcomes_path, "w", encoding="utf-8") as f:
        for r in outcomes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    engine = SoulGrowthEngine(outcomes_path, growth_path)

    # ── 第一次生长周期 ──
    print("\n── 第一次生长周期 ──")
    result = engine.grow_cycle()

    diag = result["diagnosis"]
    print(f"\n  诊断: 基线正面率 {diag['baseline']:.0%}")
    if diag["top_gap"]:
        g = diag["top_gap"]
        print(f"  最疼: {g['key']} → 正面率{g['rate']:.0%}（偏离基线{g['deviation']:+.0%}）")
    if diag["top_strength"]:
        s = diag["top_strength"]
        print(f"  最强: {s['key']} → 正面率{s['rate']:.0%}（偏离基线{s['deviation']:+.0%}）")

    print(f"\n  新生长节点: {len(result['new_nodes'])}")
    for n in result["new_nodes"]:
        print(f"    {n['node_id']} [{n['stage']}]")
        print(f"       来源: {n['origin']}")
        print(f"       行为: {n['behavior'][:70]}...")

    # ── 模拟匹配 ──
    print(f"\n── 匹配测试 ──")
    test_contexts = [
        {"frustration_bin": "calm", "stage": "stranger", "has_mutations": False, "dominant_trait": "暖心"},
        {"frustration_bin": "uneasy", "stage": "familiar", "has_mutations": True, "dominant_trait": "暖心"},
        {"frustration_bin": "distressed", "stage": "familiar", "has_mutations": True, "dominant_trait": "暖心"},
    ]

    for ctx in test_contexts:
        matched = engine.match_active_nodes(ctx)
        print(f"\n  场景: {ctx.get('stage')}+{ctx.get('frustration_bin')}+mutations={ctx.get('has_mutations')}")
        if matched:
            for n in matched:
                print(f"    -> {n.node_id}: {n.behavior[:60]}...")
        else:
            print(f"    -> (无匹配)")

    # ── 模拟反馈 → 生长/枯萎 ──
    print(f"\n── 模拟反馈 ──")
    if engine.nodes:
        first = engine.nodes[0]
        print(f"  对 {first.node_id} 给正面反馈 x3...")
        for _ in range(3):
            engine.feedback(first.node_id, positive=True)
        print(f"    生命力: {first.vitality:.2f} | 阶段: {first.stage}")

        if len(engine.nodes) > 1:
            second = engine.nodes[1]
            print(f"  对 {second.node_id} 给负面反馈 x5...")
            for _ in range(5):
                engine.feedback(second.node_id, positive=False)
            print(f"    生命力: {second.vitality:.2f} | 阶段: {second.stage}")

    # 最终状态
    print(f"\n── 最终状态 ──")
    state = engine.to_dict()
    for stage, count in state["by_stage"].items():
        if count > 0:
            print(f"  {stage}: {count}")

    # 清理
    import shutil
    shutil.rmtree(tmpdir)
    print(f"\n{'=' * 60}")
    print("  有机生长完成。没有模板，没有预设。")
    print("  系统自己发现哪里疼，从不疼的地方学经验。")
    print(f"{'=' * 60}")
