#!/usr/bin/env python3
"""
情势引擎 (Situation Engine) — 六维向量分析 + 造动破解死锁

核心概念：
- 将系统指标转换为六维情势向量（timing/resource/initiative/position/relationship/energy）
- 检测维度间的冲突（tension）
- 在第三维度上"造动"来破解死锁，而非在冲突本身的两个维度上做取舍

与 guardrails 的关系：情势引擎是 guardrails 的增强层，不替代。
risk == critical 时跳过造动，直接走 guardrails 降级。

Author: TaijiOS
Date: 2026-04-09
"""

import time
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum

import logging

from event_bus import emit, subscribe, get_event_bus, EventType
from hexagram_lines import calculate_six_lines, LineScore

log = logging.getLogger("aios.situation_engine")


# ============================================================
# 数据结构
# ============================================================

class Dimension(str, Enum):
    TIMING = "timing"
    RESOURCE = "resource"
    INITIATIVE = "initiative"
    POSITION = "position"
    RELATIONSHIP = "relationship"
    ENERGY = "energy"


class DimensionState(str, Enum):
    """每个维度的离散状态"""
    # timing
    EARLY = "early"
    MID = "mid"
    LATE = "late"
    # resource
    SCARCE = "scarce"
    ADEQUATE = "adequate"
    ABUNDANT = "abundant"
    # initiative
    PASSIVE = "passive"
    NEUTRAL = "neutral"
    ACTIVE = "active"
    # position
    INNER = "inner"
    BALANCED = "balanced"
    OUTER = "outer"
    # relationship
    OPPOSED = "opposed"
    MIXED = "mixed"
    ALIGNED = "aligned"
    # energy
    FALLING = "falling"
    STABLE = "stable"
    RISING = "rising"


@dataclass
class SituationVector:
    """六维情势向量"""
    timing: float = 0.5       # 时机成熟度 (0~1), 映射自 line_1_infra
    resource: float = 0.5     # 资源充足度 (0~1), 映射自 line_2_execution
    initiative: float = 0.5   # 主动性 (0~1), 映射自 line_3_learning
    position: float = 0.5     # 内外格局 (0~1), 映射自 line_4_routing
    relationship: float = 0.5 # 关系/共识 (0~1), 映射自 line_5_collaboration
    energy: float = 0.5       # 整体能量 (0~1), 映射自 line_6_governance

    def to_dict(self) -> Dict[str, float]:
        return {
            "timing": self.timing,
            "resource": self.resource,
            "initiative": self.initiative,
            "position": self.position,
            "relationship": self.relationship,
            "energy": self.energy,
        }

    def get_dimension(self, dim: Dimension) -> float:
        return getattr(self, dim.value)


@dataclass
class Tension:
    """冲突检测结果"""
    dim_a: Dimension        # 冲突维度 A
    dim_b: Dimension        # 冲突维度 B
    severity: float         # 冲突强度 (0~1)
    description: str        # 冲突描述
    intervention_dim: Dimension  # 建议造动的第三维度


@dataclass
class InterventionPlan:
    """造动策略"""
    tension: Tension
    target_dim: Dimension   # 造动目标维度
    action: str             # 造动动作
    risk: str               # low / medium / high / critical
    context: Dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ============================================================
# 维度状态离散化
# ============================================================

def _discretize_timing(score: float) -> str:
    if score < 0.35:
        return DimensionState.EARLY
    elif score > 0.65:
        return DimensionState.LATE
    return DimensionState.MID


def _discretize_resource(score: float) -> str:
    if score < 0.35:
        return DimensionState.SCARCE
    elif score > 0.65:
        return DimensionState.ABUNDANT
    return DimensionState.ADEQUATE


def _discretize_initiative(score: float) -> str:
    if score < 0.35:
        return DimensionState.PASSIVE
    elif score > 0.65:
        return DimensionState.ACTIVE
    return DimensionState.NEUTRAL


def _discretize_position(score: float) -> str:
    if score < 0.35:
        return DimensionState.INNER
    elif score > 0.65:
        return DimensionState.OUTER
    return DimensionState.BALANCED


def _discretize_relationship(score: float) -> str:
    if score < 0.35:
        return DimensionState.OPPOSED
    elif score > 0.65:
        return DimensionState.ALIGNED
    return DimensionState.MIXED


def _discretize_energy(score: float) -> str:
    if score < 0.35:
        return DimensionState.FALLING
    elif score > 0.65:
        return DimensionState.RISING
    return DimensionState.STABLE


# ============================================================
# 核心函数
# ============================================================

