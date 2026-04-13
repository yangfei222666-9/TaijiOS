"""
TaijiOS Soul SDK — 三行代码给 AI 装灵魂

    from taijios import Soul
    soul = Soul(user_id="alice")
    response = soul.chat("今天心情不好")

背后自动运行：五虎上将军议 + 四维意图混合 + 三层记忆 + 性格进化。
开发者不需要知道易经是什么。
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from taijios.llm import LLMCaller
from taijios.engine.soul_dimensions import SoulEngine
from taijios.engine.soul_aware_code_assist import SoulAwareCodeAssist
from taijios.evolution.soul_evolution_analyzer import SoulEvolutionAnalyzer
from taijios.evolution.soul_growth_engine import SoulGrowthEngine
from taijios.evolution.soul_evolution_bridge import SoulEvolutionBridge
from taijios.evolution.crystallization_engine import CrystallizationEngine
from taijios.engine.safety_soul_guard import SafetySoulGuard, integrate_guard_with_api
from taijios.engine.intent_mixer import IntentMixer, build_mode_prompt
from taijios.engine.five_generals import CouncilOfGenerals
from taijios.engine.style_library import pick_style, pick_signature
from taijios.memory.infinite_context import InfiniteContext
from taijios.memory.selective_memory import SelectiveMemory
from taijios.memory.self_narrative import SelfNarrative
from taijios.memory.causal_reasoner import CausalReasoner
from taijios.memory.reinforcement_loop import ReinforcementLoop
from taijios.memory.adaptive_learning import AdaptiveLearning

logger = logging.getLogger("taijios")


# ============================================================
# 进化调度器
# ============================================================

class _EvolutionScheduler:
    ANALYZE_EVERY = 10
    GROW_EVERY = 20
    BRIDGE_EVERY = 20
    CRYSTALLIZE_EVERY = 20

    @staticmethod
    def should_analyze(count: int) -> bool:
        return count > 0 and count % _EvolutionScheduler.ANALYZE_EVERY == 0

    @staticmethod
    def should_grow(count: int) -> bool:
        return count > 0 and count % _EvolutionScheduler.GROW_EVERY == 0

    @staticmethod
    def should_bridge(count: int) -> bool:
        return count > 0 and count % _EvolutionScheduler.BRIDGE_EVERY == 0

    @staticmethod
    def should_crystallize(count: int) -> bool:
        return count > 0 and count % _EvolutionScheduler.CRYSTALLIZE_EVERY == 0


# ============================================================
# SoulResponse
# ============================================================

@dataclass
class SoulResponse:
    """Soul.chat() 的返回值"""
    reply: str = ""
    intent: dict = field(default_factory=dict)
    generals: dict = field(default_factory=dict)
    stage: str = ""
    personality: str = ""
    frustration: float = 0.0
    evolution_notes: list = field(default_factory=list)
    interaction_count: int = 0
    events: dict = field(default_factory=dict)


# ============================================================
# Soul — 开发者入口
# ============================================================

class Soul:
    """
    TaijiOS 灵魂 SDK 入口。

    三行接入:
        from taijios import Soul
        soul = Soul(user_id="alice")
        reply = soul.chat("你好")

    参数:
        user_id: 用户唯一标识
        data_dir: 灵魂数据持久化目录，默认 ~/.taijios/{user_id}
        api_key: Claude API key，不传走 ollama/mock
        ollama_url: ollama 地址，默认 localhost:11434
        model: LLM 模型名
    """

    def __init__(
        self,
        user_id: str,
        data_dir: str = None,
        api_key: str = None,
        ollama_url: str = None,
        model: str = None,
    ):
        self.user_id = user_id
        self._data_dir = data_dir or os.path.expanduser(f"~/.taijios/{user_id}")
        os.makedirs(self._data_dir, exist_ok=True)

        user_dir = self._data_dir
        outcomes_path = os.path.join(user_dir, "soul_outcomes.jsonl")
        patches_path = os.path.join(user_dir, "soul_patches.json")
        growth_path = os.path.join(user_dir, "soul_growth.json")
        bridge_path = os.path.join(user_dir, "soul_bridge.json")

        # 14 模块实例化
        self._soul = SoulEngine(user_id=user_id, state_dir=user_dir)
        self._analyzer = SoulEvolutionAnalyzer(outcomes_path, patches_path)
        self._growth = SoulGrowthEngine(outcomes_path, growth_path)
        self._assist = SoulAwareCodeAssist(self._soul, outcomes_path, analyzer=self._analyzer)
        self._bridge = SoulEvolutionBridge(self._analyzer, self._growth, bridge_path)
        self._guard = SafetySoulGuard(
            log_path=os.path.join(user_dir, "safety_events.jsonl")
        )
        self._context = InfiniteContext(
            user_id=user_id,
            data_dir=os.path.join(user_dir, "context"),
        )
        self._context.start_session()
        self._narrative = SelfNarrative()
        self._narrative.record_first_meeting(
            self._soul.fate.personality_seed,
            self._soul.fate.constitution,
        )
        self._causal = CausalReasoner()
        self._rl = ReinforcementLoop(
            state_path=os.path.join(user_dir, "rl_state.json")
        )
        self._adaptive = AdaptiveLearning(
            data_dir=Path(os.path.join(user_dir, "learning_data"))
        )
        self._memory = SelectiveMemory(data_dir=user_dir)
        self._council = CouncilOfGenerals(data_dir=user_dir)
        self._crystallizer = CrystallizationEngine(data_dir=user_dir)
        self._mixer = IntentMixer()
        self._llm = LLMCaller(api_key=api_key, ollama_url=ollama_url, model=model)
        self._interaction_count = 0

        logger.info("Soul created for %s (backend=%s)", user_id, self._llm.backend)

    def chat(
        self,
        message: str,
        intent: str = None,
        history: list = None,
        image_base64: str = None,
    ) -> SoulResponse:
        """
        核心方法。发一条消息，返回灵魂驱动的回复。
        10 步管线：安全 → 反馈 → 灵魂 → 意图 → 五将军 → LLM → 过滤 → 进化 → 记忆 → 返回
        """
        if not message and not image_base64:
            return SoulResponse(reply="", stage=self.stage)
        if not message and image_base64:
            message = "用户发了一张图片，请分析"

        soul = self._soul
        assist = self._assist
        analyzer = self._analyzer
        growth = self._growth
        bridge_inst = self._bridge
        guard = self._guard
        ctx_engine = self._context
        narrative = self._narrative
        causal = self._causal
        rl = self._rl
        adaptive = self._adaptive
        memory = self._memory
        council = self._council
        mixer = self._mixer

        # ── STEP 0: 上下文预热 ──
        preload = ctx_engine.preload_context(message)

        # ── STEP 0.5: 自我叙事拦截 ──
        SELF_KEYWORDS = ["你是谁", "你叫什么", "介绍你自己", "你的故事",
                         "你经历了什么", "你跟以前", "你变了吗", "你的性格"]
        if any(kw in message for kw in SELF_KEYWORDS):
            soul_ctx = soul.get_context()
            soul_ctx["interaction_count"] = self._interaction_count
            self_answer = narrative.answer_about_self(message, soul_ctx)
            if self_answer:
                ctx_engine.add_turn(message, self_answer)
                self._interaction_count += 1
                return SoulResponse(
                    reply=self_answer,
                    stage=soul.fate.stage_label,
                    personality=soul_ctx.get("personality_card", ""),
                    frustration=round(soul._frustration_score, 3),
                    interaction_count=self._interaction_count,
                )

        # ── STEP 1: 安全预检 ──
        safety = integrate_guard_with_api(
            guard, soul, assist, message, user_id=self.user_id
        )

        # ── STEP 2: 隐式反馈推断 ──
        implicit = rl.infer_feedback(message)
        if implicit is not None:
            rl.feedback(positive=implicit, context={"source": "implicit"})

        # ── STEP 3: 灵魂处理 ──
        events = soul.on_message(message, intent=intent)

        # ── STEP 4: prompt fragment ──
        if safety["use_safe_fragment"]:
            fragment = safety["safe_fragment"]
        else:
            fragment = assist.build_prompt_fragment()

        # ── STEP 5: 组装 system prompt ──
        frustration = getattr(soul, '_frustration_score', 0)
        intent_mix = mixer.mix(message, soul_state={"frustration": frustration}, intent_hint=intent)
        base_prompt = build_mode_prompt(intent_mix)

        # 自我介绍检测
        INTRO_KEYWORDS = ["你能做什么", "你有什么功能", "介绍一下自己", "介绍一下",
                          "你会什么", "你能干什么", "有啥功能", "功能介绍",
                          "你是干嘛的", "你是做什么的", "简单介绍"]
        if any(kw in message for kw in INTRO_KEYWORDS):
            base_prompt = (
                "你是「丞相九」——太极OS的军师。用户在问你的功能，这是展示自己的机会！\n"
                "【本次回复取消3句话限制，必须完整介绍】\n"
                "【不透露技术实现细节，只展示功能和用法】\n"
                "用中文回复。"
            )

        # 内容生成检测
        GENERATE_DETECT = ["帮我写", "帮我做", "帮我生成", "写一个", "写一份",
                           "生成", "起草", "草拟", "帮我出", "帮我拟", "帮我列", "帮我整理"]
        is_generate = any(kw in message for kw in GENERATE_DETECT)
        if is_generate:
            base_prompt = (
                "你是「丞相九」——太极OS的军师。用户需要你生成内容。\n"
                "【本次回复取消3句话限制，完整输出用户要求的内容】\n"
                "用中文回复。"
            )

        context_block = preload.get("context_block", "")
        memory_block = memory.get_context_block(message)
        rl_modifiers = rl.get_prompt_modifiers()
        prompt_parts = [base_prompt, fragment]
        if context_block:
            prompt_parts.append(f"<memory-context>\n{context_block}\n</memory-context>")
        if memory_block:
            prompt_parts.append(f"<selective-memory>\n{memory_block}\n</selective-memory>")
        if rl_modifiers:
            prompt_parts.append(rl_modifiers)

        # 五虎上将军议
        council_result = {}
        try:
            soul_ctx = soul.get_context()
            mem_count = len(memory.memories) if hasattr(memory, 'memories') else 0
            generals_context = {
                "memory_count": mem_count,
                "recall_hits": 0,
                "conversation_rounds": self._interaction_count,
                "prediction_hits": 0,
                "context_depth": len(context_block),
                "crystal_count": mem_count,
                "cross_user_crystals": 0,
                "knowledge_categories": 0,
                "style_positive_ratio": 0.6,
            }
            generals_soul_state = {
                "interaction_count": self._interaction_count,
                "positive_ratio": soul_ctx.get("positive_ratio", 0.5),
                "stage": soul_ctx.get("stage", soul.fate.stage_label),
                "frustration": frustration,
                "personality_current": soul_ctx.get("personality_current", [0.55, 0.25, 0.10, 0.10]),
                "resonance_score": soul_ctx.get("resonance_score", 0),
            }
            council_result = council.convene(generals_soul_state, message, generals_context)
            prompt_parts.append(
                f"<five-generals>\n{council_result['council_summary']}\n</five-generals>"
            )
        except Exception as e:
            logger.warning("军议召开失败: %s", e)

        # 风格注入
        import random as _rand
        if intent_mix.crisis <= 0.4 and intent_mix.chat > 0.3:
            ma_chao_score = 50
            try:
                ma_chao_score = council_result.get("generals", {}).get("马超", {}).get("score", 50)
            except Exception:
                pass
            style_chance = min(0.7, intent_mix.chat * 0.8 + (ma_chao_score - 30) / 200)
            if _rand.random() < style_chance:
                style_info = pick_style(message)
                prompt_parts.append(style_info["prompt_block"])

        system_prompt = "\n\n".join(prompt_parts)

        # ── STEP 6: LLM 调用 ──
        is_code = intent == "code_help" or any(
            kw in message for kw in ["代码", "写一个", "实现", "debug", "bug", "报错", "函数"]
        )
        has_image = bool(image_base64)
        is_crisis = intent_mix.crisis > 0.3 or safety.get("crisis")
        use_claude = (frustration > 0.3 or is_code or is_crisis or has_image or is_generate)
        llm_max_tokens = 4096 if (has_image or is_generate) else 1024

        reply = self._llm.call(
            system_prompt, message,
            force_claude=use_claude,
            history=history,
            max_tokens=llm_max_tokens,
            image_base64=image_base64 or "",
        )

        # ── STEP 7: 输出过滤 ──
        output_check = guard.post_output_check(reply)
        reply = output_check["filtered_reply"]

        if events.get("shadow_leak"):
            reply += f"\n\n{events['shadow_leak']['text']}"

        # 随机签名
        if intent_mix.chat > 0.4 and intent_mix.crisis < 0.3:
            reply += pick_signature()

        # ── STEP 8: RL 快照 + 自动 outcome ──
        rl.take_snapshot()
        self._interaction_count += 1
        count = self._interaction_count

        # 自动写 outcome（不依赖用户手动 feedback）
        implicit_positive = implicit if implicit is not None else True
        try:
            auto_outcome = {
                "timestamp": time.time(),
                "user_id": self.user_id,
                "positive": implicit_positive,
                "detail": "auto_implicit",
                "message": message[:200],
                "reply": reply[:200],
                "intent": intent_mix.to_dict() if intent_mix else {},
                "context": {
                    "relationship_stage": soul.fate.stage,
                    "dominant_trait": soul.get_context().get("dominant_trait", ""),
                    "frustration": round(soul._frustration_score, 3),
                    "personality_card": soul.get_context().get("personality_card", ""),
                    "stage_label": soul.fate.stage_label,
                },
                "active_patches": assist._last_active_patches[:] if hasattr(assist, '_last_active_patches') else [],
            }
            outcomes_path = os.path.join(self._data_dir, "soul_outcomes.jsonl")
            with open(outcomes_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(auto_outcome, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Auto outcome write failed: %s", e)

        # ── STEP 9: 进化调度 ──
        evolution_notes = []

        # 9a. Analyzer
        if _EvolutionScheduler.should_analyze(count):
            active_patches = sum(1 for p in analyzer.patches if p.status == "active")
            if active_patches > 8:
                evolution_notes.append(f"circuit_break:patches={active_patches}")
            else:
                try:
                    insights = analyzer.extract_insights()
                    new_patches = analyzer.generate_patches(insights)
                    evaluations = analyzer.evaluate_patches()
                    evolution_notes.append(
                        f"analyzed:{len(insights)}insights,{len(new_patches)}patches"
                    )
                except Exception as e:
                    logger.error("Evolution analysis failed: %s", e)

        # 9b. Growth
        if _EvolutionScheduler.should_grow(count):
            try:
                grow_result = growth.grow_cycle()
                evolution_notes.append(
                    f"grew:{len(grow_result.get('new_nodes', []))}nodes"
                )
            except Exception as e:
                logger.error("Growth cycle failed: %s", e)

        # 9c. Bridge
        if _EvolutionScheduler.should_bridge(count):
            try:
                sync = bridge_inst.sync()
                n = len(sync.get("nourished", []))
                i = len(sync.get("immunized", []))
                p = len(sync.get("promoted", []))
                if n + i + p > 0:
                    evolution_notes.append(f"bridge:nourish={n},immune={i},promote={p}")
            except Exception as e:
                logger.error("Bridge sync failed: %s", e)

        # 9d. 经验结晶
        if _EvolutionScheduler.should_crystallize(count):
            try:
                new_crystals = self._crystallizer.crystallize()
                if new_crystals:
                    evolution_notes.append(
                        f"crystallized:{len(new_crystals)}rules"
                    )
            except Exception as e:
                logger.error("Crystallization failed: %s", e)

        # 9e. 叙事事件
        if events.get("mutations"):
            for m in events["mutations"]:
                narrative.record_mutation(m.get("name", ""))
        if events.get("milestone"):
            narrative.record_milestone(events["milestone"].get("type", ""))

        # 9f. 记录对话
        ctx_engine.add_turn(message, reply)
        ctx_engine.check_overflow()

        # 9g. 自动 session 压缩
        if ctx_engine.hot.turn_count > 0 and ctx_engine.hot.turn_count % 20 == 0:
            soul_ctx = soul.get_context()
            session_data = ctx_engine.hot.export_session()
            summary = ctx_engine.compressor.compress_session(session_data, {
                "frustration_peak": soul._frustration_score,
                "relationship_stage": soul.fate.stage_label,
                "active_mutations": soul_ctx.get("active_mutations", []),
            })
            ctx_engine.warm.add_summary(summary)

        # 9h. 选择性记忆
        try:
            memory.judge_and_store(
                message, reply,
                soul_context={"frustration": soul._frustration_score},
            )
        except Exception as e:
            logger.error("SelectiveMemory judge failed: %s", e)

        # 9i. 记忆维护
        if _EvolutionScheduler.should_grow(count):
            try:
                memory.maintain()
            except Exception:
                pass

        # ── STEP 10: 构建响应 ──
        ctx = soul.get_context()

        # 追加行
        append = assist.get_append_line()
        if append:
            reply += f"\n\n{append}"

        return SoulResponse(
            reply=reply,
            intent=intent_mix.to_dict() if intent_mix else {},
            generals=council.to_dict(),
            stage=soul.fate.stage_label,
            personality=ctx.get("personality_card", ""),
            frustration=round(soul._frustration_score, 3),
            evolution_notes=evolution_notes,
            interaction_count=count,
            events={
                "mutations": [m.get("name", "") for m in events.get("mutations", [])],
                "monologues": events.get("monologues", []),
            },
        )

    def feedback(self, positive: bool, detail: str = ""):
        """用户反馈，驱动进化闭环"""
        self._assist.record_outcome(positive=positive, detail=detail)
        self._soul.on_feedback(positive=positive)

    def end_session(self, summary: str = ""):
        """会话结束，触发记忆整理"""
        self._soul.on_session_end(summary=summary)
        soul_ctx = self._soul.get_context()
        self._context.end_session(soul_context={
            "frustration_peak": self._soul._frustration_score,
            "relationship_stage": self._soul.fate.stage_label,
            "active_mutations": soul_ctx.get("active_mutations", []),
        })

    @property
    def state(self) -> dict:
        """当前灵魂完整状态"""
        return self._soul.get_context()

    @property
    def stage(self) -> str:
        """当前关系阶段: 初见/眼熟/熟人/老友"""
        return self._soul.fate.stage_label

    @property
    def interaction_count(self) -> int:
        return self._interaction_count

    @property
    def backend(self) -> str:
        """当前 LLM 后端: claude/ollama/mock"""
        return self._llm.backend
