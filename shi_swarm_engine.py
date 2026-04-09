#!/usr/bin/env python3
"""
师卦协作引擎 (Shi Swarm Engine) — 多 Agent 协作调度

核心理念：地水师 ☷☵ — "师出以律，否臧凶"
出兵必须有纪律，否则必败。九二为全卦唯一阳爻 = 统帅，其余五阴爻 = 兵众。

六爻状态机：
  初六·MOBILIZE → 任务定义与约束下发（律不明则凶）
  九二·DISPATCH → 中央调度器分配 Agent（唯一阳爻统帅）
  六三·CONFLICT → 协作冲突检测（逻辑打架、资源争抢）
  六四·RETREAT  → 战略撤退 + 冲突仲裁
  六五·HARVEST  → 结果收割，整合各 Agent 输出
  上六·MANDATE  → 复盘评估，赏罚

Agent 军衔体系：
  COMMANDER — 九二位，全局调度
  GENERAL   — 高权重，独立决策
  SOLDIER   — 执行者，听从调度
  SCOUT     — 轻量探测，快速反馈

Author: TaijiOS
Date: 2026-04-09
"""

import json
import time
import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

from event_bus import emit, subscribe, get_event_bus, EventType


# ============================================================
# 枚举
# ============================================================

class ShiYao(Enum):
    """师卦六爻状态"""
    MOBILIZE = (1, "初六", "师出以律", "任务定义与约束下发")
    DISPATCH = (2, "九二", "在师中吉", "中央调度器分配 Agent")
    CONFLICT = (3, "六三", "师或舆尸", "协作冲突检测")
    RETREAT  = (4, "六四", "师左次",   "战略撤退 + 仲裁")
    HARVEST  = (5, "六五", "田有禽",   "结果收割")
    MANDATE  = (6, "上六", "大君有命", "复盘评估，赏罚")

    def __init__(self, position: int, name_cn: str, yao_ci: str, description: str):
        self.position = position
        self.name_cn = name_cn
        self.yao_ci = yao_ci
        self.description = description


class AgentRank(str, Enum):
    """军衔"""
    COMMANDER = "commander"  # 统帅
    GENERAL = "general"      # 将领
    SOLDIER = "soldier"      # 士兵
    SCOUT = "scout"          # 斥候


class MissionStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    MOBILIZING = "mobilizing"
    DISPATCHED = "dispatched"
    EXECUTING = "executing"
    CONFLICTING = "conflicting"
    RETREATING = "retreating"
    HARVESTING = "harvesting"
    COMPLETED = "completed"
    FAILED = "failed"


# ============================================================
# 数据结构
# ============================================================

@dataclass
class MissionLaw:
    """
    律令 — 出兵前必须明确

    "师出以律，否臧凶"：目标/约束/Schema 三者缺一不可
    """
    objective: str = ""
    constraints: List[str] = field(default_factory=list)
    output_schema: Dict = field(default_factory=dict)
    timeout_sec: int = 120
    conflict_policy: str = "vote"  # vote / priority / merge
    min_agents: int = 2
    max_agents: int = 5
    quality_threshold: float = 0.6

    def validate(self) -> tuple:
        """律令校验"""
        if not self.objective or len(self.objective) < 10:
            return False, "目标不清晰 (少于10字)，师出无律，必凶"
        if not self.output_schema:
            return False, "输出 Schema 未定义，各 Agent 无法对齐产出"
        if not self.constraints:
            return False, "无约束条件，Agent 可能失控"
        return True, "律已备，可出师"


@dataclass
class AgentSoldier:
    """参战 Agent"""
    agent_id: str
    name: str = ""
    rank: AgentRank = AgentRank.SOLDIER
    skills: List[str] = field(default_factory=list)
    reliability: float = 0.8
    current_load: int = 0
    max_load: int = 5
    status: str = "idle"
    performance_score: float = 0.0
    output: Optional[Dict] = None

    @property
    def combat_power(self) -> float:
        """战斗力 = reliability × (1 - current_load / max_load)"""
        load_ratio = 1 - (self.current_load / max(self.max_load, 1))
        return self.reliability * max(load_ratio, 0.1)

    @property
    def is_available(self) -> bool:
        return self.status in ("idle", "active") and self.current_load < self.max_load


