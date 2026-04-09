#!/usr/bin/env python3
"""
引擎注册中心 (Engine Registry) — 统一管理四引擎

职责：
- 注册并管理四引擎（情势/震卦/师卦/Persona）
- 统一初始化 + EventBus 订阅
- 根据事件类型路由到对应引擎

路由规则：
- critical / 故障事件   → 震卦恢复引擎
- tension / 死锁        → 情势引擎造动
- 多 Agent 协作任务     → 师卦协作引擎
- Agent 选人 / 匹配     → Persona 层
- normal                → 放行

Author: TaijiOS
Date: 2026-04-09
"""

import time
from pathlib import Path
from typing import Dict, Optional, Any

from event_bus import emit, subscribe, get_event_bus, EventType
from situation_engine import SituationEngine
from zhen_recovery_engine import ZhenRecoveryEngine, FaultEvent
from shi_swarm_engine import ShiSwarmEngine, MissionLaw
from agent_persona import PersonaLoader, enhance_agents_with_persona
from yi_learning_engine import YiLearningEngine


class EngineRegistry:
    """四引擎统一注册与管理"""

    def __init__(self, agents_json_path: str = None):
        self.agents_json_path = agents_json_path or str(
            Path(__file__).parent / "agents.json"
        )

        # 初始化五引擎
        self.situation_engine = SituationEngine()
        self.zhen_engine = ZhenRecoveryEngine()
        self.shi_engine = ShiSwarmEngine(self.agents_json_path)
        self.yi_engine = YiLearningEngine()
        self.personas = {}

        # 加载 Persona
        try:
            self.personas = PersonaLoader.load_from_agents_json(self.agents_json_path)
        except Exception as e:
            print(f"⚠️ Persona 加载失败: {e}")

        self.initialized = True
        self.stats = {
            "situation_calls": 0,
            "zhen_calls": 0,
            "shi_calls": 0,
            "persona_queries": 0,
            "yi_queries": 0,
            "yi_digests": 0,
        }

    def route_event(self, event_type: str, data: Dict = None) -> Dict:
        """
        根据事件类型路由到对应引擎

        Returns:
            路由结果
        """
        data = data or {}
        result = {"routed_to": None, "action": None, "details": {}}

        # 故障/严重事件 → 震卦
        if event_type in (EventType.AGENT_FAILED, EventType.SYSTEM_CRITICAL,
                          EventType.TASK_FAILED, "fault"):
            result["routed_to"] = "zhen_recovery"
            fault = FaultEvent(
                source_agent=data.get("agent", data.get("source", "unknown")),
                error_type=data.get("error_type", event_type),
                severity=data.get("severity", "medium"),
                message=data.get("message", ""),
            )
            state = self.zhen_engine.recover(fault)
            self.stats["zhen_calls"] += 1
            result["action"] = "recovery"
            result["details"] = {
                "success": state.success,
                "lesson": state.lesson,
                "yao_path": [h["yao"] for h in state.history],
            }

        # 多 Agent 任务 → 师卦
        elif event_type in ("mission", "multi_agent_task", "shi.execute"):
            result["routed_to"] = "shi_swarm"
            law = MissionLaw(
                objective=data.get("objective", ""),
                constraints=data.get("constraints", []),
                output_schema=data.get("output_schema", {"result": "any"}),
                conflict_policy=data.get("conflict_policy", "vote"),
            )
            mission = self.shi_engine.execute_mission(law, data.get("executor"))
            self.stats["shi_calls"] += 1
            result["action"] = "swarm_execute"
            result["details"] = {
                "status": mission.status.value,
                "squad": [s.agent_id for s in mission.squad],
                "conflicts": len(mission.conflicts),
                "final_output": mission.final_output,
            }

        # 情势分析 → 情势引擎
        elif event_type in ("situation.analyze", "tension", "metrics.update"):
            result["routed_to"] = "situation_engine"
            metrics = data.get("metrics", data)
            analysis = self.situation_engine.analyze(metrics)
            self.stats["situation_calls"] += 1
            result["action"] = "analyze"
            result["details"] = analysis

            # 如果有 tension，尝试造动
            if analysis["has_tension"]:
                intervention = self.situation_engine.try_intervention(metrics)
                if intervention:
                    result["details"]["intervention"] = intervention

        # Persona 查询
        elif event_type in ("persona.query", "persona.match"):
            result["routed_to"] = "persona"
            task_desc = data.get("task", "")
            enhanced = enhance_agents_with_persona(self.agents_json_path)
            matches = []
            for s in enhanced:
                score = s.matches_task(task_desc)
                if score > 0:
                    matches.append({
                        "agent_id": s.agent_id,
                        "name": s.name,
                        "match_score": score,
                        "combat_power": s.combat_power,
                    })
            matches.sort(key=lambda m: m["match_score"], reverse=True)
            self.stats["persona_queries"] += 1
            result["action"] = "persona_match"
            result["details"] = {"matches": matches[:10]}

        # 颐卦查询/消化
        elif event_type in ("yi.query", "yi.search"):
            result["routed_to"] = "yi_learning"
            query_ctx = data.get("context", data)
            experiences = self.yi_engine.query(query_ctx)
            self.stats["yi_queries"] += 1
            result["action"] = "yi_query"
            result["details"] = {
                "hits": len(experiences),
                "results": [
                    {"exp_id": e.exp_id, "source": e.source,
                     "lesson": e.lesson, "weight": e.weight}
                    for e in experiences
                ],
            }

        elif event_type in ("yi.digest", "yi.learn"):
            result["routed_to"] = "yi_learning"
            digest_result = self.yi_engine.digest()
            self.stats["yi_digests"] += 1
            result["action"] = "yi_digest"
            result["details"] = digest_result

        else:
            result["routed_to"] = "passthrough"
            result["action"] = "no_engine_match"

        return result

    def get_status(self) -> Dict:
        """获取引擎状态"""
        return {
            "initialized": self.initialized,
            "engines": {
                "situation": {
                    "active": True,
                    "intervention_history": len(self.situation_engine.intervention_history),
                },
                "zhen_recovery": {
                    "active": True,
                    "recovery_log": len(self.zhen_engine.recovery_log),
                    "circuit_breakers": len(self.zhen_engine.guardian.circuit_breakers),
                },
                "shi_swarm": {
                    "active": True,
                    "mission_log": len(self.shi_engine.mission_log),
                    "barracks": self.shi_engine.barracks.get_battle_report(),
                },
                "persona": {
                    "active": True,
                    "loaded_count": len(self.personas),
                },
                "yi_learning": {
                    "active": True,
                    "experiences": self.yi_engine.get_status()["total"],
                    "high_weight": self.yi_engine.get_status()["high_weight_count"],
                    "stats": self.yi_engine.get_status()["stats"],
                },
            },
            "stats": self.stats,
        }


