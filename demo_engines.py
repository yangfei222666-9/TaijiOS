#!/usr/bin/env python3
"""
四引擎端到端演示

演示内容：
1. 初始化所有引擎
2. 情势引擎：metrics → 向量 → tension → 造动
3. 震卦恢复引擎：故障事件 → 六爻流转 → 恢复/降级 → 教训
4. 师卦协作引擎：律令 → 选帅派兵 → 并行执行 → 冲突仲裁 → 赏罚
5. Persona 层：任务匹配 → 阴阳平衡选人
6. 引擎联动：通过 engine_registry 统一路由

Author: TaijiOS
Date: 2026-04-09


用法：
  python demo_engines.py          # 真实 LLM 调用
  python demo_engines.py --mock   # 模拟模式（不调用 API）
"""

import json
import sys
from pathlib import Path

# Windows GBK 编码兼容
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

MOCK_MODE = "--mock" in sys.argv

from event_bus import get_event_bus, EventType

_yi_engine = None  # 提前初始化的颐卦引擎，在 main() 中赋值


def separator(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}\n")


def demo_situation_engine():
    """演示 1: 情势引擎"""
    separator("1. 情势引擎 — 六维向量 + 造动破解死锁")

    from situation_engine import SituationEngine

    engine = SituationEngine()

    # 模拟: 资源紧张 + 活跃度高 → 需要造动
    metrics = {
        "api_health": 0.7,
        "network_latency": 0.3,
        "dependency_available": 0.7,
        "task_success_rate": 0.2,    # 资源紧张
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
        "evolution_score": 40.0,
        "canary_health": 0.5,
        "global_stability": 0.4,
    }

    result = engine.analyze(metrics)

    print("六维情势向量:")
    for dim, val in result["vector"].items():
        bar = "█" * int(val * 20) + "░" * (20 - int(val * 20))
        print(f"  {dim:15s} {bar} {val:.2f}")

    print(f"\n冲突检测: {len(result['tensions'])} 个 tension")
    for t in result["tensions"]:
        print(f"  [{t['severity']:.2f}] {t['dim_a']} vs {t['dim_b']}")
        print(f"    → 造动维度: {t['intervention_dim']}")
        print(f"    描述: {t['description']}")

    intervention = engine.try_intervention(metrics)
    if intervention:
        print(f"\n造动执行:")
        print(f"  目标维度: {intervention['intervention_dim']}")
        print(f"  动作: {intervention['action']}")
        print(f"  风险: {intervention['risk']}")
        print(f"  观察窗口: {intervention['observation_window_sec']}s")
        if intervention.get("llm_advice"):
            print(f"  LLM 建议: {intervention['llm_advice']}")
    else:
        print("\n无需造动 / 冷却中")


def demo_zhen_recovery():
    """演示 2: 震卦恢复引擎"""
    separator("2. 震卦恢复引擎 — 六爻状态机驱动故障恢复")

    from zhen_recovery_engine import ZhenRecoveryEngine, FaultEvent

    engine = ZhenRecoveryEngine()

    # 场景 A: 局部故障（低严重度 → 重试成功）
    print("场景 A: 局部故障 (API 超时)")
    fault_a = FaultEvent(
        source_agent="coder",
        error_type="api_timeout",
        severity="low",
        message="Claude API 响应超时",
    )
    state_a = engine.recover(fault_a)
    print(f"  爻位: {' → '.join(h['yao_cn'] for h in state_a.history)}")
    print(f"  结果: {'成功恢复' if state_a.success else '降级运行'}")
    print(f"  教训: {state_a.lesson}")
    print()

    # 场景 B: 级联故障（critical → 跳至备用）
    print("场景 B: 级联故障 (critical)")
    fault_b = FaultEvent(
        source_agent="scheduler",
        error_type="system_crash",
        severity="critical",
        message="调度器核心异常",
    )
    state_b = engine.recover(fault_b)
    print(f"  爻位: {' → '.join(h['yao_cn'] for h in state_b.history)}")
    print(f"  结果: {'成功恢复' if state_b.success else '降级运行'}")
    print(f"  教训: {state_b.lesson}")
    print()

    # 场景 C: 中等故障 + 重试达上限
    print("场景 C: 中等故障 (多次重试)")
    fault_c = FaultEvent(
        source_agent="monitor",
        error_type="connection_reset",
        severity="medium",
        message="连接重置",
        max_retries=2,
    )
    state_c = engine.recover(fault_c)
    print(f"  爻位: {' → '.join(h['yao_cn'] for h in state_c.history)}")
    print(f"  结果: {'成功恢复' if state_c.success else '降级运行'}")
    print(f"  教训: {state_c.lesson}")

    print(f"\n断路器状态: {list(engine.guardian.circuit_breakers.keys())}")
    print(f"恢复日志: {len(engine.recovery_log)} 条")


