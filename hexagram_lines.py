#!/usr/bin/env python3
"""
Hexagram Lines - 六爻业务语义与评分计算

六爻固定语义（自下而上）：
1. 初爻：基础设施层（API健康、网络、依赖可达性）
2. 二爻：执行层（任务成功率、超时率、重试率）
3. 三爻：学习层（推荐命中率、学习收益、经验有效性）
4. 四爻：调度层（Router决策质量、队列、分发稳定性）
5. 五爻：协作层（Agent配合、资源共享、冲突情况）
6. 上爻：演化/治理层（Evolution Score、灰度控制、全局稳定性）

Author: 珊瑚海 + 小九
Date: 2026-03-07
Version: 2.0
"""

from typing import Dict, Tuple
from dataclasses import dataclass

@dataclass
class LineScore:
    """单爻评分结果"""
    score: float  # 0.0 ~ 1.0
    state: int  # 0=阴, 1=阳
    is_changing: bool  # 是否处于临界带
    confidence: float  # 判断置信度
    factors: Dict[str, float]  # 影响因素
    description: str  # 业务描述

# ============================================================
# 评分离散化规则
# ============================================================

def discretize_score(score: float) -> Tuple[int, bool, float]:
    """
    将评分离散化为阴阳
    
    Args:
        score: 0.0 ~ 1.0
    
    Returns:
        (state, is_changing, confidence)
        - state: 0=阴, 1=阳
        - is_changing: 是否处于临界带（0.4~0.6）
        - confidence: 置信度（离临界带越远越高）
    """
    if score < 0.4:
        # 阴爻
        state = 0
        is_changing = False
        confidence = 1.0 - (score / 0.4)  # 越接近0，置信度越高
    elif score > 0.6:
        # 阳爻
        state = 1
        is_changing = False
        confidence = (score - 0.6) / 0.4  # 越接近1，置信度越高
    else:
        # 临界带（将变未变）
        state = 1 if score >= 0.5 else 0
        is_changing = True
        confidence = 0.5  # 临界态置信度低
    
    return state, is_changing, confidence

# ============================================================
# 初爻：基础设施层
# ============================================================

def score_infra_line(metrics: Dict[str, float]) -> LineScore:
    """
    初爻：基础设施层
    
    关键指标：
    - api_health: API健康度（0~1）
    - network_latency: 网络延迟（归一化，越低越好）
    - dependency_available: 依赖可达性（0~1）
    
    权重：
    - api_health: 0.5（最关键）
    - network_latency: 0.3
    - dependency_available: 0.2
    """
    api_health = metrics.get("api_health", 0.5)
    network_latency = 1.0 - metrics.get("network_latency", 0.5)  # 反转（低延迟=高分）
    dependency_available = metrics.get("dependency_available", 0.5)
    
    # 加权计算
    score = (
        api_health * 0.5 +
        network_latency * 0.3 +
        dependency_available * 0.2
    )
    
    state, is_changing, confidence = discretize_score(score)
    
    return LineScore(
        score=score,
        state=state,
        is_changing=is_changing,
        confidence=confidence,
        factors={
            "api_health": api_health,
            "network_latency": network_latency,
            "dependency_available": dependency_available
        },
        description=f"基础设施层 {'健康' if state == 1 else '异常'}"
    )

# ============================================================
# 二爻：执行层
# ============================================================

def score_execution_line(metrics: Dict[str, float]) -> LineScore:
    """
    二爻：执行层
    
    关键指标：
    - task_success_rate: 任务成功率（0~1）
    - timeout_rate: 超时率（归一化，越低越好）
    - retry_rate: 重试率（归一化，越低越好）
    
    权重：
    - task_success_rate: 0.6（最关键）
    - timeout_rate: 0.25
    - retry_rate: 0.15
    """
    task_success_rate = metrics.get("task_success_rate", 0.5)
    timeout_rate = 1.0 - metrics.get("timeout_rate", 0.5)  # 反转
    retry_rate = 1.0 - metrics.get("retry_rate", 0.5)  # 反转
    
    score = (
        task_success_rate * 0.6 +
        timeout_rate * 0.25 +
        retry_rate * 0.15
    )
    
    state, is_changing, confidence = discretize_score(score)
    
    return LineScore(
        score=score,
        state=state,
        is_changing=is_changing,
        confidence=confidence,
        factors={
            "task_success_rate": task_success_rate,
            "timeout_rate": timeout_rate,
            "retry_rate": retry_rate
        },
        description=f"执行层 {'稳定' if state == 1 else '不稳定'}"
    )