@dataclass
class Mission:
    """作战任务"""
    mission_id: str = field(default_factory=lambda: f"mission-{uuid.uuid4().hex[:8]}")
    law: MissionLaw = field(default_factory=MissionLaw)
    status: MissionStatus = MissionStatus.PENDING
    commander: Optional[AgentSoldier] = None
    squad: List[AgentSoldier] = field(default_factory=list)
    outputs: Dict[str, Dict] = field(default_factory=dict)  # agent_id -> output
    conflicts: List[Dict] = field(default_factory=list)
    final_output: Optional[Dict] = None
    history: List[Dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def record(self, yao: ShiYao, action: str, detail: str):
        self.history.append({
            "yao": yao.name,
            "yao_cn": yao.name_cn,
            "action": action,
            "detail": detail,
            "timestamp": time.time(),
        })


# ============================================================
# 兵库
# ============================================================

class AgentBarracks:
    """
    兵库：管理所有可用 Agent

    从 agents.json 加载，映射 stats.success_rate → reliability
    """

    def __init__(self):
        self.soldiers: Dict[str, AgentSoldier] = {}

    def load_from_json(self, agents_json_path: str = None):
        """从 agents.json 加载 Agent 兵力"""
        if agents_json_path is None:
            agents_json_path = str(Path(__file__).parent / "agents.json")

        with open(agents_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        agents_list = data if isinstance(data, list) else data.get("agents", [])

        for agent_data in agents_list:
            agent_id = agent_data.get("id", agent_data.get("name", "").lower().replace(" ", "_"))
            if not agent_id:
                continue

            stats = agent_data.get("stats", {})
            success_rate = stats.get("success_rate", 0.8)

            # 映射 priority/group → rank
            priority = agent_data.get("priority", "normal")
            group = agent_data.get("group", "general")
            rank = self._infer_rank(priority, group)

            soldier = AgentSoldier(
                agent_id=agent_id,
                name=agent_data.get("name", agent_id),
                rank=rank,
                skills=agent_data.get("skills", []),
                reliability=success_rate if isinstance(success_rate, float) else 0.8,
            )
            self.soldiers[agent_id] = soldier

    def _infer_rank(self, priority: str, group: str) -> AgentRank:
        """从 priority 和 group 推断军衔"""
        if priority == "critical" or group == "dispatcher":
            return AgentRank.COMMANDER
        elif priority == "high" or group in ("research", "coder"):
            return AgentRank.GENERAL
        elif group in ("monitor", "scout", "collector"):
            return AgentRank.SCOUT
        return AgentRank.SOLDIER

    def register(self, soldier: AgentSoldier):
        """手动注册 Agent"""
        self.soldiers[soldier.agent_id] = soldier

    def select_commander(self) -> Optional[AgentSoldier]:
        """
        选帅："丈人吉" — reliability 最高者为帅
        """
        commanders = [
            s for s in self.soldiers.values()
            if s.is_available and s.rank in (AgentRank.COMMANDER, AgentRank.GENERAL)
        ]
        if not commanders:
            # 无将领可用，从所有 Agent 中选 reliability 最高者
            commanders = [s for s in self.soldiers.values() if s.is_available]

        if not commanders:
            return None

        # 颐卦反哺：用历史表现趋势微调选帅
        self._yi_boost_reliability(commanders)

        return max(commanders, key=lambda s: s.reliability)

    def _yi_boost_reliability(self, candidates: List["AgentSoldier"]):
        """查询颐卦获取 agent 历史表现趋势，微调 reliability"""
        try:
            from engine_registry import get_registry
            registry = get_registry()
            if not registry or not hasattr(registry, 'yi_engine'):
                return
            for soldier in candidates:
                results = registry.yi_engine.query({"agent": soldier.agent_id})
                if results:
                    avg_score = sum(
                        r.outcome.get("score", 0.5) for r in results
                        if "score" in r.outcome
                    ) / max(len(results), 1)
                    # 微调: 历史高分者 +0.02，低分者 -0.02
                    if avg_score > 0.7:
                        soldier.reliability = min(1.0, soldier.reliability + 0.02)
                    elif avg_score < 0.3:
                        soldier.reliability = max(0.1, soldier.reliability - 0.02)
        except Exception:
            pass

    def recruit_squad(self, commander: AgentSoldier, task_skills: List[str] = None,
                      max_size: int = 5) -> List[AgentSoldier]:
        """
        招募小队：按战斗力排序

        优先选择技能匹配且可用的 Agent
        """
        candidates = [
            s for s in self.soldiers.values()
            if s.is_available and s.agent_id != commander.agent_id
        ]

        # 按战斗力排序
        candidates.sort(key=lambda s: s.combat_power, reverse=True)

        # 如果有技能要求，优先匹配
        if task_skills:
            def skill_match(soldier):
                return sum(1 for skill in task_skills if skill in soldier.skills)
            candidates.sort(key=lambda s: (skill_match(s), s.combat_power), reverse=True)

        squad = [commander] + candidates[:max_size - 1]
        return squad

    def get_battle_report(self) -> Dict:
        """兵力报告"""
        total = len(self.soldiers)
        available = sum(1 for s in self.soldiers.values() if s.is_available)
        by_rank = {}
        for s in self.soldiers.values():
            rank = s.rank.value
            by_rank[rank] = by_rank.get(rank, 0) + 1

        return {
            "total": total,
            "available": available,
            "by_rank": by_rank,
            "avg_reliability": sum(s.reliability for s in self.soldiers.values()) / max(total, 1),
        }


# ============================================================
# 冲突仲裁
# ============================================================

class ConflictArbiter:
    """
    冲突仲裁器

    三策略：
    - vote：多数表决（民主）
    - priority：军衔优先（集权）
    - merge：合并输出（和合）
    """

    @staticmethod
    def detect_conflicts(outputs: Dict[str, Dict]) -> List[Dict]:
        """
        检测输出矛盾

        两两比对，同一 key 有不同 value 即为矛盾
        """
        conflicts = []
        agent_ids = list(outputs.keys())

        for i in range(len(agent_ids)):
            for j in range(i + 1, len(agent_ids)):
                a_id, b_id = agent_ids[i], agent_ids[j]
                a_out, b_out = outputs[a_id], outputs[b_id]

                if not isinstance(a_out, dict) or not isinstance(b_out, dict):
                    continue

                for key in set(a_out.keys()) & set(b_out.keys()):
                    if a_out[key] != b_out[key]:
                        conflicts.append({
                            "key": key,
                            "agent_a": a_id,
                            "value_a": a_out[key],
                            "agent_b": b_id,
                            "value_b": b_out[key],
                        })

        return conflicts

    @staticmethod
    def arbitrate_vote(outputs: Dict[str, Dict], conflicts: List[Dict]) -> Dict:
        """多数表决：每个冲突 key 取出现次数最多的值"""
        result = {}
        all_keys = set()
        for out in outputs.values():
            if isinstance(out, dict):
                all_keys.update(out.keys())

        for key in all_keys:
            votes = {}
            for agent_id, out in outputs.items():
                if isinstance(out, dict) and key in out:
                    val = json.dumps(out[key], ensure_ascii=False, default=str)
                    votes[val] = votes.get(val, 0) + 1

            if votes:
                winner = max(votes, key=votes.get)
                result[key] = json.loads(winner)

        return result

    @staticmethod
    def arbitrate_priority(outputs: Dict[str, Dict], squad: List[AgentSoldier]) -> Dict:
        """集权：按 combat_power 排序，最强者输出优先"""
        ranked = sorted(squad, key=lambda s: s.combat_power, reverse=True)

        result = {}
        for soldier in reversed(ranked):
            out = outputs.get(soldier.agent_id)
            if isinstance(out, dict):
                result.update(out)

        return result

    @staticmethod
    def arbitrate_merge(outputs: Dict[str, Dict]) -> Dict:
        """和合：取所有 Agent 输出的并集"""
        result = {}
        for out in outputs.values():
            if isinstance(out, dict):
                for key, value in out.items():
                    if key not in result:
                        result[key] = value
                    elif isinstance(result[key], list) and isinstance(value, list):
                        result[key] = list(set(result[key] + value))

        return result


# ============================================================
# 师卦协作引擎（核心状态机）
# ============================================================

class ShiSwarmEngine:
    """
    核心状态机：驱动六爻流转

    任务律令 → 初六·MOBILIZE → 九二·DISPATCH → 并行执行
             → 六三·CONFLICT → 六四·RETREAT → 六五·HARVEST
             → 上六·MANDATE
    """

    def __init__(self, agents_json_path: str = None):
        self.barracks = AgentBarracks()
        self.arbiter = ConflictArbiter()
        self.mission_log: List[Mission] = []
        self.agents_json_path = agents_json_path or str(Path(__file__).parent / "agents.json")

        # 加载兵力
        try:
            self.barracks.load_from_json(self.agents_json_path)
        except Exception as e:
            print(f"⚠️ 加载 agents.json 失败: {e}")

    def execute_mission(self, law: MissionLaw,
                        task_executor=None) -> Mission:
        """
        完整协作流程

        Args:
            law: 任务律令
            task_executor: 可选的自定义任务执行器
                           签名: (agent_id, objective, constraints) -> dict

        Returns: Mission 对象
        """
        mission = Mission(law=law)

        # ── 初六·MOBILIZE ── 校验律令
        result = self._yao_1_mobilize(mission)
        if not result:
            return mission

        # ── 九二·DISPATCH ── 选帅 + 招募 + 下发律令
        self._yao_2_dispatch(mission)

        if not mission.squad:
            mission.status = MissionStatus.FAILED
            mission.record(ShiYao.DISPATCH, "招募失败", "无可用 Agent")
            return mission

        # ── 并行执行 ──
        self._execute_agents(mission, task_executor)

        # ── 六三·CONFLICT ── 冲突检测
        has_conflict = self._yao_3_conflict(mission)

        if has_conflict:
            # ── 六四·RETREAT ── 仲裁
            self._yao_4_retreat(mission)

        # ── 六五·HARVEST ── 结果收割
        self._yao_5_harvest(mission)

        # ── 上六·MANDATE ── 赏罚
        self._yao_6_mandate(mission)

        self.mission_log.append(mission)
        return mission

    def _yao_1_mobilize(self, mission: Mission) -> bool:
        """初六·MOBILIZE — 校验律令"""
        mission.status = MissionStatus.MOBILIZING

        emit("shi.yao_transition", {
            "mission_id": mission.mission_id,
            "yao": "MOBILIZE",
            "yao_cn": "初六·师出以律",
        })

        valid, msg = mission.law.validate()
        mission.record(ShiYao.MOBILIZE, "律令校验", msg)

        if not valid:
            mission.status = MissionStatus.FAILED
            emit("shi.mission_failed", {
                "mission_id": mission.mission_id,
                "reason": msg,
            })
            return False

        return True

    def _yao_2_dispatch(self, mission: Mission):
        """九二·DISPATCH — 选帅 + 招募"""
        mission.status = MissionStatus.DISPATCHED

        emit("shi.yao_transition", {
            "mission_id": mission.mission_id,
            "yao": "DISPATCH",
            "yao_cn": "九二·在师中吉",
        })

        # 选帅
        commander = self.barracks.select_commander()
        if commander:
            mission.commander = commander
            mission.record(ShiYao.DISPATCH, "选帅",
                           f"{commander.name} (reliability={commander.reliability:.2f})")
        else:
            mission.record(ShiYao.DISPATCH, "选帅", "无将可用")
            return

        # 招募
        squad = self.barracks.recruit_squad(
            commander,
            max_size=mission.law.max_agents,
        )
        mission.squad = squad
        mission.record(ShiYao.DISPATCH, "招募",
                       f"共 {len(squad)} 人: {', '.join(s.name for s in squad)}")

        emit("shi.squad_formed", {
            "mission_id": mission.mission_id,
            "commander": commander.agent_id,
            "squad": [s.agent_id for s in squad],
        })

    def _execute_agents(self, mission: Mission, task_executor=None):
        """执行所有 Agent（真实 LLM 调用或自定义执行器）"""
        mission.status = MissionStatus.EXECUTING

        for soldier in mission.squad:
            soldier.status = "busy"
            soldier.current_load += 1

            if task_executor:
                try:
                    output = task_executor(
                        soldier.agent_id,
                        mission.law.objective,
                        mission.law.constraints,
                    )
                except Exception as e:
                    output = {"error": str(e), "status": "failed"}
            else:
                output = self._llm_executor(soldier, mission.law)

            soldier.output = output
            mission.outputs[soldier.agent_id] = output
            soldier.current_load = max(0, soldier.current_load - 1)
            soldier.status = "idle"

        mission.record(ShiYao.DISPATCH, "执行完毕",
                       f"收到 {len(mission.outputs)} 份输出")

    def _llm_executor(self, soldier: AgentSoldier, law: MissionLaw) -> Dict:
        """
        真实 LLM 执行器 — 每个 Agent 用 Claude API 生成输出

        - Commander/General → claude-sonnet-4-6
        - Soldier/Scout → claude-haiku-4-5
        - system_prompt 根据 Agent 角色动态生成
        - 要求 JSON 格式输出（对齐 law.output_schema）
        """
        from llm_caller import call_llm_json, is_llm_available

        if not is_llm_available():
            return self._mock_executor(soldier, law)

        # 模型选择：将领用 sonnet，士兵用 haiku
        if soldier.rank in (AgentRank.COMMANDER, AgentRank.GENERAL):
            model = "claude-sonnet-4-6"
        else:
            model = "claude-haiku-4-5"

        # 动态 system_prompt
        system_prompt = (
            f"你是 {soldier.name}（ID: {soldier.agent_id}），"
            f"军衔: {soldier.rank.value}，"
            f"技能: {', '.join(soldier.skills) if soldier.skills else '通用'}。\n"
            f"你正在参与一个多 Agent 协作任务。\n"
            f"请严格按照指定的 JSON Schema 格式输出，不要输出任何其他内容。"
        )

        # user_prompt = 律令
        schema_str = json.dumps(law.output_schema, ensure_ascii=False)
        constraints_str = "\n".join(f"- {c}" for c in law.constraints)

        user_prompt = (
            f"## 任务目标\n{law.objective}\n\n"
            f"## 约束条件\n{constraints_str}\n\n"
            f"## 输出格式（JSON）\n{schema_str}\n\n"
            f"请以 JSON 格式回答，字段严格对齐上面的 Schema。"
        )

        result = call_llm_json(system_prompt, user_prompt, model=model, max_tokens=1024)

        # 补充元信息
        if "error" not in result:
            result["agent_id"] = soldier.agent_id
            result["status"] = "completed"
            result["confidence"] = round(soldier.combat_power * 0.8 + 0.2, 2)
        else:
            result["agent_id"] = soldier.agent_id
            result["status"] = "failed"
            result["confidence"] = 0.0

        return result

    def _mock_executor(self, soldier: AgentSoldier, law: MissionLaw) -> Dict:
        """模拟执行器（API 不可用时的 fallback）"""
        score = soldier.combat_power * 0.8 + 0.2
        return {
            "agent_id": soldier.agent_id,
            "result": f"{soldier.name} 完成 {law.objective[:20]}...",
            "confidence": round(score, 2),
            "status": "completed",
        }

    def _yao_3_conflict(self, mission: Mission) -> bool:
        """六三·CONFLICT — 冲突检测"""
        emit("shi.yao_transition", {
            "mission_id": mission.mission_id,
            "yao": "CONFLICT",
            "yao_cn": "六三·师或舆尸",
        })

        conflicts = ConflictArbiter.detect_conflicts(mission.outputs)
        mission.conflicts = conflicts

        if conflicts:
            mission.status = MissionStatus.CONFLICTING
            mission.record(ShiYao.CONFLICT, "冲突检测",
                           f"发现 {len(conflicts)} 个矛盾")
            return True
        else:
            mission.record(ShiYao.CONFLICT, "冲突检测", "无冲突")
            return False

    def _yao_4_retreat(self, mission: Mission):
        """六四·RETREAT — 战略撤退 + 仲裁"""
        mission.status = MissionStatus.RETREATING

        emit("shi.yao_transition", {
            "mission_id": mission.mission_id,
            "yao": "RETREAT",
            "yao_cn": "六四·师左次",
        })

        policy = mission.law.conflict_policy

        if policy == "vote":
            arbitrated = ConflictArbiter.arbitrate_vote(mission.outputs, mission.conflicts)
            mission.record(ShiYao.RETREAT, "多数表决", f"仲裁 {len(mission.conflicts)} 个冲突")
        elif policy == "priority":
            arbitrated = ConflictArbiter.arbitrate_priority(mission.outputs, mission.squad)
            mission.record(ShiYao.RETREAT, "集权裁决", "按战斗力优先")
        elif policy == "merge":
            arbitrated = ConflictArbiter.arbitrate_merge(mission.outputs)
            mission.record(ShiYao.RETREAT, "和合合并", "取并集")
        else:
            arbitrated = ConflictArbiter.arbitrate_vote(mission.outputs, mission.conflicts)
            mission.record(ShiYao.RETREAT, "默认表决", "未知策略，回退表决")

        mission.outputs["_arbitrated"] = arbitrated

    def _yao_5_harvest(self, mission: Mission):
        """六五·HARVEST — 结果收割"""
        mission.status = MissionStatus.HARVESTING

        emit("shi.yao_transition", {
            "mission_id": mission.mission_id,
            "yao": "HARVEST",
            "yao_cn": "六五·田有禽",
        })

        # 优先级：仲裁结果 > Commander 输出 > 最高置信度
        if "_arbitrated" in mission.outputs:
            mission.final_output = mission.outputs["_arbitrated"]
            mission.record(ShiYao.HARVEST, "收割", "使用仲裁结果")
        elif mission.commander and mission.commander.agent_id in mission.outputs:
            mission.final_output = mission.outputs[mission.commander.agent_id]
            mission.record(ShiYao.HARVEST, "收割", "使用统帅输出")
        else:
            # 选最高置信度
            best_id = None
            best_conf = -1
            for agent_id, out in mission.outputs.items():
                if isinstance(out, dict):
                    conf = out.get("confidence", 0)
                    if conf > best_conf:
                        best_conf = conf
                        best_id = agent_id
            if best_id:
                mission.final_output = mission.outputs[best_id]
            mission.record(ShiYao.HARVEST, "收割", f"使用最高置信度: {best_id}")

    def _yao_6_mandate(self, mission: Mission):
        """上六·MANDATE — 赏罚复盘"""
        mission.status = MissionStatus.COMPLETED

        emit("shi.yao_transition", {
            "mission_id": mission.mission_id,
            "yao": "MANDATE",
            "yao_cn": "上六·大君有命",
        })

        threshold = mission.law.quality_threshold
        rewards = []

        for soldier in mission.squad:
            out = mission.outputs.get(soldier.agent_id, {})
            score = out.get("confidence", 0.5) if isinstance(out, dict) else 0.5
            soldier.performance_score = score

            old_rel = soldier.reliability

            if score >= threshold:
                # 开国承家 — 提升
                soldier.reliability = min(1.0, soldier.reliability + 0.05)
                change = "+0.05"
            elif any(c.get("agent_a") == soldier.agent_id or c.get("agent_b") == soldier.agent_id
                     for c in mission.conflicts) or score < 0.3:
                # 小人勿用 — 降级
                soldier.reliability = max(0.1, soldier.reliability - 0.1)
                change = "-0.10"
            else:
                change = "±0"

            rewards.append({
                "agent_id": soldier.agent_id,
                "score": score,
                "old_reliability": old_rel,
                "new_reliability": soldier.reliability,
                "change": change,
            })

        mission.record(ShiYao.MANDATE, "赏罚",
                       f"评估 {len(rewards)} 人")

        emit("shi.mandate", {
            "mission_id": mission.mission_id,
            "rewards": rewards,
        })

        # 写回 agents.json 的 stats
        self._persist_rewards(rewards)

    def _persist_rewards(self, rewards: List[Dict]):
        """将赏罚结果写回 agents.json"""
        try:
            with open(self.agents_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            agents_list = data if isinstance(data, list) else data.get("agents", [])

            for reward in rewards:
                agent_id = reward["agent_id"]
                for agent in agents_list:
                    aid = agent.get("id", agent.get("name", "").lower().replace(" ", "_"))
                    if aid == agent_id:
                        if "stats" not in agent:
                            agent["stats"] = {}
                        agent["stats"]["success_rate"] = reward["new_reliability"]
                        break

            with open(self.agents_json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"⚠️ 赏罚写回失败: {e}")


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== 师卦协作引擎测试 ===\n")

    engine = ShiSwarmEngine()

    # 手动注册测试兵力
    test_soldiers = [
        AgentSoldier("coder", "Coder", AgentRank.GENERAL, ["coding", "debug"], 0.9),
        AgentSoldier("analyst", "Analyst", AgentRank.GENERAL, ["analysis", "pattern"], 0.85),
        AgentSoldier("monitor", "Monitor", AgentRank.SOLDIER, ["monitor", "alert"], 0.8),
        AgentSoldier("reactor", "Reactor", AgentRank.SOLDIER, ["recovery", "ops"], 0.75),
        AgentSoldier("guardian", "Guardian", AgentRank.COMMANDER, ["security", "audit"], 0.95),
    ]
    for s in test_soldiers:
        engine.barracks.register(s)

    # 兵力报告
    report = engine.barracks.get_battle_report()
    print(f"兵力: 总计 {report['total']}, 可用 {report['available']}")
    print(f"军衔分布: {report['by_rank']}")
    print(f"平均可靠度: {report['avg_reliability']:.2f}\n")

    # 场景 1：正常协作任务
    print("场景 1：正常协作任务")
    law1 = MissionLaw(
        objective="分析系统日志，找出过去 24 小时内的异常模式",
        constraints=["只读操作", "不修改任何文件", "30 秒内完成"],
        output_schema={"patterns": "list", "severity": "str", "recommendation": "str"},
        conflict_policy="vote",
    )
    mission1 = engine.execute_mission(law1)
    print(f"  状态: {mission1.status.value}")
    print(f"  统帅: {mission1.commander.name if mission1.commander else 'N/A'}")
    print(f"  小队: {', '.join(s.name for s in mission1.squad)}")
    print(f"  冲突: {len(mission1.conflicts)}")
    if mission1.final_output:
        print(f"  输出: {json.dumps(mission1.final_output, ensure_ascii=False)[:100]}...")
    print(f"  爻位路径: {' → '.join(h['yao'] for h in mission1.history)}")
    print()

    # 场景 2：律令不合格
    print("场景 2：律令不合格（目标过短）")
    law2 = MissionLaw(
        objective="修 bug",  # 少于 10 字
        constraints=[],
        output_schema={},
    )
    mission2 = engine.execute_mission(law2)
    print(f"  状态: {mission2.status.value}")
    print(f"  原因: {mission2.history[0]['detail'] if mission2.history else 'N/A'}")
    print()

    # 场景 3：带冲突的任务
    print("场景 3：模拟冲突")

    def conflict_executor(agent_id, objective, constraints):
        # 模拟不同 Agent 给出矛盾结果
        if agent_id == "coder":
            return {"recommendation": "重构代码", "confidence": 0.85, "priority": "high"}
        elif agent_id == "analyst":
            return {"recommendation": "保持现状", "confidence": 0.75, "priority": "low"}
        else:
            return {"recommendation": "重构代码", "confidence": 0.70, "priority": "medium"}

    law3 = MissionLaw(
        objective="评估系统架构是否需要重构，给出建议",
        constraints=["考虑稳定性", "考虑成本"],
        output_schema={"recommendation": "str", "confidence": "float", "priority": "str"},
        conflict_policy="vote",
    )
    mission3 = engine.execute_mission(law3, task_executor=conflict_executor)
    print(f"  状态: {mission3.status.value}")
    print(f"  冲突数: {len(mission3.conflicts)}")
    if mission3.final_output:
        print(f"  最终输出: {json.dumps(mission3.final_output, ensure_ascii=False)}")
    print(f"  爻位路径: {' → '.join(h['yao'] for h in mission3.history)}")

    # 赏罚结果
    print("\n  赏罚结果:")
    for soldier in mission3.squad:
        print(f"    {soldier.name}: reliability={soldier.reliability:.2f}, score={soldier.performance_score:.2f}")

    print(f"\n任务总数: {len(engine.mission_log)}")
    print("\n✅ 师卦协作引擎测试完成")