def demo_shi_swarm():
    """演示 3: 师卦协作引擎"""
    separator("3. 师卦协作引擎 — 多 Agent 选帅/协作/仲裁/赏罚")

    from shi_swarm_engine import ShiSwarmEngine, MissionLaw, AgentSoldier, AgentRank

    engine = ShiSwarmEngine()

    # 手动注册测试兵力
    soldiers = [
        AgentSoldier("guardian", "Guardian", AgentRank.COMMANDER, ["security", "audit"], 0.95),
        AgentSoldier("coder", "Coder", AgentRank.GENERAL, ["coding", "debug", "refactor"], 0.9),
        AgentSoldier("analyst", "Analyst", AgentRank.GENERAL, ["analysis", "pattern"], 0.85),
        AgentSoldier("monitor", "Monitor", AgentRank.SOLDIER, ["monitor", "alert"], 0.8),
        AgentSoldier("learner", "Learner", AgentRank.SOLDIER, ["learning", "training"], 0.7),
        AgentSoldier("collector", "Collector", AgentRank.SCOUT, ["analysis", "general"], 0.7),
    ]
    for s in soldiers:
        engine.barracks.register(s)

    # 兵力报告
    report = engine.barracks.get_battle_report()
    print(f"兵力报告: 总计 {report['total']}, 可用 {report['available']}")
    print(f"  军衔分布: {report['by_rank']}")
    print(f"  平均可靠度: {report['avg_reliability']:.2f}")
    print()

    # 场景 A: 正常协作（无冲突）
    print("场景 A: 正常协作任务")
    law_a = MissionLaw(
        objective="分析近 24 小时系统日志，识别异常模式并生成报告",
        constraints=["只读操作", "不修改文件", "30 秒超时"],
        output_schema={"patterns": "list", "severity": "str", "recommendation": "str"},
        conflict_policy="vote",
        max_agents=4,
    )
    mission_a = engine.execute_mission(law_a)
    print(f"  统帅: {mission_a.commander.name if mission_a.commander else 'N/A'}")
    print(f"  小队: {', '.join(s.name for s in mission_a.squad)}")
    print(f"  状态: {mission_a.status.value}")
    print(f"  冲突: {len(mission_a.conflicts)}")
    print(f"  爻位: {' → '.join(h['yao'] for h in mission_a.history)}")
    print()

    # 场景 B: 真实 LLM 协作任务
    print("场景 B: 真实 LLM 协作任务")

    if MOCK_MODE:
        def conflict_executor(agent_id, objective, constraints):
            if agent_id in ("coder", "guardian"):
                return {"recommendation": "全面重构", "confidence": 0.85, "risk": "high"}
            return {"recommendation": "局部优化", "confidence": 0.75, "risk": "low"}
        executor_b = conflict_executor
    else:
        executor_b = None  # 使用真实 LLM

    law_b = MissionLaw(
        objective="评估 agent_system 架构是否需要重构，给出明确建议",
        constraints=["考虑向后兼容", "考虑维护成本", "考虑开发周期"],
        output_schema={"recommendation": "str", "confidence": "float", "risk": "str"},
        conflict_policy="vote",
        max_agents=4,
    )
    mission_b = engine.execute_mission(law_b, task_executor=executor_b)
    print(f"  统帅: {mission_b.commander.name if mission_b.commander else 'N/A'}")
    print(f"  冲突数: {len(mission_b.conflicts)}")

    # 展示每个 Agent 的输出
    print("\n  各 Agent 输出:")
    for aid, out in mission_b.outputs.items():
        if aid.startswith("_"):
            continue
        out_str = json.dumps(out, ensure_ascii=False, default=str)
        if len(out_str) > 120:
            out_str = out_str[:120] + "..."
        print(f"    {aid}: {out_str}")

    if mission_b.final_output:
        final_str = json.dumps(mission_b.final_output, ensure_ascii=False, default=str)
        print(f"\n  最终输出: {final_str[:200]}")

    # 赏罚结果
    print("\n  赏罚结果:")
    for s in mission_b.squad:
        print(f"    {s.name}: reliability={s.reliability:.2f} "
              f"(score={s.performance_score:.2f})")


