"""
CausalReasoner — 因果推理引擎

认知晶体是相关性的："A和B一起出现时效果好"。
因果推理是机制性的："A导致B，B导致C，所以A导致C"。

因果链的价值：
  1. 能预测没见过的情况
  2. 能解释为什么
  3. 能设计干预
"""

import time
import json
import os
import logging
from typing import Optional
from dataclasses import dataclass, field
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class CausalLink:
    """因果链中的一环"""
    cause: str
    effect: str
    mechanism: str
    strength: float
    evidence: int
    counter: int

    @property
    def reliability(self) -> float:
        return self.evidence / max(self.evidence + self.counter, 1)

    def to_dict(self) -> dict:
        return {
            "cause": self.cause,
            "effect": self.effect,
            "mechanism": self.mechanism,
            "strength": round(self.strength, 2),
            "reliability": round(self.reliability, 2),
            "evidence": self.evidence,
        }


@dataclass
class CausalChain:
    """一条完整的因果链"""
    chain_id: str
    links: list[CausalLink]
    domain: str
    prediction_power: float = 0.0
    predictions_made: int = 0
    predictions_correct: int = 0
    created_at: float = field(default_factory=time.time)

    @property
    def depth(self) -> int:
        return len(self.links)

    def get_root_cause(self) -> str:
        return self.links[0].cause if self.links else ""

    def get_final_effect(self) -> str:
        return self.links[-1].effect if self.links else ""

    def predict(self, given_cause: str) -> Optional[str]:
        if not self.links:
            return None
        if given_cause != self.links[0].cause:
            return None
        self.predictions_made += 1
        return self.get_final_effect()

    def validate_prediction(self, correct: bool):
        if correct:
            self.predictions_correct += 1
        self.prediction_power = self.predictions_correct / max(self.predictions_made, 1)

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "depth": self.depth,
            "root": self.get_root_cause(),
            "final": self.get_final_effect(),
            "domain": self.domain,
            "prediction_power": round(self.prediction_power, 2),
            "predictions": f"{self.predictions_correct}/{self.predictions_made}",
            "links": [l.to_dict() for l in self.links],
        }


