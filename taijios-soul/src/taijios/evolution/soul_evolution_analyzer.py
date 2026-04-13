"""
SoulEvolutionAnalyzer — 进化引擎
从行为数据中提取洞察 → 生成prompt补丁 → 评估效果 → 保留或回滚

闭环：
  record_outcome() 写入 soul_outcomes.jsonl
  → extract_insights() 分析模式
  → generate_patches() 生成具体的prompt修改
  → SoulAwareCodeAssist 加载 active patches 注入prompt
  → 新的 outcome 带上 patch_ids
  → evaluate_patches() 对比 patch 前后效果
  → keep / rollback

系统从此不需要手动调参。
"""

import json
import os
import time
import hashlib
from typing import Optional
from dataclasses import dataclass, field


# ============================================================
# Patch 数据结构
# ============================================================

@dataclass
class PromptPatch:
    """一个可追溯、可回滚的prompt补丁"""
    patch_id: str
    generation: int                    # 第几代进化
    source_insight: str                # 来源洞察ID
    condition: dict                    # 生效条件 {"frustration_bin": "calm", "stage": "stranger"}
    prompt_addition: str               # 注入的prompt文本
    status: str = "active"             # active / kept / rolled_back / expired
    created_at: float = field(default_factory=time.time)
    outcomes_before: int = 0           # patch生成前的outcome数量
    outcomes_with: int = 0             # 带此patch的outcome数量
    positive_with: int = 0             # 带此patch的positive数量
    positive_rate_before: float = 0.0  # patch前的正面率
    evaluation_note: str = ""

    def to_dict(self) -> dict:
        return {
            "patch_id": self.patch_id,
            "generation": self.generation,
            "source_insight": self.source_insight,
            "condition": self.condition,
            "prompt_addition": self.prompt_addition,
            "status": self.status,
            "created_at": self.created_at,
            "outcomes_with": self.outcomes_with,
            "positive_with": self.positive_with,
            "positive_rate_with": round(self.positive_with / max(self.outcomes_with, 1), 3),
            "positive_rate_before": self.positive_rate_before,
            "evaluation_note": self.evaluation_note,
        }

    @staticmethod
    def from_dict(d: dict) -> "PromptPatch":
        return PromptPatch(
            patch_id=d["patch_id"],
            generation=d.get("generation", 1),
            source_insight=d.get("source_insight", ""),
            condition=d.get("condition", {}),
            prompt_addition=d.get("prompt_addition", ""),
            status=d.get("status", "active"),
            created_at=d.get("created_at", time.time()),
            outcomes_before=d.get("outcomes_before", 0),
            outcomes_with=d.get("outcomes_with", 0),
            positive_with=d.get("positive_with", 0),
            positive_rate_before=d.get("positive_rate_before", 0),
            evaluation_note=d.get("evaluation_note", ""),
        )


# ============================================================
# Frustration 分桶（复用）
# ============================================================

def frustration_bin(score: float) -> str:
    if score < 0.2:
        return "calm"
    elif score < 0.5:
        return "uneasy"
    elif score < 0.7:
        return "frustrated"
    else:
        return "distressed"


# ============================================================
# 主引擎
# ============================================================