def demo_persona():
    """演示 4: Persona 层"""
    separator("4. Persona 层 — 角色匹配 + 阴阳平衡")

    from agent_persona import (
        PersonaLoader, enhance_agents_with_persona,
        select_by_yin_yang_balance,
    )

    agents_json = str(Path(__file__).parent / "agents.json")

    try:
        # 加载 Persona
        personas = PersonaLoader.load_from_agents_json(agents_json)
        print(f"加载 {len(personas)} 个 Persona")

        # 展示部分
        for pid, p in list(personas.items())[:3]:
            print(f"\n  {p.name_cn} ({pid}):")
            print(f"    部门: {p.department} | 卦象: {p.hexagram} | 阴阳: {p.yin_yang}")
            print(f"    军衔: {p.rank} | 可为帅: {p.can_be_commander}")
            if p.auto_activate_keywords:
                print(f"    关键词: {p.auto_activate_keywords[:5]}")

        # 增强 Agent
        enhanced = enhance_agents_with_persona(agents_json)
        print(f"\n增强 {len(enhanced)} 个 Agent")

        # 任务匹配
        print("\n任务匹配测试「前端 React 组件开发」:")
        for s in enhanced:
            score = s.matches_task("前端 react 组件开发")
            if score > 0:
                print(f"  {s.name}: match={score:.2f}, combat={s.combat_power:.2f}")

        # 阴阳平衡选人
        print("\n阴阳平衡选人 (max=5):")
        balanced = select_by_yin_yang_balance(enhanced, max_size=5)
        for s in balanced:
            yy = s.persona.yin_yang if s.persona else "?"
            print(f"  {s.name} ({yy}): combat={s.combat_power:.2f}")

    except Exception as e:
        print(f"⚠️ Persona 演示失败: {e}")
        import traceback
        traceback.print_exc()


def demo_yi_learning():
    """演示 6: 颐卦自学引擎"""
    separator("6. 颐卦自学引擎 — 吸收/消化/沉淀/反哺")

    from yi_learning_engine import YiLearningEngine

    # 复用 main() 中提前初始化的全局实例
    engine = _yi_engine if _yi_engine else YiLearningEngine()

    # 颐卦已通过 EventBus 自动采集前面引擎产生的事件
    status = engine.get_status()
    print(f"自动采集经验: {status['total']} 条")
    print(f"  按来源: {status['by_source']}")
    print(f"  高权重(>=0.7): {status['high_weight_count']} 条")
    print()

    # 被动查询测试
    print("被动查询测试:")

    # 查询震卦相关经验
    zhen_results = engine.query({"error_type": "api_timeout", "source": "zhen"})
    print(f"  查询 error_type=api_timeout: {len(zhen_results)} 条命中")
    for r in zhen_results[:3]:
        print(f"    [{r.source}] w={r.weight:.2f} {r.lesson[:60]}")

    # 查询师卦相关经验
    shi_results = engine.query({"agent": "coder"})
    print(f"  查询 agent=coder: {len(shi_results)} 条命中")
    for r in shi_results[:3]:
        print(f"    [{r.source}] w={r.weight:.2f} {r.lesson[:60]}")

    # 查询情势相关经验
    sit_results = engine.query({"dim_a": "resource", "dim_b": "initiative"})
    print(f"  查询 tension=resource/initiative: {len(sit_results)} 条命中")
    for r in sit_results[:3]:
        print(f"    [{r.source}] w={r.weight:.2f} {r.lesson[:60]}")
    print()

    # 消化归纳
    print("消化归纳:")
    digest_result = engine.digest()
    print(f"  合并组数: {digest_result['groups_merged']}")
    print(f"  合并记录: {digest_result['records_merged']}")
    if digest_result["meta_lessons"]:
        print(f"  元经验:")
        for ml in digest_result["meta_lessons"]:
            print(f"    {ml[:80]}")
    else:
        print(f"  (同类经验不足3条，暂无合并)")
    print()

    # 最终状态
    final = engine.get_status()
    print(f"最终状态: {final['total']} 条经验, 查询 {final['stats']['queries']} 次, "
          f"命中 {final['stats']['hits']} 次, 主动推送 {final['stats']['advisories']} 次")