# ============================================================
# 三爻：学习层
# ============================================================

def score_learning_line(metrics: Dict[str, float]) -> LineScore:
    """
    三爻：学习层
    
    关键指标：
    - recommendation_hit_rate: 推荐命中率（0~1）
    - learning_gain: 学习收益（0~1）
    - experience_validity: 经验有效性（0~1）
    
    权重：
    - recommendation_hit_rate: 0.4
    - learning_gain: 0.35
    - experience_validity: 0.25
    """
    recommendation_hit_rate = metrics.get("recommendation_hit_rate", 0.5)
    learning_gain = metrics.get("learning_gain", 0.5)
    experience_validity = metrics.get("experience_validity", 0.5)
    
    score = (
        recommendation_hit_rate * 0.4 +
        learning_gain * 0.35 +
        experience_validity * 0.25
    )
    
    state, is_changing, confidence = discretize_score(score)
    
    return LineScore(
        score=score,
        state=state,
        is_changing=is_changing,
        confidence=confidence,
        factors={
            "recommendation_hit_rate": recommendation_hit_rate,
            "learning_gain": learning_gain,
            "experience_validity": experience_validity
        },
        description=f"学习层 {'有效' if state == 1 else '低效'}"
    )

# ============================================================
# 四爻：调度层
# ============================================================

def score_routing_line(metrics: Dict[str, float]) -> LineScore:
    """
    四爻：调度层
    
    关键指标：
    - router_accuracy: Router决策准确率（0~1）
    - queue_health: 队列健康度（归一化，越低越好）
    - dispatch_stability: 分发稳定性（0~1）
    
    权重：
    - router_accuracy: 0.4
    - queue_health: 0.35
    - dispatch_stability: 0.25
    """
    router_accuracy = metrics.get("router_accuracy", 0.5)
    queue_health = 1.0 - metrics.get("queue_length", 0.5)  # 反转（队列短=健康）
    dispatch_stability = metrics.get("dispatch_stability", 0.5)
    
    score = (
        router_accuracy * 0.4 +
        queue_health * 0.35 +
        dispatch_stability * 0.25
    )
    
    state, is_changing, confidence = discretize_score(score)
    
    return LineScore(
        score=score,
        state=state,
        is_changing=is_changing,
        confidence=confidence,
        factors={
            "router_accuracy": router_accuracy,
            "queue_health": queue_health,
            "dispatch_stability": dispatch_stability
        },
        description=f"调度层 {'流畅' if state == 1 else '阻塞'}"
    )

# ============================================================
# 五爻：协作层
# ============================================================

def score_collaboration_line(metrics: Dict[str, float]) -> LineScore:
    """
    五爻：协作层
    
    关键指标：
    - agent_cooperation: Agent配合度（0~1）
    - resource_sharing: 资源共享效率（0~1）
    - conflict_rate: 冲突率（归一化，越低越好）
    
    权重：
    - agent_cooperation: 0.4
    - resource_sharing: 0.35
    - conflict_rate: 0.25
    """
    agent_cooperation = metrics.get("agent_cooperation", 0.5)
    resource_sharing = metrics.get("resource_sharing", 0.5)
    conflict_rate = 1.0 - metrics.get("conflict_rate", 0.5)  # 反转
    
    score = (
        agent_cooperation * 0.4 +
        resource_sharing * 0.35 +
        conflict_rate * 0.25
    )
    
    state, is_changing, confidence = discretize_score(score)
    
    return LineScore(
        score=score,
        state=state,
        is_changing=is_changing,
        confidence=confidence,
        factors={
            "agent_cooperation": agent_cooperation,
            "resource_sharing": resource_sharing,
            "conflict_rate": conflict_rate
        },
        description=f"协作层 {'和谐' if state == 1 else '冲突'}"
    )

# ============================================================
# 上爻：演化/治理层
# ============================================================

def score_governance_line(metrics: Dict[str, float]) -> LineScore:
    """
    上爻：演化/治理层
    
    关键指标：
    - evolution_score: Evolution Score（0~100，归一化到0~1）
    - canary_health: 灰度健康度（0~1）
    - global_stability: 全局稳定性（0~1）
    
    权重：
    - evolution_score: 0.5（最关键）
    - canary_health: 0.3
    - global_stability: 0.2
    """
    evolution_score = metrics.get("evolution_score", 50.0) / 100.0  # 归一化
    canary_health = metrics.get("canary_health", 0.5)
    global_stability = metrics.get("global_stability", 0.5)
    
    score = (
        evolution_score * 0.5 +
        canary_health * 0.3 +
        global_stability * 0.2
    )
    
    state, is_changing, confidence = discretize_score(score)
    
    return LineScore(
        score=score,
        state=state,
        is_changing=is_changing,
        confidence=confidence,
        factors={
            "evolution_score": evolution_score,
            "canary_health": canary_health,
            "global_stability": global_stability
        },
        description=f"治理层 {'优秀' if state == 1 else '待改进'}"
    )

