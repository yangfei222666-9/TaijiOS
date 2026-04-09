#!/usr/bin/env python3
"""
震卦恢复引擎 (Zhen Recovery Engine) — 六爻状态机驱动的故障恢复

核心理念：震为雷 ☳☳ — "震惊百里，不丧匕鬯"
巨大冲击来临，不慌乱，不丢失手中之物。

六爻状态机：
  初六·ALERT     → 捕获异常，记录观察，不轻举妄动（阴·Guardian）
  六二·ASSESS    → 评估损害范围，判断局部还是级联（阴·Guardian）
  六三·REACT     → 启动恢复：重试、回滚或降级（阳·Reactor）
  九四·FALLBACK  → 重试失败，切换备用方案（阳·Reactor）
  六五·STABILIZE → 降级稳定运行，核心功能保住（太极·平衡）
  上六·LEARN     → 余震监控，记录教训，进化防御（阴·Guardian）

刚柔相推：
  阳(刚) = Reactor Agent  → 主动出击，执行恢复动作
  阴(柔) = Guardian Agent → 守住边界，防止过度操作
  太极    = Balanced       → 阴阳平衡，系统和谐

Author: TaijiOS
Date: 2026-04-09
"""

import time
import json
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from event_bus import emit, subscribe, get_event_bus, EventType


# ============================================================
# 枚举与常量
# ============================================================

class ZhenYao(Enum):
    """震卦六爻状态"""
    ALERT     = (1, "初六", "震来虩虩", "捕获异常，记录观察")
    ASSESS    = (2, "六二", "震来厉",   "评估损害范围")
    REACT     = (3, "六三", "震苏苏",   "启动恢复动作")
    FALLBACK  = (4, "九四", "震遂泥",   "切换备用方案")
    STABILIZE = (5, "六五", "震往来厉", "降级稳定运行")
    LEARN     = (6, "上六", "震索索",   "记录教训，进化防御")

    def __init__(self, position: int, name_cn: str, yao_ci: str, description: str):
        self.position = position
        self.name_cn = name_cn
        self.yao_ci = yao_ci
        self.description = description


class YinYangForce(str, Enum):
    """阴阳力"""
    YIN = "yin"        # Guardian — 守护
    YANG = "yang"      # Reactor — 行动
    TAIJI = "taiji"    # 平衡


class DamageScope(str, Enum):
    """损害范围"""
    LOCAL = "local"       # 局部故障
    PARTIAL = "partial"   # 部分级联
    CASCADE = "cascade"   # 全面级联


# ============================================================
# 数据结构
# ============================================================

@dataclass
class FaultEvent:
    """故障事件"""
    fault_id: str = field(default_factory=lambda: f"fault-{uuid.uuid4().hex[:8]}")
    source_agent: str = "unknown"
    error_type: str = "unknown"
    severity: str = "medium"     # low / medium / high / critical
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    retry_count: int = 0
    max_retries: int = 3
    context: Dict = field(default_factory=dict)


@dataclass
class RecoveryState:
    """恢复状态追踪"""
    fault: FaultEvent
    current_yao: ZhenYao = ZhenYao.ALERT
    dominant_force: YinYangForce = YinYangForce.YIN
    damage_scope: Optional[DamageScope] = None
    history: List[Dict] = field(default_factory=list)
    strategy: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    completed: bool = False
    success: bool = False
    lesson: Optional[str] = None

    @property
    def elapsed(self) -> float:
        return time.time() - self.started_at

    def record(self, yao: ZhenYao, action: str, result: str):
        self.history.append({
            "yao": yao.name,
            "yao_cn": yao.name_cn,
            "action": action,
            "result": result,
            "timestamp": time.time(),
            "force": self.dominant_force.value,
        })


# ============================================================
# Guardian Agent（阴·守护）
# ============================================================