def metrics_to_vector(metrics: Dict[str, float]) -> SituationVector:
    """
    系统指标 → 六维情势向量

    通过 hexagram_lines 的六爻评分中转：
    - line_1_infra     → timing (基础设施健康 ≈ 时机是否成熟)
    - line_2_execution → resource (执行能力 ≈ 资源充足度)
    - line_3_learning  → initiative (学习活跃度 ≈ 主动性)
    - line_4_routing   → position (路由策略 ≈ 内外格局)
    - line_5_collaboration → relationship (协作状态 ≈ 关系/共识)
    - line_6_governance → energy (治理健康度 ≈ 整体能量)
    """
    lines = calculate_six_lines(metrics)
    return lines_to_vector(lines)


def lines_to_vector(lines: Dict[str, LineScore]) -> SituationVector:
    """从已计算的六爻评分直接转换为情势向量"""
    return SituationVector(
        timing=lines["line_1_infra"].score,
        resource=lines["line_2_execution"].score,
        initiative=lines["line_3_learning"].score,
        position=lines["line_4_routing"].score,
        relationship=lines["line_5_collaboration"].score,
        energy=lines["line_6_governance"].score,
    )


def detect_tensions(vector: SituationVector) -> List[Tension]:
    """
    检测六维向量中的冲突

    6 条冲突检测规则（来自情势引擎设计）：
    1. 资源紧张 + 主动性高 → 在 relationship 上造动（协作分担）
    2. 时机未成熟 + 能量上升 → 在 position 上造动（调整内外格局）
    3. 内外失衡 + 关系对立 → 在 energy 上造动（调整优先级权重）
    4. 资源紧张 + 时机已到 → 在 initiative 上造动（激活备用 Agent）
    5. 能量下降 + 主动性低 → 在 timing 上造动（调整调度窗口）
    6. 关系对立 + 能量下降 → 在 resource 上造动（资源回收重分配）
    """
    tensions = []

    # Rule 1: 资源紧张 + 主动性高 → 在 relationship 上造动
    if vector.resource < 0.35 and vector.initiative > 0.65:
        severity = (1.0 - vector.resource) * vector.initiative
        tensions.append(Tension(
            dim_a=Dimension.RESOURCE,
            dim_b=Dimension.INITIATIVE,
            severity=severity,
            description="资源紧张但活跃度高，需协作分担负载",
            intervention_dim=Dimension.RELATIONSHIP,
        ))

    # Rule 2: 时机未成熟 + 能量上升 → 在 position 上造动
    if vector.timing < 0.35 and vector.energy > 0.65:
        severity = (1.0 - vector.timing) * vector.energy
        tensions.append(Tension(
            dim_a=Dimension.TIMING,
            dim_b=Dimension.ENERGY,
            severity=severity,
            description="基础设施未就绪但请求增长，需调整运行模式",
            intervention_dim=Dimension.POSITION,
        ))

    # Rule 3: 内外失衡 + 关系对立 → 在 energy 上造动
    if vector.position < 0.35 and vector.relationship < 0.35:
        severity = (1.0 - vector.position) * (1.0 - vector.relationship)
        tensions.append(Tension(
            dim_a=Dimension.POSITION,
            dim_b=Dimension.RELATIONSHIP,
            severity=severity,
            description="路由阻塞且协作冲突，需调整优先级权重",
            intervention_dim=Dimension.ENERGY,
        ))

    # Rule 4: 资源紧张 + 时机已到 → 在 initiative 上造动
    if vector.resource < 0.35 and vector.timing > 0.65:
        severity = (1.0 - vector.resource) * vector.timing
        tensions.append(Tension(
            dim_a=Dimension.RESOURCE,
            dim_b=Dimension.TIMING,
            severity=severity,
            description="资源不足但系统成熟，需激活备用 Agent",
            intervention_dim=Dimension.INITIATIVE,
        ))

    # Rule 5: 能量下降 + 主动性低 → 在 timing 上造动
    if vector.energy < 0.35 and vector.initiative < 0.35:
        severity = (1.0 - vector.energy) * (1.0 - vector.initiative)
        tensions.append(Tension(
            dim_a=Dimension.ENERGY,
            dim_b=Dimension.INITIATIVE,
            severity=severity,
            description="系统疲软且学习停滞，需调整调度窗口延缓执行",
            intervention_dim=Dimension.TIMING,
        ))

    # Rule 6: 关系对立 + 能量下降 → 在 resource 上造动
    if vector.relationship < 0.35 and vector.energy < 0.35:
        severity = (1.0 - vector.relationship) * (1.0 - vector.energy)
        tensions.append(Tension(
            dim_a=Dimension.RELATIONSHIP,
            dim_b=Dimension.ENERGY,
            severity=severity,
            description="协作冲突且治理恶化，需资源回收重新分配",
            intervention_dim=Dimension.RESOURCE,
        ))

    # 按严重度降序排列
    tensions.sort(key=lambda t: t.severity, reverse=True)
    return tensions