def demo_engine_registry():
    """演示 7: 引擎注册中心统一路由（五引擎）"""
    separator("7. 引擎注册中心 — 统一路由（五引擎）")

    from engine_registry import initialize_engines

    registry = initialize_engines()

    # 状态
    status = registry.get_status()
    print("引擎状态:")
    for name, info in status["engines"].items():
        active = info.get("active", False)
        print(f"  {name}: {'运行中' if active else '未启动'}")
    print()

    # 路由 1: 故障 → 震卦
    print("路由 1: agent.failed → 震卦恢复")
    r1 = registry.route_event(EventType.AGENT_FAILED, {
        "agent": "coder",
        "error_type": "api_timeout",
        "severity": "low",
        "message": "API 超时",
    })
    print(f"  → {r1['routed_to']}: {r1['details'].get('success', 'N/A')}")
    print(f"  教训: {r1['details'].get('lesson', '')}")
    print()

    # 路由 2: 情势分析
    print("路由 2: situation.analyze → 情势引擎")
    r2 = registry.route_event("situation.analyze", {
        "metrics": {
            "api_health": 0.3, "network_latency": 0.6, "dependency_available": 0.4,
            "task_success_rate": 0.2, "timeout_rate": 0.6, "retry_rate": 0.5,
            "recommendation_hit_rate": 0.8, "learning_gain": 0.7, "experience_validity": 0.7,
            "router_accuracy": 0.5, "queue_length": 0.5, "dispatch_stability": 0.5,
            "agent_cooperation": 0.5, "resource_sharing": 0.5, "conflict_rate": 0.3,
            "evolution_score": 40.0, "canary_health": 0.5, "global_stability": 0.4,
        }
    })
    tensions = r2["details"].get("tensions", [])
    print(f"  → {r2['routed_to']}: {len(tensions)} 个 tension")
    if r2["details"].get("intervention"):
        print(f"  造动: {r2['details']['intervention'].get('intervention_dim', 'N/A')}")
    print()

    # 路由 3: 多 Agent 任务 → 师卦
    print("路由 3: mission → 师卦协作")
    r3 = registry.route_event("mission", {
        "objective": "全面检查系统安全配置，生成安全审计报告",
        "constraints": ["只读", "不修改配置"],
        "output_schema": {"vulnerabilities": "list", "score": "int"},
    })
    print(f"  → {r3['routed_to']}: {r3['details'].get('status', 'N/A')}")
    print(f"  小队: {r3['details'].get('squad', [])}")
    print()

    # 最终统计
    final = registry.get_status()
    print(f"调用统计: {final['stats']}")


def main():
    mode_label = "模拟模式 (--mock)" if MOCK_MODE else "真实 LLM 模式"
    print("╔══════════════════════════════════════════════════════════╗")
    print("║          TaijiOS 五引擎全面演示                          ║")
    print(f"║   {mode_label:^52s} ║")
    print("╚══════════════════════════════════════════════════════════╝")

    # 初始化 EventBus
    bus = get_event_bus()
    event_count = {"count": 0}

    def count_events(event):
        event_count["count"] += 1

    # 订阅所有事件用于计数
    for event_type in [
        "situation.intervention",
        "recovery.yao_transition",
        "recovery.lesson_learned",
        "shi.yao_transition",
        "shi.mandate",
        "yi.experience_added",
        "yi.advisory",
        "yi.digest_completed",
        "engines.initialized",
    ]:
        bus.subscribe(event_type, count_events)

    # 提前初始化颐卦引擎，让它在其他引擎产生事件时就能采集
    global _yi_engine
    from yi_learning_engine import YiLearningEngine
    _yi_engine = YiLearningEngine()

    # 依次演示
    demo_situation_engine()
    demo_zhen_recovery()
    demo_shi_swarm()
    demo_persona()
    demo_yi_learning()
    demo_engine_registry()

    # 总结
    separator("演示总结")
    recent = bus.get_recent_events(limit=100)
    print(f"EventBus 事件总数: {len(recent)}")
    print(f"订阅计数器捕获: {event_count['count']} 个引擎事件")

    # 按类型统计
    type_counts = {}
    for e in recent:
        t = e["type"]
        type_counts[t] = type_counts.get(t, 0) + 1

    print("\n事件类型分布:")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}")

    print("\n✅ 五引擎全面演示完成")


if __name__ == "__main__":
    main()