class GuardianAgent:
    """
    阴性 Agent：守住边界，防止过度操作

    职责：
    - 损害评估
    - 断路器管理
    - 三重安全检查（断路器 + 重试上限 + 时间窗口）
    """

    def __init__(self):
        self.circuit_breakers: Dict[str, Dict] = {}  # agent_id -> {open_until, trip_count}
        self.fault_window: List[FaultEvent] = []
        self.window_sec = 60

    def assess_damage(self, fault: FaultEvent) -> DamageScope:
        """
        损害评估

        60 秒窗口内统计：
        - critical 或 total > 10 → cascade
        - same_source > 3 或 high → partial
        - 其他 → local
        """
        now = time.time()
        # 清理过期事件
        self.fault_window = [
            f for f in self.fault_window
            if now - f.timestamp < self.window_sec
        ]
        self.fault_window.append(fault)

        total_recent = len(self.fault_window)
        same_source = sum(
            1 for f in self.fault_window
            if f.source_agent == fault.source_agent
        )

        if fault.severity == "critical" or total_recent > 10:
            return DamageScope.CASCADE
        elif same_source > 3 or fault.severity == "high":
            return DamageScope.PARTIAL
        else:
            return DamageScope.LOCAL

    def check_recovery_safety(self, state: RecoveryState) -> bool:
        """
        三重安全检查

        1. 断路器：该 Agent 是否在冷却期
        2. 重试上限：是否已达 max_retries
        3. 时间窗口：恢复是否超过 5 分钟
        """
        agent_id = state.fault.source_agent

        # 1. 断路器检查
        cb = self.circuit_breakers.get(agent_id, {})
        if time.time() < cb.get("open_until", 0):
            return False

        # 2. 重试上限
        if state.fault.retry_count >= state.fault.max_retries:
            return False

        # 3. 时间窗口（5 分钟）
        if state.elapsed > 300:
            return False

        return True

    def trip_circuit_breaker(self, agent_id: str, cooldown_sec: int = 60):
        """触发断路器"""
        cb = self.circuit_breakers.get(agent_id, {"trip_count": 0})
        cb["trip_count"] = cb.get("trip_count", 0) + 1
        cb["open_until"] = time.time() + cooldown_sec
        self.circuit_breakers[agent_id] = cb

        emit("recovery.circuit_breaker_tripped", {
            "agent_id": agent_id,
            "cooldown_sec": cooldown_sec,
            "trip_count": cb["trip_count"],
        })


# ============================================================
# Reactor Agent（阳·行动）
# ============================================================

class ReactorAgent:
    """
    阳性 Agent：主动出击，执行恢复动作

    职责：
    - 重试（指数退避）
    - 回滚
    - 降级
    - 切换备用 Agent
    """

    def retry_task(self, fault: FaultEvent) -> bool:
        """
        重试任务（模拟指数退避）

        Returns: True=成功, False=失败
        """
        backoff = min(2 ** fault.retry_count, 30)
        fault.retry_count += 1

        emit("recovery.retry", {
            "fault_id": fault.fault_id,
            "agent": fault.source_agent,
            "retry_count": fault.retry_count,
            "backoff_sec": backoff,
        })

        # 模拟：根据严重程度决定成功率
        # 实际中这里应该调用真实的任务重执行
        if fault.severity == "low":
            return True  # 低严重度通常重试成功
        elif fault.severity == "medium" and fault.retry_count <= 2:
            return True  # 中等严重度前两次可能成功
        return False

    def rollback(self, fault: FaultEvent) -> bool:
        """回滚到上一个检查点"""
        emit("recovery.rollback", {
            "fault_id": fault.fault_id,
            "agent": fault.source_agent,
        })
        # 模拟：回滚通常成功
        return True

    def degrade(self, fault: FaultEvent) -> bool:
        """降级服务"""
        emit(EventType.AGENT_DEGRADED, {
            "fault_id": fault.fault_id,
            "agent": fault.source_agent,
            "reason": f"震卦降级: {fault.error_type}",
        })
        return True

    def activate_fallback(self, fault: FaultEvent) -> bool:
        """激活备用 Agent"""
        emit("recovery.fallback_activated", {
            "fault_id": fault.fault_id,
            "original_agent": fault.source_agent,
            "fallback_agent": f"{fault.source_agent}_backup",
        })
        return True


# ============================================================
# 震卦恢复引擎（核心状态机）
# ============================================================