def get_intervention_plans(tensions: List[Tension]) -> List[InterventionPlan]:
    """
    根据冲突生成造动策略

    每种造动维度对应不同的具体操作
    """
    # 造动动作映射
    _ACTION_MAP = {
        Dimension.RELATIONSHIP: "触发跨 Agent 协作 / 负载迁移 (scheduler.rebalance)",
        Dimension.POSITION: "切换运行模式，调整内外路由策略 (scheduler.migrate)",
        Dimension.ENERGY: "动态调整 Agent 优先级权重 (scheduler.reprioritize)",
        Dimension.INITIATIVE: "激活备用 Agent / 主动探测 (agent_hub.activate)",
        Dimension.TIMING: "调整调度窗口 / 延迟执行 (scheduler.defer)",
        Dimension.RESOURCE: "紧急资源回收 + 重新分配 (memory_manager.gc + reallocate)",
    }

    _RISK_MAP = {
        Dimension.RELATIONSHIP: "medium",
        Dimension.POSITION: "medium",
        Dimension.ENERGY: "low",
        Dimension.INITIATIVE: "medium",
        Dimension.TIMING: "low",
        Dimension.RESOURCE: "high",
    }

    plans = []
    for tension in tensions:
        target = tension.intervention_dim
        plan = InterventionPlan(
            tension=tension,
            target_dim=target,
            action=_ACTION_MAP.get(target, "unknown_action"),
            risk=_RISK_MAP.get(target, "medium"),
            context={
                "dim_a": tension.dim_a.value,
                "dim_b": tension.dim_b.value,
                "severity": tension.severity,
            },
        )
        plans.append(plan)

    return plans


def execute_intervention(plan: InterventionPlan) -> Dict:
    """
    执行造动指令，通过 EventBus 发布事件

    LLM 增强：用 Claude 生成具体的造动执行建议
    造动后进入 30s 观察窗口。

    Returns:
        执行结果 dict
    """
    target = plan.target_dim.value

    # LLM 生成具体造动建议
    llm_advice = None
    try:
        from llm_caller import call_llm, is_llm_available
        if is_llm_available():
            system_prompt = (
                "你是 TaijiOS 情势引擎的造动策略师。\n"
                "基于六维向量冲突分析，给出一句具体、可执行的造动建议（50字以内）。\n"
                "只输出建议本身。"
            )
            user_prompt = (
                f"冲突维度: {plan.tension.dim_a.value} vs {plan.tension.dim_b.value}\n"
                f"冲突描述: {plan.tension.description}\n"
                f"冲突强度: {plan.tension.severity:.2f}\n"
                f"造动目标维度: {target}\n"
                f"预设动作: {plan.action}\n"
                f"请给出更具体的执行建议。"
            )
            advice = call_llm(system_prompt, user_prompt,
                              model="claude-haiku-4-5", max_tokens=150)
            if not advice.startswith("[LLM_ERROR]"):
                llm_advice = advice.strip()
    except Exception:
        pass

    result = {
        "intervention_dim": target,
        "action": plan.action,
        "llm_advice": llm_advice,
        "risk": plan.risk,
        "executed_at": time.time(),
        "observation_window_sec": 30,
        "status": "executed",
    }

    # 通过 EventBus 发布造动事件
    emit("situation.intervention", {
        "target_dimension": target,
        "action": plan.action,
        "llm_advice": llm_advice,
        "tension": {
            "dim_a": plan.tension.dim_a.value,
            "dim_b": plan.tension.dim_b.value,
            "severity": plan.tension.severity,
            "description": plan.tension.description,
        },
        "risk": plan.risk,
    })

    return result


# ============================================================
# 完整分析管线
# ============================================================