# ============================================================
# 便捷函数
# ============================================================

_registry: Optional[EngineRegistry] = None


def initialize_engines(agents_json_path: str = None) -> EngineRegistry:
    """初始化所有引擎（全局单例）"""
    global _registry
    _registry = EngineRegistry(agents_json_path)
    emit("engines.initialized", {
        "engines": ["situation", "zhen_recovery", "shi_swarm", "persona", "yi_learning"],
        "timestamp": time.time(),
    })
    return _registry


def get_registry() -> Optional[EngineRegistry]:
    """获取引擎注册中心"""
    return _registry


def route_to_engine(event_type: str, data: Dict = None) -> Dict:
    """路由事件到对应引擎"""
    if _registry is None:
        return {"error": "Engine registry not initialized"}
    return _registry.route_event(event_type, data)


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== 引擎注册中心测试 ===\n")

    registry = initialize_engines()
    status = registry.get_status()

    print("引擎状态:")
    for name, info in status["engines"].items():
        print(f"  {name}: active={info['active']}")
    print()

    # 测试路由: 故障 → 震卦
    print("路由测试 1: 故障事件 → 震卦")
    r1 = registry.route_event(EventType.AGENT_FAILED, {
        "agent": "coder",
        "error_type": "timeout",
        "severity": "low",
    })
    print(f"  路由到: {r1['routed_to']}")
    print(f"  结果: {r1['details'].get('success', 'N/A')}")
    print(f"  教训: {r1['details'].get('lesson', 'N/A')}")
    print()

    # 测试路由: 情势分析
    print("路由测试 2: 情势分析")
    r2 = registry.route_event("situation.analyze", {
        "metrics": {
            "api_health": 0.3,
            "network_latency": 0.7,
            "dependency_available": 0.4,
            "task_success_rate": 0.2,
            "timeout_rate": 0.6,
            "retry_rate": 0.5,
            "recommendation_hit_rate": 0.8,
            "learning_gain": 0.7,
            "experience_validity": 0.7,
            "router_accuracy": 0.5,
            "queue_length": 0.5,
            "dispatch_stability": 0.5,
            "agent_cooperation": 0.5,
            "resource_sharing": 0.5,
            "conflict_rate": 0.3,
            "evolution_score": 40.0,
            "canary_health": 0.5,
            "global_stability": 0.4,
        }
    })
    print(f"  路由到: {r2['routed_to']}")
    print(f"  冲突数: {len(r2['details'].get('tensions', []))}")
    print()

    # 测试路由: 师卦任务
    print("路由测试 3: 多 Agent 协作 → 师卦")
    r3 = registry.route_event("mission", {
        "objective": "分析系统近期的异常日志，找出规律并给出改进建议",
        "constraints": ["只读", "30秒内完成"],
        "output_schema": {"patterns": "list", "recommendation": "str"},
        "conflict_policy": "vote",
    })
    print(f"  路由到: {r3['routed_to']}")
    print(f"  状态: {r3['details'].get('status', 'N/A')}")
    print(f"  小队: {r3['details'].get('squad', [])}")
    print()

    # 最终统计
    final_status = registry.get_status()
    print(f"调用统计: {final_status['stats']}")
    print("\n✅ 引擎注册中心测试完成")