class ZhenRecoveryEngine:
    """
    核心状态机：驱动六爻流转

    故障事件 → 初六·ALERT → 六二·ASSESS → 六三·REACT
              → 九四·FALLBACK → 六五·STABILIZE → 上六·LEARN
    """

    def __init__(self):
        self.guardian = GuardianAgent()
        self.reactor = ReactorAgent()
        self.recovery_log: List[RecoveryState] = []
        self.data_dir = Path(__file__).parent / "data"
        self._register_event_handlers()

    def _register_event_handlers(self):
        """注册 EventBus 事件处理器"""
        subscribe(EventType.AGENT_FAILED, self._on_agent_failed)
        subscribe(EventType.SYSTEM_CRITICAL, self._on_system_critical)
        subscribe(EventType.TASK_FAILED, self._on_task_failed)

    def _on_agent_failed(self, event: Dict):
        """处理 Agent 失败事件"""
        data = event.get("data", {})
        fault = FaultEvent(
            source_agent=data.get("agent", "unknown"),
            error_type=data.get("error_type", "agent_failure"),
            severity=data.get("severity", "medium"),
            message=data.get("message", ""),
        )
        self.recover(fault)

    def _on_system_critical(self, event: Dict):
        """处理系统严重事件"""
        data = event.get("data", {})
        fault = FaultEvent(
            source_agent=data.get("source", "system"),
            error_type="system_critical",
            severity="critical",
            message=data.get("message", "System critical event"),
        )
        self.recover(fault)

    def _on_task_failed(self, event: Dict):
        """处理任务失败事件"""
        data = event.get("data", {})
        fault = FaultEvent(
            source_agent=data.get("agent", "unknown"),
            error_type=data.get("error_type", "task_failure"),
            severity=data.get("severity", "medium"),
            message=data.get("message", ""),
        )
        self.recover(fault)

    def recover(self, fault: FaultEvent) -> RecoveryState:
        """
        完整恢复流程：六爻状态机逐步推进

        Returns: 恢复状态
        """
        state = RecoveryState(fault=fault)

        # ── 颐卦反哺：查询历史经验 ──
        yi_advice = self._query_yi(fault)
        if yi_advice:
            state.record(ZhenYao.ALERT, "颐卦建议", yi_advice)

        # ── 初六·ALERT ── 阴·Guardian：记录异常，不行动
        state.current_yao = ZhenYao.ALERT
        state.dominant_force = YinYangForce.YIN
        state.record(ZhenYao.ALERT, "捕获异常", f"来源: {fault.source_agent}, 类型: {fault.error_type}")

        emit("recovery.yao_transition", {
            "fault_id": fault.fault_id,
            "yao": "ALERT",
            "yao_cn": "初六·震来虩虩",
            "force": "yin",
        })

        # ── 六二·ASSESS ── 阴·Guardian：评估损害
        state.current_yao = ZhenYao.ASSESS
        state.damage_scope = self.guardian.assess_damage(fault)
        state.record(ZhenYao.ASSESS, "损害评估", f"范围: {state.damage_scope.value}")

        emit("recovery.yao_transition", {
            "fault_id": fault.fault_id,
            "yao": "ASSESS",
            "yao_cn": "六二·震来厉",
            "damage_scope": state.damage_scope.value,
        })

        # 级联故障 → 跳至九四 FALLBACK
        if state.damage_scope == DamageScope.CASCADE:
            state.record(ZhenYao.ASSESS, "级联检测", "全面级联 → 跳至九四备用")
            return self._yao_4_fallback(state)

        # ── 六三·REACT ── 阳·Reactor（先问阴是否安全）
        state.current_yao = ZhenYao.REACT
        state.dominant_force = YinYangForce.YANG

        # Guardian 安全检查
        is_safe = self.guardian.check_recovery_safety(state)
        if not is_safe:
            state.record(ZhenYao.REACT, "安全检查", "不安全 → 跳至六五降级")
            return self._yao_5_stabilize(state)

        emit("recovery.yao_transition", {
            "fault_id": fault.fault_id,
            "yao": "REACT",
            "yao_cn": "六三·震苏苏",
            "force": "yang",
        })

        # 根据损害范围选择恢复策略
        if state.damage_scope == DamageScope.LOCAL:
            state.strategy = "retry"
            success = self.reactor.retry_task(fault)
        elif state.damage_scope == DamageScope.PARTIAL:
            state.strategy = "rollback"
            success = self.reactor.rollback(fault)
        else:
            state.strategy = "retry"
            success = self.reactor.retry_task(fault)

        state.record(ZhenYao.REACT, f"恢复: {state.strategy}", "成功" if success else "失败")

        if success:
            state.success = True
            return self._yao_6_learn(state)

        # 恢复失败 → 九四 FALLBACK
        return self._yao_4_fallback(state)

    def _yao_4_fallback(self, state: RecoveryState) -> RecoveryState:
        """九四·FALLBACK — 阳·Reactor：断路器跳闸 + 切换备用"""
        state.current_yao = ZhenYao.FALLBACK
        state.dominant_force = YinYangForce.YANG

        emit("recovery.yao_transition", {
            "fault_id": state.fault.fault_id,
            "yao": "FALLBACK",
            "yao_cn": "九四·震遂泥",
            "force": "yang",
        })

        # 断路器跳闸
        self.guardian.trip_circuit_breaker(state.fault.source_agent)
        state.record(ZhenYao.FALLBACK, "断路器跳闸", state.fault.source_agent)

        # 尝试激活备用 Agent
        fallback_ok = self.reactor.activate_fallback(state.fault)
        state.record(ZhenYao.FALLBACK, "激活备用", "成功" if fallback_ok else "失败")

        if fallback_ok:
            state.success = True
            return self._yao_6_learn(state)

        # 备用也失败 → 降级
        return self._yao_5_stabilize(state)

    def _yao_5_stabilize(self, state: RecoveryState) -> RecoveryState:
        """六五·STABILIZE — 太极：降级稳定运行"""
        state.current_yao = ZhenYao.STABILIZE
        state.dominant_force = YinYangForce.TAIJI

        emit("recovery.yao_transition", {
            "fault_id": state.fault.fault_id,
            "yao": "STABILIZE",
            "yao_cn": "六五·震往来厉",
            "force": "taiji",
        })

        self.reactor.degrade(state.fault)
        state.record(ZhenYao.STABILIZE, "降级运行", "核心功能保住，非关键功能暂停")
        state.success = False  # 降级不算完全成功

        return self._yao_6_learn(state)

    def _yao_6_learn(self, state: RecoveryState) -> RecoveryState:
        """上六·LEARN — 阴·Guardian：记录教训，进化防御"""
        state.current_yao = ZhenYao.LEARN
        state.dominant_force = YinYangForce.YIN
        state.completed = True

        emit("recovery.yao_transition", {
            "fault_id": state.fault.fault_id,
            "yao": "LEARN",
            "yao_cn": "上六·震索索",
            "force": "yin",
        })

        # 提炼教训
        lesson = self._extract_lesson(state)
        state.lesson = lesson
        state.record(ZhenYao.LEARN, "教训提炼", lesson)

        # 持久化教训
        self._persist_lesson(state)

        # 发布学习事件
        emit("recovery.lesson_learned", {
            "fault_id": state.fault.fault_id,
            "agent": state.fault.source_agent,
            "lesson": lesson,
            "success": state.success,
            "yao_path": [h["yao"] for h in state.history],
        })

        # 记录到恢复日志
        self.recovery_log.append(state)

        return state

    def _query_yi(self, fault: FaultEvent) -> Optional[str]:
        """查询颐卦经验库获取历史建议"""
        try:
            from engine_registry import get_registry
            registry = get_registry()
            if registry and hasattr(registry, 'yi_engine'):
                results = registry.yi_engine.query({
                    "source": "zhen",
                    "error_type": fault.error_type,
                })
                if results:
                    best = results[0]
                    return f"历史经验(w={best.weight:.2f}): {best.lesson}"
        except Exception:
            pass
        return None

    def _extract_lesson(self, state: RecoveryState) -> str:
        """
        教训提炼 — 优先用 LLM 深度分析，fallback 到模板

        LLM 模式：用 Claude haiku 生成一句精准教训
        模板模式：当 API 不可用时使用
        """
        agent = state.fault.source_agent
        error = state.fault.error_type

        # 尝试 LLM 深度教训
        try:
            from llm_caller import call_llm, is_llm_available
            if is_llm_available():
                system_prompt = (
                    "你是 TaijiOS 震卦恢复引擎的教训分析师。\n"
                    "根据故障恢复过程，提炼一句精准、可操作的教训（30字以内）。\n"
                    "只输出教训本身，不要有任何前缀或解释。"
                )
                yao_path = " → ".join(h["yao"] for h in state.history)
                user_prompt = (
                    f"故障 Agent: {agent}\n"
                    f"错误类型: {error}\n"
                    f"严重程度: {state.fault.severity}\n"
                    f"损害范围: {state.damage_scope.value if state.damage_scope else 'unknown'}\n"
                    f"恢复策略: {state.strategy or 'N/A'}\n"
                    f"恢复结果: {'成功' if state.success else '失败/降级'}\n"
                    f"重试次数: {state.fault.retry_count}\n"
                    f"爻位路径: {yao_path}\n"
                    f"错误信息: {state.fault.message}"
                )
                lesson = call_llm(system_prompt, user_prompt,
                                  model="claude-haiku-4-5", max_tokens=100)
                if not lesson.startswith("[LLM_ERROR]"):
                    return lesson.strip()
        except Exception:
            pass

        # Fallback 模板
        if state.success and state.fault.retry_count <= 1:
            return f"{agent} 的 {error} 可通过简单重试解决"
        elif state.success and state.fault.retry_count > 1:
            return f"{agent} 需要多次重试，建议增加超时容忍度"
        elif state.damage_scope == DamageScope.CASCADE:
            return f"{agent} 触发级联故障，需检查上下游依赖隔离性"
        else:
            return f"{agent} 的 {error} 无法自动恢复，需人工介入"

    def _persist_lesson(self, state: RecoveryState):
        """持久化教训到 agent_system/data/"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        lesson_file = self.data_dir / f"lesson_{state.fault.fault_id}.json"

        lesson_data = {
            "fault_id": state.fault.fault_id,
            "source_agent": state.fault.source_agent,
            "error_type": state.fault.error_type,
            "severity": state.fault.severity,
            "damage_scope": state.damage_scope.value if state.damage_scope else None,
            "strategy": state.strategy,
            "success": state.success,
            "lesson": state.lesson,
            "yao_path": [h["yao"] for h in state.history],
            "duration_sec": state.elapsed,
            "timestamp": time.time(),
            "tags": [
                "#error",
                f"#agent/{state.fault.source_agent}",
                "#震卦",
            ],
            "type": "pattern",
        }

        with open(lesson_file, "w", encoding="utf-8") as f:
            json.dump(lesson_data, f, ensure_ascii=False, indent=2)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== 震卦恢复引擎测试 ===\n")

    engine = ZhenRecoveryEngine()

    # 场景 1：局部故障（低严重度）
    print("场景 1：局部故障")
    fault1 = FaultEvent(
        source_agent="coder",
        error_type="api_timeout",
        severity="low",
        message="Claude API 超时",
    )
    state1 = engine.recover(fault1)
    print(f"  结果: {'成功' if state1.success else '降级'}")
    print(f"  教训: {state1.lesson}")
    print(f"  爻位路径: {' → '.join(h['yao'] for h in state1.history)}")
    print()

    # 场景 2：中等故障
    print("场景 2：中等故障（多次重试）")
    fault2 = FaultEvent(
        source_agent="monitor",
        error_type="connection_reset",
        severity="medium",
        message="连接被重置",
    )
    state2 = engine.recover(fault2)
    print(f"  结果: {'成功' if state2.success else '降级'}")
    print(f"  教训: {state2.lesson}")
    print(f"  爻位路径: {' → '.join(h['yao'] for h in state2.history)}")
    print()

    # 场景 3：级联故障
    print("场景 3：级联故障（critical）")
    fault3 = FaultEvent(
        source_agent="scheduler",
        error_type="system_crash",
        severity="critical",
        message="调度器崩溃",
    )
    state3 = engine.recover(fault3)
    print(f"  结果: {'成功' if state3.success else '降级'}")
    print(f"  教训: {state3.lesson}")
    print(f"  爻位路径: {' → '.join(h['yao'] for h in state3.history)}")

    print(f"\n恢复日志总数: {len(engine.recovery_log)}")
    print("\n✅ 震卦恢复引擎测试完成")