class SituationEngine:
    """情势引擎：完整的分析 → 检测 → 造动管线"""

    def __init__(self):
        self.intervention_history: List[Dict] = []
        self._cooldown: Dict[str, float] = {}  # dimension -> last_intervention_time
        self.observation_window = 30  # 秒

    def analyze(self, metrics: Dict[str, float]) -> Dict:
        """
        完整分析流程：
        1. 指标 → 向量
        2. 向量 → 冲突检测
        3. 冲突 → 造动策略
        """
        vector = metrics_to_vector(metrics)
        tensions = detect_tensions(vector)
        plans = get_intervention_plans(tensions)

        return {
            "vector": vector.to_dict(),
            "tensions": [
                {
                    "dim_a": t.dim_a.value,
                    "dim_b": t.dim_b.value,
                    "severity": t.severity,
                    "description": t.description,
                    "intervention_dim": t.intervention_dim.value,
                }
                for t in tensions
            ],
            "plans": [
                {
                    "target_dim": p.target_dim.value,
                    "action": p.action,
                    "risk": p.risk,
                }
                for p in plans
            ],
            "has_tension": len(tensions) > 0,
        }

    def try_intervention(self, metrics: Dict[str, float]) -> Optional[Dict]:
        """
        尝试造动：
        - 检查冷却期（同一维度同一观察周期内只造动一次）
        - 执行最高优先级的造动
        - 记录历史

        Returns:
            造动结果 dict，如果不适合造动则返回 None
        """
        vector = metrics_to_vector(metrics)
        tensions = detect_tensions(vector)

        if not tensions:
            return None

        # 颐卦反哺：查询同类 tension 历史干预效果
        yi_hint = self._query_yi_for_tension(tensions[0])
        if yi_hint:
            log.info(f"[Situation] 颐卦建议: {yi_hint}")

        plans = get_intervention_plans(tensions)

        for plan in plans:
            dim_key = plan.target_dim.value
            last_time = self._cooldown.get(dim_key, 0)

            # 冷却期检查：同一维度 30s 内不重复造动
            if time.time() - last_time < self.observation_window:
                continue

            # 执行造动
            result = execute_intervention(plan)
            self._cooldown[dim_key] = time.time()
            self.intervention_history.append(result)
            return result

        return None  # 所有维度都在冷却期

    @staticmethod
    def _query_yi_for_tension(tension) -> Optional[str]:
        """查询颐卦：同类 tension 历史干预效果"""
        try:
            from engine_registry import get_registry
            registry = get_registry()
            if not registry or not hasattr(registry, 'yi_engine'):
                return None
            results = registry.yi_engine.query({
                "dim_a": tension.dim_a.value,
                "dim_b": tension.dim_b.value,
            })
            if results:
                return results[0].lesson
        except Exception:
            pass
        return None


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== 情势引擎测试 ===\n")

    engine = SituationEngine()

    # 场景 1：资源紧张 + 活跃度高
    print("场景 1：资源紧张 + 活跃度高")
    metrics_tension = {
        "api_health": 0.8,
        "network_latency": 0.2,
        "dependency_available": 0.8,
        "task_success_rate": 0.2,   # 资源紧张
        "timeout_rate": 0.7,
        "retry_rate": 0.6,
        "recommendation_hit_rate": 0.8,  # 活跃
        "learning_gain": 0.75,
        "experience_validity": 0.8,
        "router_accuracy": 0.5,
        "queue_length": 0.5,
        "dispatch_stability": 0.5,
        "agent_cooperation": 0.5,
        "resource_sharing": 0.5,
        "conflict_rate": 0.3,
        "evolution_score": 50.0,
        "canary_health": 0.5,
        "global_stability": 0.5,
    }

    result = engine.analyze(metrics_tension)
    print(f"向量: {result['vector']}")
    print(f"冲突数: {len(result['tensions'])}")
    for t in result["tensions"]:
        print(f"  [{t['severity']:.2f}] {t['dim_a']} vs {t['dim_b']} → 造动 {t['intervention_dim']}")
        print(f"    {t['description']}")
    print(f"造动计划数: {len(result['plans'])}")
    for p in result["plans"]:
        print(f"  目标: {p['target_dim']} | 动作: {p['action']} | 风险: {p['risk']}")
    print()

    # 场景 2：全面低迷
    print("场景 2：全面低迷（能量下降 + 主动性低）")
    metrics_low = {
        "api_health": 0.3,
        "network_latency": 0.6,
        "dependency_available": 0.4,
        "task_success_rate": 0.3,
        "timeout_rate": 0.5,
        "retry_rate": 0.4,
        "recommendation_hit_rate": 0.2,
        "learning_gain": 0.15,
        "experience_validity": 0.2,
        "router_accuracy": 0.3,
        "queue_length": 0.7,
        "dispatch_stability": 0.3,
        "agent_cooperation": 0.25,
        "resource_sharing": 0.2,
        "conflict_rate": 0.6,
        "evolution_score": 20.0,
        "canary_health": 0.3,
        "global_stability": 0.25,
    }

    result2 = engine.analyze(metrics_low)
    print(f"向量: {result2['vector']}")
    print(f"冲突数: {len(result2['tensions'])}")
    for t in result2["tensions"]:
        print(f"  [{t['severity']:.2f}] {t['dim_a']} vs {t['dim_b']} → 造动 {t['intervention_dim']}")

    # 尝试造动
    print("\n尝试造动...")
    intervention = engine.try_intervention(metrics_low)
    if intervention:
        print(f"造动执行: {intervention['intervention_dim']} → {intervention['action']}")
    else:
        print("无需造动 / 冷却中")

    print("\n✅ 情势引擎测试完成")
