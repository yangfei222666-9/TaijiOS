"""
SoulEvolutionBridge — 外科手术 × 免疫系统 协同层

EvolutionAnalyzer（外科手术）和 GrowthEngine（免疫系统）各自独立运行，
这个bridge让它们协同：

  kept patch   → 喂养对应的 growth node（验证过的策略 → 加速生长）
  rollback     → 生成免疫记忆（失败的策略 → 记住不要再长这个方向）
  mature node  → 反哺 analyzer 的模板库（成熟的生长 → 变成新的手术方案）

类比：
  你感冒了。
  外科手术 = 吃药（快速精准，但停药就没了）
  免疫系统 = 产生抗体（慢，但永久免疫）
  协同 = 吃药的同时免疫系统学会了这个病毒的模式，下次不用吃药了
"""

import json
import os
import time
from typing import Optional
from dataclasses import dataclass, field


@dataclass
class ImmuneMemory:
    """
    免疫记忆 — 记住失败的方向，避免重复犯错。
    不是"不做这件事"，是"在这个条件下，这种策略行不通"。
    """
    memory_id: str
    source_patch_id: str       # 来自哪个被rollback的patch
    condition: dict             # 什么条件下失败的
    failed_behavior: str        # 失败的策略内容
    reason: str                 # 为什么失败
    created_at: float = field(default_factory=time.time)
    times_prevented: int = 0    # 阻止了几次重复犯错

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "source_patch_id": self.source_patch_id,
            "condition": self.condition,
            "failed_behavior": self.failed_behavior[:80],
            "reason": self.reason,
            "times_prevented": self.times_prevented,
            "created_at": self.created_at,
            "age_days": round((time.time() - self.created_at) / 86400, 1),
        }

    @staticmethod
    def from_dict(d: dict) -> "ImmuneMemory":
        return ImmuneMemory(
            memory_id=d["memory_id"],
            source_patch_id=d.get("source_patch_id", ""),
            condition=d.get("condition", {}),
            failed_behavior=d.get("failed_behavior", ""),
            reason=d.get("reason", ""),
            created_at=d.get("created_at", time.time()),
            times_prevented=d.get("times_prevented", 0),
        )