# ============================================================
# 主函数：计算六爻
# ============================================================

def calculate_six_lines(metrics: Dict[str, float]) -> Dict[str, LineScore]:
    """
    计算六爻评分
    
    Args:
        metrics: 系统指标字典
    
    Returns:
        六爻评分结果
    """
    return {
        "line_1_infra": score_infra_line(metrics),
        "line_2_execution": score_execution_line(metrics),
        "line_3_learning": score_learning_line(metrics),
        "line_4_routing": score_routing_line(metrics),
        "line_5_collaboration": score_collaboration_line(metrics),
        "line_6_governance": score_governance_line(metrics),
    }

# ============================================================
# 测试用例
# ============================================================

if __name__ == "__main__":
    print("=== Hexagram Lines 测试 ===\n")
    
    # 测试场景 1：新 Agent 启动
    print("场景 1：新 Agent 启动")
    metrics_new = {
        "api_health": 0.3,  # API 还在初始化
        "network_latency": 0.8,  # 高延迟
        "dependency_available": 0.2,  # 依赖未就绪
        "task_success_rate": 0.0,  # 还没开始任务
        "timeout_rate": 0.0,
        "retry_rate": 0.0,
        "recommendation_hit_rate": 0.0,
        "learning_gain": 0.0,
        "experience_validity": 0.0,
        "router_accuracy": 0.5,
        "queue_length": 0.0,
        "dispatch_stability": 0.5,
        "agent_cooperation": 0.5,
        "resource_sharing": 0.5,
        "conflict_rate": 0.0,
        "evolution_score": 0.0,
        "canary_health": 0.5,
        "global_stability": 0.5,
    }
    lines = calculate_six_lines(metrics_new)
    for name, line in lines.items():
        print(f"{name}: {line.score:.2f} ({'阳' if line.state == 1 else '阴'}) "
              f"{'[临界]' if line.is_changing else ''} - {line.description}")
    print()
    
    # 测试场景 2：成熟 Agent
    print("场景 2：成熟 Agent")
    metrics_mature = {
        "api_health": 0.98,
        "network_latency": 0.1,
        "dependency_available": 0.95,
        "task_success_rate": 0.96,
        "timeout_rate": 0.05,
        "retry_rate": 0.03,
        "recommendation_hit_rate": 0.85,
        "learning_gain": 0.80,
        "experience_validity": 0.90,
        "router_accuracy": 0.92,
        "queue_length": 0.15,
        "dispatch_stability": 0.95,
        "agent_cooperation": 0.90,
        "resource_sharing": 0.88,
        "conflict_rate": 0.05,
        "evolution_score": 99.5,
        "canary_health": 0.95,
        "global_stability": 0.98,
    }
    lines = calculate_six_lines(metrics_mature)
    for name, line in lines.items():
        print(f"{name}: {line.score:.2f} ({'阳' if line.state == 1 else '阴'}) "
              f"{'[临界]' if line.is_changing else ''} - {line.description}")
    print()
    
    # 测试场景 3：基础设施异常
    print("场景 3：基础设施异常（API 超时）")
    metrics_infra_fail = {
        "api_health": 0.15,  # API 严重异常
        "network_latency": 0.9,  # 高延迟
        "dependency_available": 0.3,  # 依赖不稳定
        "task_success_rate": 0.45,  # 成功率下降
        "timeout_rate": 0.6,  # 高超时率
        "retry_rate": 0.5,  # 高重试率
        "recommendation_hit_rate": 0.70,
        "learning_gain": 0.65,
        "experience_validity": 0.75,
        "router_accuracy": 0.80,
        "queue_length": 0.7,  # 队列积压
        "dispatch_stability": 0.60,
        "agent_cooperation": 0.75,
        "resource_sharing": 0.70,
        "conflict_rate": 0.2,
        "evolution_score": 85.0,
        "canary_health": 0.70,
        "global_stability": 0.65,
    }
    lines = calculate_six_lines(metrics_infra_fail)
    for name, line in lines.items():
        print(f"{name}: {line.score:.2f} ({'阳' if line.state == 1 else '阴'}) "
              f"{'[临界]' if line.is_changing else ''} - {line.description}")