class CausalReasoner:
    """
    因果推理引擎。
    从认知晶体和行为数据中构建因果链，用因果链做预测，用预测结果反向验证。
    """

    CAUSAL_SEEDS = [
        {"cause": "用户连续失败", "effect": "frustration上升",
         "mechanism": "反复失败产生挫败感", "domain": "emotion"},
        {"cause": "frustration上升", "effect": "情绪护盾触发",
         "mechanism": "系统检测到高frustration自动保护", "domain": "emotion"},
        {"cause": "情绪护盾触发", "effect": "AI语气变温和",
         "mechanism": "突变修改personality向量，压制直率", "domain": "style"},
        {"cause": "AI语气变温和", "effect": "用户感到被支持",
         "mechanism": "温和语气降低对抗感，建立安全感", "domain": "emotion"},
        {"cause": "用户感到被支持", "effect": "正面反馈",
         "mechanism": "被支持的感觉转化为满意度", "domain": "outcome"},
        {"cause": "关系阶段提升", "effect": "策略空间扩大",
         "mechanism": "更深的信任解锁更多交互模式", "domain": "style"},
        {"cause": "策略空间扩大", "effect": "个性化程度提高",
         "mechanism": "更多可用策略→更精准的匹配", "domain": "style"},
        {"cause": "性格被长期压制", "effect": "Shadow能量积累",
         "mechanism": "base和effective的差值持续累积", "domain": "personality"},
        {"cause": "Shadow能量积累", "effect": "性格泄漏",
         "mechanism": "能量超过阈值后概率性释放", "domain": "personality"},
        {"cause": "深夜交互", "effect": "文艺倾向增强",
         "mechanism": "夜间抑制力下降+氛围感增强", "domain": "timing"},
    ]

    def __init__(self, state_path: str = None):
        self.state_path = state_path or "causal_state.json"
        self.chains: list[CausalChain] = []
        self.links: list[CausalLink] = []
        self._chain_counter = 0
        self._init_seeds()

    def _init_seeds(self):
        for seed in self.CAUSAL_SEEDS:
            link = CausalLink(
                cause=seed["cause"],
                effect=seed["effect"],
                mechanism=seed["mechanism"],
                strength=0.5,
                evidence=1,
                counter=0,
            )
            self.links.append(link)
        self._build_chains()

    def _build_chains(self):
        cause_to_link = {}
        for link in self.links:
            cause_to_link.setdefault(link.cause, []).append(link)
        visited = set()
        for link in self.links:
            if link.cause in visited:
                continue
            chain_links = [link]
            current_effect = link.effect
            depth = 0
            while current_effect in cause_to_link and depth < 5:
                next_links = cause_to_link[current_effect]
                best = max(next_links, key=lambda l: l.strength)
                if best.effect in {l.cause for l in chain_links}:
                    break
                chain_links.append(best)
                current_effect = best.effect
                depth += 1
            if len(chain_links) >= 2:
                self._chain_counter += 1
                domain = "general"
                for seed in self.CAUSAL_SEEDS:
                    if seed["cause"] == chain_links[0].cause:
                        domain = seed["domain"]
                        break
                chain = CausalChain(
                    chain_id=f"chain_{self._chain_counter:03d}",
                    links=chain_links,
                    domain=domain,
                )
                self.chains.append(chain)
            visited.add(link.cause)

    def discover_from_data(self, outcomes: list[dict]) -> list[CausalLink]:
        new_links = []
        if len(outcomes) < 5:
            return new_links
        for i in range(1, len(outcomes)):
            prev = outcomes[i - 1]
            curr = outcomes[i]
            prev_ctx = prev.get("context", {})
            curr_ctx = curr.get("context", {})
            prev_frust = prev.get("frustration_at_time", 0)
            curr_frust = curr.get("frustration_at_time", 0)
            if prev_frust < 0.3 and curr_frust > 0.5:
                if not curr.get("positive") and prev.get("positive"):
                    link = CausalLink(
                        cause="frustration急升",
                        effect="正面反馈下降",
                        mechanism="情绪恶化导致用户满意度下降",
                        strength=0.6, evidence=1, counter=0,
                    )
                    new_links.append(link)
            prev_mut = prev_ctx.get("mutations", [])
            curr_mut = curr_ctx.get("mutations", [])
            if not prev_mut and curr_mut and curr.get("positive"):
                link = CausalLink(
                    cause=f"突变{'+'.join(curr_mut)}激活",
                    effect="正面反馈增加",
                    mechanism="突变调整了AI行为模式使其更适合当前场景",
                    strength=0.5, evidence=1, counter=0,
                )
                new_links.append(link)
            prev_stage = prev_ctx.get("relationship_stage", "")
            curr_stage = curr_ctx.get("relationship_stage", "")
            if prev_stage != curr_stage and curr_stage:
                link = CausalLink(
                    cause=f"关系从{prev_stage}升到{curr_stage}",
                    effect="交互模式变化",
                    mechanism="信任积累解锁新的交互可能",
                    strength=0.6, evidence=1, counter=0,
                )
                new_links.append(link)
        for new in new_links:
            existing = self._find_similar_link(new)
            if existing:
                existing.evidence += 1
                existing.strength = min(1.0, existing.strength + 0.05)
            else:
                self.links.append(new)
        if new_links:
            self._build_chains()
        return new_links

    def predict(self, scenario: dict) -> list[dict]:
        predictions = []
        cause = scenario.get("cause", "")
        for chain in self.chains:
            result = chain.predict(cause)
            if result:
                predictions.append({
                    "chain_id": chain.chain_id,
                    "predicted_effect": result,
                    "confidence": chain.prediction_power if chain.predictions_made > 0 else chain.links[0].strength,
                    "reasoning": " -> ".join(f"{l.cause}->{l.effect}" for l in chain.links),
                    "depth": chain.depth,
                })
        predictions.sort(key=lambda p: -p["confidence"])
        return predictions

    def validate(self, chain_id: str, correct: bool):
        for chain in self.chains:
            if chain.chain_id == chain_id:
                chain.validate_prediction(correct)
                break

    def explain(self, observation: str) -> list[dict]:
        explanations = []
        for chain in self.chains:
            if observation in chain.get_final_effect():
                explanation = {
                    "chain_id": chain.chain_id,
                    "root_cause": chain.get_root_cause(),
                    "explanation": " 导致 ".join(
                        f"{l.cause}（{l.mechanism}）" for l in chain.links
                    ) + f" 导致 {chain.get_final_effect()}",
                    "reliability": min(l.reliability for l in chain.links),
                }
                explanations.append(explanation)
        return explanations

    def _find_similar_link(self, new_link: CausalLink) -> Optional[CausalLink]:
        for existing in self.links:
            if existing.cause == new_link.cause and existing.effect == new_link.effect:
                return existing
        return None

    def get_strongest_chains(self, top_k: int = 5) -> list[CausalChain]:
        scored = []
        for chain in self.chains:
            avg_strength = sum(l.strength for l in chain.links) / max(len(chain.links), 1)
            scored.append((avg_strength, chain))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top_k]]

    def to_dict(self) -> dict:
        return {
            "total_links": len(self.links),
            "total_chains": len(self.chains),
            "strongest_chains": [c.to_dict() for c in self.get_strongest_chains(3)],
            "predictions_total": sum(c.predictions_made for c in self.chains),
            "predictions_correct": sum(c.predictions_correct for c in self.chains),
        }


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  CausalReasoner — 因果推理")
    print("  从'知道什么'到'知道为什么'")
    print("=" * 60)

    reasoner = CausalReasoner()

    print(f"\n── 种子因果链 ──")
    print(f"  独立因果关系: {len(reasoner.links)}条")
    print(f"  因果链: {len(reasoner.chains)}条")
    for chain in reasoner.get_strongest_chains(3):
        print(f"\n  [{chain.chain_id}] (深度={chain.depth})")
        for link in chain.links:
            print(f"     {link.cause} -> {link.effect}")
            print(f"       机制: {link.mechanism}")

    print(f"\n── 预测 ──")
    predictions = reasoner.predict({"cause": "用户连续失败"})
    for p in predictions:
        print(f"  如果「{p['predicted_effect']}」")
        print(f"     推理: {p['reasoning']}")
        print(f"     置信度: {p['confidence']:.2f}")

    print(f"\n── 解释 ──")
    explanations = reasoner.explain("正面反馈")
    for e in explanations:
        print(f"  为什么会有正面反馈？")
        print(f"     根因: {e['root_cause']}")
        print(f"     链路: {e['explanation'][:80]}...")

    print(f"\n── 从数据发现 ──")
    outcomes = [
        {"positive": True, "frustration_at_time": 0.1, "context": {"relationship_stage": "stranger", "mutations": []}},
        {"positive": False, "frustration_at_time": 0.6, "context": {"relationship_stage": "familiar", "mutations": []}},
        {"positive": True, "frustration_at_time": 0.4, "context": {"relationship_stage": "familiar", "mutations": ["战友模式"]}},
        {"positive": True, "frustration_at_time": 0.3, "context": {"relationship_stage": "familiar", "mutations": ["情绪护盾"]}},
        {"positive": False, "frustration_at_time": 0.8, "context": {"relationship_stage": "acquainted", "mutations": []}},
        {"positive": True, "frustration_at_time": 0.35, "context": {"relationship_stage": "acquainted", "mutations": ["战友模式"]}},
    ]
    new = reasoner.discover_from_data(outcomes)
    print(f"  发现{len(new)}条新因果关系")
    for link in new:
        print(f"    {link.cause} -> {link.effect} (强度={link.strength:.2f})")

    print(f"\n── 更新后 ──")
    state = reasoner.to_dict()
    print(f"  总因果关系: {state['total_links']}")
    print(f"  总因果链: {state['total_chains']}")

    print(f"\n{'=' * 60}")
    print("  相关性告诉你what。因果性告诉你why。")
    print("  知道why的系统能预测从没见过的情况。")
    print(f"{'=' * 60}")