class SoulEvolutionAnalyzer:
    """
    进化引擎：分析行为数据，生成策略补丁，评估效果。

    用法：
        analyzer = SoulEvolutionAnalyzer(outcomes_path, patches_path)

        # 周期性调用（每N次对话或每天）
        insights = analyzer.extract_insights()
        new_patches = analyzer.generate_patches(insights)
        evaluations = analyzer.evaluate_patches()

        # SoulAwareCodeAssist 读取 active patches
        patches = analyzer.get_active_patches()
    """

    # ── Patch 生成规则：insight类型 → 补丁模板 ──
    PATCH_TEMPLATES = {
        "frustration_gap:calm": {
            "condition": {"frustration_bin": "calm"},
            "prompt_addition": (
                "用户情绪平稳，但历史数据显示此状态下满意度偏低。"
                "多确认一句「这样解决了吗」或「还有什么不清楚的」。"
                "不要假设用户满意了。"
            ),
        },
        "frustration_gap:distressed": {
            "condition": {"frustration_bin": "distressed"},
            "prompt_addition": (
                "用户极度沮丧。历史数据显示此状态下正面反馈几乎为零。"
                "降低期望值——此刻的目标不是解决问题，是让用户感到被支持。"
                "先说「我在」或「慢慢来」，然后等用户引导方向。"
            ),
        },
        "stage_disparity": {
            "condition": {"stage": "stranger"},
            "prompt_addition": (
                "与陌生用户交互效果偏低。"
                "尝试更快建立信任：主动说明你的思路而不只给答案。"
                "让用户看到推理过程，建立「这个AI是认真的」的印象。"
            ),
        },
        "mutation_effective": {
            "condition": {"has_mutations": True},
            "prompt_addition": (
                "当前有突变保护生效。历史数据显示此时策略有效。"
                "保持当前风格不要退缩。"
            ),
        },
        "recovery_with_protection": {
            "condition": {"frustration_bin": "uneasy", "has_mutations": True},
            "prompt_addition": (
                "用户从高挫败恢复中。双重保护仍在。"
                "这是黄金窗口——历史数据显示此时正面率最高。"
                "保持温和但开始适度引入解决方案。"
            ),
        },
    }

    # 评估阈值
    MIN_OUTCOMES_TO_EVALUATE = 5     # 至少5条数据才评估
    IMPROVEMENT_THRESHOLD = 0.15     # 正面率提升>15%才keep
    REGRESSION_THRESHOLD = -0.10     # 正面率下降>10%就rollback

    def __init__(self, outcomes_path: str = None, patches_path: str = None):
        self.outcomes_path = outcomes_path or os.path.join(
            os.path.dirname(__file__) or ".", "soul_outcomes.jsonl"
        )
        self.patches_path = patches_path or os.path.join(
            os.path.dirname(__file__) or ".", "soul_patches.json"
        )
        self.patches: list[PromptPatch] = []
        self._generation = 0
        self._load_patches()

    # ────────────────────────────────────────────
    # 数据加载
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

    def _load_patches(self):
        if os.path.exists(self.patches_path):
            try:
                with open(self.patches_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.patches = [PromptPatch.from_dict(p) for p in data.get("patches", [])]
                self._generation = data.get("generation", 0)
            except Exception:
                self.patches = []
                self._generation = 0

    def _save_patches(self):
        data = {
            "generation": self._generation,
            "patches": [p.to_dict() for p in self.patches],
            "last_updated": time.time(),
        }
        with open(self.patches_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ────────────────────────────────────────────
    # Phase 1: 提取洞察
    # ────────────────────────────────────────────

    def extract_insights(self) -> list[dict]:
        """从outcome数据中提取模式洞察"""
        records = self._load_outcomes()
        if len(records) < 3:
            return []

        insights = []

        # ── 按frustration分桶分析 ──
        bins = {}
        for r in records:
            fb = frustration_bin(r.get("frustration_at_time", 0))
            bins.setdefault(fb, {"total": 0, "positive": 0})
            bins[fb]["total"] += 1
            if r.get("positive"):
                bins[fb]["positive"] += 1

        for bin_name, stats in bins.items():
            rate = stats["positive"] / max(stats["total"], 1)
            if rate < 0.3 and stats["total"] >= 2:
                insights.append({
                    "id": f"frustration_gap:{bin_name}",
                    "confidence": min(0.9, 0.4 + stats["total"] * 0.1),
                    "detail": f"{bin_name}区间正面率{rate:.0%}（{stats['positive']}/{stats['total']}），偏低",
                    "positive_rate": rate,
                    "sample_size": stats["total"],
                })

        # ── 按关系阶段分析 ──
        stages = {}
        for r in records:
            stage = r.get("context", {}).get("relationship_stage", "unknown")
            stages.setdefault(stage, {"total": 0, "positive": 0})
            stages[stage]["total"] += 1
            if r.get("positive"):
                stages[stage]["positive"] += 1

        for stage, stats in stages.items():
            rate = stats["positive"] / max(stats["total"], 1)
            if rate < 0.3 and stats["total"] >= 2:
                insights.append({
                    "id": "stage_disparity",
                    "confidence": 0.5,
                    "detail": f"{stage}阶段正面率{rate:.0%}",
                    "stage": stage,
                    "positive_rate": rate,
                })

        # ── 突变有效性 ──
        mutation_records = [r for r in records if r.get("context", {}).get("mutations")]
        if len(mutation_records) >= 2:
            pos = sum(1 for r in mutation_records if r.get("positive"))
            rate = pos / len(mutation_records)
            mutation_names = set()
            for r in mutation_records:
                for m in r.get("context", {}).get("mutations", []):
                    mutation_names.add(m)
            insights.append({
                "id": "mutation_effective",
                "confidence": 0.6,
                "detail": f"突变组合{'+'.join(mutation_names)}有效率{rate:.0%}",
                "positive_rate": rate,
                "mutations": list(mutation_names),
            })

        # ── 恢复窗口 ──
        for r in records:
            fb = frustration_bin(r.get("frustration_at_time", 0))
            has_mut = bool(r.get("context", {}).get("mutations"))
            if fb == "uneasy" and has_mut and r.get("positive"):
                insights.append({
                    "id": "recovery_with_protection",
                    "confidence": 0.6,
                    "detail": "恢复期+双突变保护=有效",
                    "positive_rate": 1.0,
                })
                break  # 只报一次

        return insights

    # ────────────────────────────────────────────
    # Phase 2: 生成补丁
    # ────────────────────────────────────────────

    def generate_patches(self, insights: list[dict] = None) -> list[PromptPatch]:
        """
        从洞察生成prompt补丁。
        只为还没有对应patch的insight生成新patch。
        """
        if insights is None:
            insights = self.extract_insights()

        records = self._load_outcomes()
        existing_sources = {p.source_insight for p in self.patches}

        new_patches = []
        for insight in insights:
            insight_id = insight["id"]

            # 已有对应patch → 跳过
            if insight_id in existing_sources:
                continue

            # 查模板
            template = self.PATCH_TEMPLATES.get(insight_id)
            if not template:
                continue

            # 计算patch前的基线正面率
            matching = self._filter_outcomes_by_condition(records, template["condition"])
            baseline_pos = sum(1 for r in matching if r.get("positive"))
            baseline_rate = baseline_pos / max(len(matching), 1)

            self._generation += 1
            patch = PromptPatch(
                patch_id=f"p{self._generation:03d}",
                generation=self._generation,
                source_insight=insight_id,
                condition=template["condition"],
                prompt_addition=template["prompt_addition"],
                status="active",
                outcomes_before=len(matching),
                positive_rate_before=baseline_rate,
            )
            self.patches.append(patch)
            new_patches.append(patch)

        if new_patches:
            self._save_patches()

        return new_patches

    # ────────────────────────────────────────────
    # Phase 3: 评估补丁
    # ────────────────────────────────────────────

    def evaluate_patches(self) -> list[dict]:
        """
        评估所有active状态的patch。
        对比patch激活后的正面率 vs 基线。
        满足阈值 → keep，退化 → rollback，数据不足 → 等待。
        """
        records = self._load_outcomes()
        evaluations = []

        for patch in self.patches:
            if patch.status != "active":
                continue

            # 统计带此patch的outcomes
            with_patch = [
                r for r in records
                if patch.patch_id in r.get("active_patches", [])
            ]
            patch.outcomes_with = len(with_patch)
            patch.positive_with = sum(1 for r in with_patch if r.get("positive"))

            if patch.outcomes_with < self.MIN_OUTCOMES_TO_EVALUATE:
                evaluations.append({
                    "patch_id": patch.patch_id,
                    "action": "waiting",
                    "reason": f"数据不足（{patch.outcomes_with}/{self.MIN_OUTCOMES_TO_EVALUATE}）",
                    "outcomes_with": patch.outcomes_with,
                })
                continue

            rate_with = patch.positive_with / patch.outcomes_with
            improvement = rate_with - patch.positive_rate_before

            if improvement >= self.IMPROVEMENT_THRESHOLD:
                patch.status = "kept"
                patch.evaluation_note = (
                    f"正面率从{patch.positive_rate_before:.0%}提升到{rate_with:.0%}"
                    f"（+{improvement:.0%}），保留"
                )
                evaluations.append({
                    "patch_id": patch.patch_id,
                    "action": "kept",
                    "improvement": round(improvement, 3),
                    "rate_before": patch.positive_rate_before,
                    "rate_after": rate_with,
                    "note": patch.evaluation_note,
                })

            elif improvement <= self.REGRESSION_THRESHOLD:
                patch.status = "rolled_back"
                patch.evaluation_note = (
                    f"正面率从{patch.positive_rate_before:.0%}降到{rate_with:.0%}"
                    f"（{improvement:+.0%}），回滚"
                )
                evaluations.append({
                    "patch_id": patch.patch_id,
                    "action": "rolled_back",
                    "improvement": round(improvement, 3),
                    "rate_before": patch.positive_rate_before,
                    "rate_after": rate_with,
                    "note": patch.evaluation_note,
                })

            else:
                evaluations.append({
                    "patch_id": patch.patch_id,
                    "action": "inconclusive",
                    "improvement": round(improvement, 3),
                    "reason": f"变化{improvement:+.0%}未达阈值，继续观察",
                })

        self._save_patches()
        return evaluations

    # ────────────────────────────────────────────
    # 公开接口
    # ────────────────────────────────────────────

    def get_active_patches(self) -> list[PromptPatch]:
        """返回所有活跃或已保留的patch，供CodeAssist注入"""
        return [p for p in self.patches if p.status in ("active", "kept")]

    def get_active_patch_ids(self) -> list[str]:
        """返回活跃patch的ID列表，用于outcome记录"""
        return [p.patch_id for p in self.get_active_patches()]

    def match_patches(self, context: dict) -> list[PromptPatch]:
        """
        根据当前灵魂状态匹配适用的patch。
        context 包含: frustration_bin, stage, has_mutations 等
        """
        matched = []
        for patch in self.get_active_patches():
            if self._condition_matches(patch.condition, context):
                matched.append(patch)
        return matched

    # ────────────────────────────────────────────
    # 内部工具
    # ────────────────────────────────────────────

    def _condition_matches(self, condition: dict, context: dict) -> bool:
        """检查context是否满足patch的condition"""
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

    def _filter_outcomes_by_condition(self, records: list[dict], condition: dict) -> list[dict]:
        """从outcomes中筛选满足condition的记录"""
        matched = []
        for r in records:
            ctx = self._outcome_to_match_context(r)
            if self._condition_matches(condition, ctx):
                matched.append(r)
        return matched

    @staticmethod
    def _outcome_to_match_context(record: dict) -> dict:
        """把一条outcome记录转成可匹配的context"""
        ctx = record.get("context", {})
        return {
            "frustration_bin": frustration_bin(record.get("frustration_at_time", 0)),
            "stage": ctx.get("relationship_stage", "unknown"),
            "has_mutations": bool(ctx.get("mutations")),
            "dominant_trait": ctx.get("dominant_trait", ""),
        }

    def to_dict(self) -> dict:
        active = [p for p in self.patches if p.status in ("active", "kept")]
        rolled = [p for p in self.patches if p.status == "rolled_back"]
        return {
            "generation": self._generation,
            "total_patches": len(self.patches),
            "active": len(active),
            "rolled_back": len(rolled),
            "patches": [p.to_dict() for p in self.patches],
        }


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    import tempfile

    print("=" * 60)
    print("  SoulEvolutionAnalyzer — 自动进化循环演示")
    print("=" * 60)

    # 创建临时数据
    tmpdir = tempfile.mkdtemp()
    outcomes_path = os.path.join(tmpdir, "outcomes.jsonl")
    patches_path = os.path.join(tmpdir, "patches.json")

    # 模拟8条outcome（跟实际LLM测试数据一致）
    outcomes = [
        {"positive": False, "frustration_at_time": 0.0,   "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": []},
        {"positive": False, "frustration_at_time": 0.0,   "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": []},
        {"positive": False, "frustration_at_time": 0.0,   "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": []},
        {"positive": False, "frustration_at_time": 0.0,   "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": []},
        {"positive": False, "frustration_at_time": 0.45,  "context": {"relationship_stage": "familiar", "mutations": ["战友模式"]}, "active_patches": []},
        {"positive": False, "frustration_at_time": 0.855, "context": {"relationship_stage": "familiar", "mutations": ["战友模式", "情绪护盾"]}, "active_patches": []},
        {"positive": False, "frustration_at_time": 0.919, "context": {"relationship_stage": "familiar", "mutations": ["战友模式", "情绪护盾"]}, "active_patches": []},
        {"positive": True,  "frustration_at_time": 0.428, "context": {"relationship_stage": "familiar", "mutations": ["战友模式", "情绪护盾"]}, "active_patches": []},
    ]

    with open(outcomes_path, "w") as f:
        for r in outcomes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    analyzer = SoulEvolutionAnalyzer(outcomes_path, patches_path)

    # Step 1: 提取洞察
    print("\n── Step 1: 提取洞察 ──")
    insights = analyzer.extract_insights()
    for ins in insights:
        print(f"  [{ins['confidence']:.1f}] {ins['id']} — {ins['detail']}")

    # Step 2: 生成补丁
    print("\n── Step 2: 生成补丁 ──")
    new_patches = analyzer.generate_patches(insights)
    for p in new_patches:
        print(f"  {p.patch_id} [{p.status}] {p.source_insight}")
        print(f"    条件: {p.condition}")
        print(f"    注入: {p.prompt_addition[:60]}...")
        print(f"    基线正面率: {p.positive_rate_before:.0%}")

    # Step 3: 模拟使用patch后的新outcomes
    print("\n── Step 3: 模拟patch生效后的新数据 ──")
    active_ids = analyzer.get_active_patch_ids()
    print(f"  当前活跃patch: {active_ids}")

    # 模拟5条新数据（calm区间有了patch之后效果变好）
    new_outcomes = [
        {"positive": True,  "frustration_at_time": 0.05, "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": active_ids},
        {"positive": True,  "frustration_at_time": 0.1,  "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": active_ids},
        {"positive": False, "frustration_at_time": 0.08, "context": {"relationship_stage": "stranger", "mutations": []}, "active_patches": active_ids},
        {"positive": True,  "frustration_at_time": 0.12, "context": {"relationship_stage": "familiar", "mutations": []}, "active_patches": active_ids},
        {"positive": True,  "frustration_at_time": 0.15, "context": {"relationship_stage": "familiar", "mutations": []}, "active_patches": active_ids},
    ]

    with open(outcomes_path, "a") as f:
        for r in new_outcomes:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"  写入 {len(new_outcomes)} 条新outcome（带patch标记）")

    # Step 4: 评估
    print("\n── Step 4: 评估补丁效果 ──")
    evaluations = analyzer.evaluate_patches()
    for ev in evaluations:
        action = ev["action"]
        pid = ev["patch_id"]
        if action == "kept":
            print(f"  KEPT {pid} — {ev['note']}")
        elif action == "rolled_back":
            print(f"  ROLLED BACK {pid} — {ev['note']}")
        elif action == "waiting":
            print(f"  WAITING {pid} — {ev['reason']}")
        else:
            print(f"  INCONCLUSIVE {pid} — {ev.get('reason', '')}")

    # 最终状态
    print(f"\n── 最终状态 ──")
    state = analyzer.to_dict()
    print(f"  进化代数: {state['generation']}")
    print(f"  总补丁数: {state['total_patches']}")
    print(f"  活跃: {state['active']} | 回滚: {state['rolled_back']}")

    # 展示一个匹配场景
    print(f"\n── 匹配测试 ──")
    test_ctx = {"frustration_bin": "calm", "stage": "stranger", "has_mutations": False}
    matched = analyzer.match_patches(test_ctx)
    print(f"  场景: {test_ctx}")
    print(f"  匹配到 {len(matched)} 个patch:")
    for p in matched:
        print(f"    {p.patch_id}: {p.prompt_addition[:50]}...")

    # 清理
    import shutil
    shutil.rmtree(tmpdir)
    print(f"\n{'=' * 60}")
    print("  自动进化循环完整演示完成")
    print(f"{'=' * 60}")