class SoulEvolutionBridge:
    """
    协同层。连接 EvolutionAnalyzer 和 GrowthEngine。

    三个方向的数据流：
      Analyzer → Growth:  kept patch 喂养 growth node
      Analyzer → Immune:  rollback 生成免疫记忆
      Growth → Analyzer:  mature node 反哺 patch 模板
      Immune → Growth:    阻止在免疫方向上生长
    """

    def __init__(self, analyzer, growth_engine, bridge_path: str = None):
        self.analyzer = analyzer
        self.growth = growth_engine
        self.bridge_path = bridge_path or os.path.join(
            os.path.dirname(__file__) or ".", "soul_bridge_state.json"
        )
        self.immune_memories: list[ImmuneMemory] = []
        self._memory_counter = 0
        self._synced_patch_ids: set = set()  # 已同步过的patch，避免重复
        self._load()

    # ────────────────────────────────────────────
    # 核心：同步循环
    # ────────────────────────────────────────────

    def sync(self) -> dict:
        """
        执行一次同步。调用时机：
        - 每次 evaluate_patches() 之后
        - 每次 grow_cycle() 之后
        - 或者定期调用

        返回本次同步的事件摘要。
        """
        events = {
            "nourished": [],    # kept → 喂养了哪些 growth node
            "immunized": [],    # rollback → 生成了哪些免疫记忆
            "promoted": [],     # mature node → 反哺了哪些 patch 模板
            "prevented": [],    # 免疫记忆阻止了哪些生长
        }

        # ── 1. kept patch → 喂养 growth node ──
        for patch in self.analyzer.patches:
            if patch.patch_id in self._synced_patch_ids:
                continue

            if patch.status == "kept":
                result = self._nourish_from_patch(patch)
                if result:
                    events["nourished"].append(result)
                self._synced_patch_ids.add(patch.patch_id)

            elif patch.status == "rolled_back":
                result = self._immunize_from_patch(patch)
                if result:
                    events["immunized"].append(result)
                self._synced_patch_ids.add(patch.patch_id)

        # ── 2. mature growth node → 反哺 analyzer 模板 ──
        for node in self.growth.nodes:
            if node.stage == "mature" and node.node_id not in self._synced_patch_ids:
                result = self._promote_node(node)
                if result:
                    events["promoted"].append(result)
                self._synced_patch_ids.add(node.node_id)

        # ── 3. 免疫检查：阻止 growth 在失败方向上长 ──
        prevented = self._immune_check()
        events["prevented"] = prevented

        self._save()
        return events

    # ────────────────────────────────────────────
    # 方向1：kept patch → 喂养 growth node
    # ────────────────────────────────────────────

    def _nourish_from_patch(self, patch) -> Optional[dict]:
        """
        一个patch被kept了 = 这个策略经过验证有效。
        找到条件匹配的growth node，给它浇水。
        如果没有匹配的node，创建一个新的mature级别的node。
        """
        # 找匹配的growth node
        for node in self.growth.nodes:
            if self._conditions_overlap(node.condition, patch.condition):
                # 浇水：直接跳级到growing，加生命力
                node.nourish()
                node.nourish()  # 双倍浇水，因为是经过验证的
                return {
                    "action": "nourish_existing",
                    "patch_id": patch.patch_id,
                    "node_id": node.node_id,
                    "node_stage": node.stage,
                    "detail": f"patch {patch.patch_id} kept → 喂养 {node.node_id}",
                }

        # 没有匹配的 → 创建新节点（从patch直接升级，跳过seedling）
        self.growth._node_counter += 1
        from taijios.evolution.soul_growth_engine import GrowthNode
        new_node = GrowthNode(
            node_id=f"g{self.growth._node_counter:03d}",
            origin=f"promoted_from_patch:{patch.patch_id}",
            condition=patch.condition.copy(),
            behavior=patch.prompt_addition,
            vitality=0.8,  # 已验证，直接高生命力
            times_activated=patch.outcomes_with,
            times_helpful=patch.positive_with,
        )
        new_node._update_stage()
        self.growth.nodes.append(new_node)

        return {
            "action": "create_from_patch",
            "patch_id": patch.patch_id,
            "node_id": new_node.node_id,
            "node_stage": new_node.stage,
            "detail": f"patch {patch.patch_id} kept → 新建 {new_node.node_id}（已验证，高生命力）",
        }

    # ────────────────────────────────────────────
    # 方向2：rollback → 免疫记忆
    # ────────────────────────────────────────────

    def _immunize_from_patch(self, patch) -> Optional[dict]:
        """
        一个patch被rollback了 = 这个方向行不通。
        记住失败条件和策略，防止GrowthEngine在同方向再长。
        """
        # 检查是否已有相同条件的免疫记忆
        for mem in self.immune_memories:
            if mem.condition == patch.condition:
                return None  # 已免疫

        self._memory_counter += 1
        memory = ImmuneMemory(
            memory_id=f"imm{self._memory_counter:03d}",
            source_patch_id=patch.patch_id,
            condition=patch.condition.copy(),
            failed_behavior=patch.prompt_addition,
            reason=patch.evaluation_note or f"正面率从{patch.positive_rate_before:.0%}下降",
        )
        self.immune_memories.append(memory)

        # 同时削弱匹配的growth node（如果有）
        for node in self.growth.nodes:
            if self._conditions_overlap(node.condition, patch.condition):
                node.wilt()
                node.wilt()  # 双倍削弱

        return {
            "action": "immunize",
            "patch_id": patch.patch_id,
            "memory_id": memory.memory_id,
            "condition": memory.condition,
            "detail": f"patch {patch.patch_id} 失败 → 免疫记忆 {memory.memory_id}",
        }

    # ────────────────────────────────────────────
    # 方向3：mature node → 反哺 analyzer
    # ────────────────────────────────────────────

    def _promote_node(self, node) -> Optional[dict]:
        """
        一个growth node长到mature了 = 这个自然生长的策略足够稳定。
        把它注册到analyzer的PATCH_TEMPLATES里，让它变成"可以精确调参的方案"。
        """
        template_id = f"growth:{node.node_id}"

        # 检查是否已在模板库
        if template_id in self.analyzer.PATCH_TEMPLATES:
            return None

        self.analyzer.PATCH_TEMPLATES[template_id] = {
            "condition": node.condition.copy(),
            "prompt_addition": node.behavior,
        }

        return {
            "action": "promote_to_template",
            "node_id": node.node_id,
            "template_id": template_id,
            "detail": f"growth {node.node_id} mature → 新增 analyzer 模板 {template_id}",
        }

    # ────────────────────────────────────────────
    # 免疫检查：阻止在失败方向上生长
    # ────────────────────────────────────────────

    def _immune_check(self) -> list[dict]:
        """
        扫描所有seedling级别的growth node，
        如果它的条件和某个免疫记忆重叠，削弱它。
        """
        prevented = []
        for node in self.growth.nodes:
            if node.stage not in ("seedling", "growing"):
                continue
            for mem in self.immune_memories:
                if self._conditions_overlap(node.condition, mem.condition):
                    # 检查行为是否相似（简单的文本重叠检测）
                    if self._behavior_similar(node.behavior, mem.failed_behavior):
                        node.wilt()
                        mem.times_prevented += 1
                        prevented.append({
                            "node_id": node.node_id,
                            "memory_id": mem.memory_id,
                            "detail": f"免疫记忆 {mem.memory_id} 阻止了 {node.node_id} 的生长",
                        })
        return prevented

    # ────────────────────────────────────────────
    # 工具方法
    # ────────────────────────────────────────────

    def _conditions_overlap(self, cond_a: dict, cond_b: dict) -> bool:
        """两个条件是否有交集"""
        if not cond_a or not cond_b:
            return False
        shared_keys = set(cond_a.keys()) & set(cond_b.keys())
        if not shared_keys:
            return False
        return any(cond_a[k] == cond_b[k] for k in shared_keys)

    def _behavior_similar(self, behavior_a: str, behavior_b: str) -> bool:
        """简单的行为相似度检测"""
        if not behavior_a or not behavior_b:
            return False
        # 取前100字符的关键词重叠度
        words_a = set(behavior_a[:100].split())
        words_b = set(behavior_b[:100].split())
        if not words_a or not words_b:
            return False
        overlap = len(words_a & words_b) / max(len(words_a | words_b), 1)
        return overlap > 0.3

    def get_immune_memories(self) -> list[dict]:
        return [m.to_dict() for m in self.immune_memories]

    # ────────────────────────────────────────────
    # 持久化
    # ────────────────────────────────────────────

    def _load(self):
        if os.path.exists(self.bridge_path):
            try:
                with open(self.bridge_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.immune_memories = [ImmuneMemory.from_dict(m) for m in data.get("immune_memories", [])]
                self._memory_counter = data.get("memory_counter", 0)
                self._synced_patch_ids = set(data.get("synced_ids", []))
            except Exception:
                pass

    def _save(self):
        data = {
            "memory_counter": self._memory_counter,
            "synced_ids": list(self._synced_patch_ids),
            "immune_memories": [m.to_dict() for m in self.immune_memories],
            "last_sync": time.time(),
        }
        with open(self.bridge_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def to_dict(self) -> dict:
        return {
            "immune_count": len(self.immune_memories),
            "synced_patches": len(self._synced_patch_ids),
            "immune_memories": [m.to_dict() for m in self.immune_memories],
            "total_prevented": sum(m.times_prevented for m in self.immune_memories),
        }
