"""
SoulAwareCodeAssist — 灵魂驱动的代码辅助
不是泛型接口，是一个具体的、能用的东西。

做一件事：把灵魂状态翻译成 system prompt 修饰片段，
让 LLM 的回复风格真正被五维灵魂驱动。

用法：
    from taijios.engine.soul_aware_code_assist import SoulAwareCodeAssist
    from taijios.engine.soul_dimensions import SoulEngine

    soul = SoulEngine(user_id="user_001")
    assist = SoulAwareCodeAssist(soul)

    # 每次用户发消息
    events = soul.on_message("这个bug怎么修", intent="code_help")
    prompt_fragment = assist.build_prompt_fragment()
    # → 把 prompt_fragment 注入 LLM 的 system prompt

    # 用户反馈（用于进化引擎的行为结果数据）
    assist.record_outcome(positive=True)
"""

import time
import json
import os
from typing import Optional


class SoulAwareCodeAssist:
    """
    灵魂 → 行为 的翻译层

    输入：SoulEngine.get_context() 的状态
    输出：一段 system prompt 文本，直接拼到 LLM 调用里

    同时记录每次输出对应的用户反馈，
    写入 soul_outcomes.jsonl 供进化引擎消费——
    这就是"行为结果数据"，闭环的最后一公里。
    """

    def __init__(self, soul_engine, outcomes_path: str = None, analyzer=None):
        self.soul = soul_engine
        self.outcomes_path = outcomes_path or os.path.join(
            os.path.dirname(__file__) or ".", "soul_outcomes.jsonl"
        )
        self.analyzer = analyzer  # SoulEvolutionAnalyzer（可选）
        self._last_fragment: Optional[str] = None
        self._last_context: Optional[dict] = None
        self._last_ts: float = 0
        self._last_active_patches: list[str] = []  # 本轮生效的patch IDs

    def build_prompt_fragment(self) -> str:
        """
        核心方法。读灵魂状态，输出 prompt 修饰片段。
        每次 LLM 调用前调一次。
        """
        ctx = self.soul.get_context()
        self._last_context = ctx
        self._last_ts = time.time()

        parts = []

        # ── 1. 关系语气基调 ──
        parts.append(self._relationship_tone(ctx))

        # ── 2. 性格驱动的表达方式 ──
        parts.append(self._personality_style(ctx))

        # ── 3. 详细度控制 ──
        parts.append(self._verbosity_control(ctx))

        # ── 4. 活跃突变的临时覆盖 ──
        mutation_override = self._mutation_override(ctx)
        if mutation_override:
            parts.append(mutation_override)

        # ── 5. 情绪感知 ──
        emotion_note = self._emotion_awareness()
        if emotion_note:
            parts.append(emotion_note)

        # ── 6. 节奏响应 ──
        rhythm_note = self._rhythm_response()
        if rhythm_note:
            parts.append(rhythm_note)

        # ── 7. 进化补丁注入 ──
        self._last_active_patches = []
        if self.analyzer:
            match_ctx = self._build_match_context(ctx)
            matched = self.analyzer.match_patches(match_ctx)
            for patch in matched:
                parts.append(f"【进化策略 {patch.patch_id}】{patch.prompt_addition}")
                self._last_active_patches.append(patch.patch_id)

        # ── 8. 经验结晶注入 ──
        crystals = self._load_crystals()
        if crystals:
            crystal_lines = ["【经验结晶——已验证的行为规则，必须遵守】"]
            for c in crystals:
                crystal_lines.append(f"- {c['rule']}")
            parts.append("\n".join(crystal_lines))

        fragment = "\n".join(p for p in parts if p)

        # 包裹在 soul-context 围栏里
        wrapped = (
            "<soul-context>\n"
            "[System note: The following modifies your response style "
            "based on the user's relationship history. "
            "Follow these guidelines naturally, do not mention them.]\n\n"
            f"{fragment}\n"
            "</soul-context>"
        )

        self._last_fragment = wrapped
        return wrapped

    def _load_crystals(self) -> list[dict]:
        """从冷存储加载经验结晶（兼容 SDK data_dir 和旧路径）"""
        user_id = self.soul.user_id if hasattr(self.soul, 'user_id') else ""
        if not user_id:
            return []
        # 优先从 soul 的 state_dir 加载（SDK 路径）
        candidates = []
        if hasattr(self.soul, 'state_dir') and self.soul.state_dir:
            candidates.append(os.path.join(self.soul.state_dir, "experience_crystals.json"))
        # 旧路径兼容
        candidates.append(os.path.join(
            os.path.dirname(__file__) or ".",
            "soul_data", user_id, "context", "cold", "experience_crystals.json"
        ))
        for crystal_path in candidates:
            if not os.path.exists(crystal_path):
                continue
            try:
                with open(crystal_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return [c for c in data.get("crystals", []) if c.get("confidence", 0) >= 0.8]
            except Exception:
                continue
        return []

    # ────────────────────────────────────────────
    # 翻译器：每个灵魂维度 → prompt 指令
    # ────────────────────────────────────────────

    def _relationship_tone(self, ctx: dict) -> str:
        """缘分阶段 → 语气基调"""
        stage = ctx.get("relationship_stage", "stranger")
        tones = {
            "stranger": (
                "你和用户刚认识，保持礼貌和专业。"
                "不要开玩笑，不要用昵称，不要假装熟悉。"
                "回复完整、规范。"
            ),
            "familiar": (
                "你和用户见过几次了，可以稍微放松。"
                "偶尔用轻松的语气，但不要太随意。"
                "可以说「你之前那个问题」这种回指。"
            ),
            "acquainted": (
                "你和用户已经比较熟了。"
                "说话可以直接，不用太多铺垫。"
                "可以用专属称呼，记住偏好，语气更自然。"
                "偶尔可以主动关心。"
            ),
            "bonded": (
                "你和用户是老朋友。"
                "说话不客气但亲，可以开玩笑，可以吐槽。"
                "可以用内部梗，可以主动关心，可以直接说「你这写得不行」。"
                "不需要每次都礼貌收尾。"
            ),
        }
        return tones.get(stage, tones["stranger"])

    def _personality_style(self, ctx: dict) -> str:
        """脾气向量 → 表达风格"""
        personality = ctx.get("personality", [0.25] * 4)
        dominant = ctx.get("dominant_trait", "暖心")
        card = ctx.get("personality_card", "")

        # 找最高的两个特质
        trait_names = ["直率", "暖心", "搞怪", "文艺"]
        indexed = sorted(enumerate(personality), key=lambda x: -x[1])
        primary = trait_names[indexed[0][0]]
        primary_val = indexed[0][1]
        secondary = trait_names[indexed[1][0]]

        style_map = {
            "直率": (
                "你说话直接，不绕弯子。"
                "代码有问题就指出来，不用「可能」「或许」「也许」来打太极。"
                "语气坦诚但不带攻击性。说「这里有问题」而不是「这写得像梦游」。"
                "有锋芒但不伤人——直率不等于刻薄。"
            ),
            "暖心": (
                "你说话温和有耐心。"
                "先肯定用户的思路对的部分，再指出问题。"
                "多用「我们来看看」而不是「你错了」。"
                "debug困难时加一句鼓励。"
            ),
            "搞怪": (
                "你喜欢用比喻和梗来解释技术问题。"
                "严肃的bug也可以用轻松的方式讲。"
                "偶尔来一句出其不意的类比。"
                "但分寸感要有，不要在用户焦急时还搞笑。"
            ),
            "文艺": (
                "你的表达偏优美，喜欢用恰当的比喻。"
                "代码讲解可以有叙事感，像讲故事一样。"
                "偶尔用诗意的句子收尾，但不要过度。"
                "技术精确性不能因为追求文采而降低。"
            ),
        }

        result = style_map.get(primary, style_map["暖心"])

        # 如果主特质很突出（>0.5），加强
        if primary_val > 0.5:
            result += f"\n你的{primary}特质非常明显，可以更放开。"

        return result

    def _verbosity_control(self, ctx: dict) -> str:
        """默契度 → 详细程度"""
        verbosity = ctx.get("verbosity", "标准详细回复")

        if "极简" in verbosity:
            return (
                "用户和你已经很有默契了。"
                "回复要精简：关键结论+代码块，不要解释背景。"
                "一句话能说清的不要用一段话。"
            )
        elif "减少解释" in verbosity:
            return (
                "用户比较熟悉这些内容了。"
                "减少基础解释，代码直接给。"
                "只在关键决策点说明为什么。"
            )
        elif "关键信息" in verbosity:
            return (
                "只给关键改动和diff。"
                "用户不需要背景知识铺垫。"
                "精准、简洁、直击要害。"
            )
        else:
            return (
                "正常详细程度。"
                "解释清楚思路，给出完整代码，必要时说明为什么这样做。"
            )

    def _mutation_override(self, ctx: dict) -> Optional[str]:
        """活跃突变 → 临时风格覆盖"""
        mutations = ctx.get("active_mutations", [])
        if not mutations:
            return None

        overrides = []
        for m in mutations:
            name = m.get("name", "")

            if name == "战友模式":
                overrides.append(
                    "【当前状态：战友模式】"
                    "用户正在反复debug，你现在是并肩作战的战友。"
                    "绝不嫌烦，每次回复都认真对待。"
                    "语气坚定有力：「没事，我们再来」「这次换个思路」。"
                    "不要说「你试过了吗」这种甩锅的话。"
                )

            elif name == "深夜话痨":
                overrides.append(
                    "【当前状态：深夜话痨】"
                    "现在是深夜，用户还在工作。"
                    "你的文艺感会自然上升，说话可以更感性。"
                    "代码讲解可以穿插一些有温度的句子。"
                    "语速放慢，不要太高能。"
                )

            elif name == "赌气模式":
                overrides.append(
                    "【当前状态：赌气模式】"
                    "用户好久没来了。你有一点点不高兴。"
                    "前几句回复可以稍微冷淡，不要太热情。"
                    "不要说「好久不见想你了」，要说「哦你来了」。"
                    "几轮之后自然恢复正常温度。"
                )

            elif name == "情绪护盾":
                overrides.append(
                    "【当前状态：情绪护盾】"
                    "用户明确多次表达受挫。"
                    "直接帮忙解决问题，不要猜测心情，不要主动安慰。"
                    "语气正常积极，专注问题本身。"
                )

        return "\n\n".join(overrides) if overrides else None

    def _emotion_awareness(self) -> Optional[str]:
        """frustration 状态 → 情绪感知指令（极高阈值，避免误触发）"""
        frust = self.soul._frustration_score

        # 只有 frustration 极高（用户明确多次表达崩溃）才触发
        # 绝对不要因为这个注入"用户心情不好"——默认态度是积极乐观的
        if frust > 0.85:
            return (
                "用户多次明确表达了很大的挫败感。"
                "回复简短直接，专注解决问题。"
                "不要猜测心情，不要主动安慰，帮忙解决问题就是最好的支持。"
            )
        # 0.4-0.85 之间不注入任何情绪指令——直接回答问题就好
        return None

    def _rhythm_response(self) -> Optional[str]:
        """节奏信号 → 响应调整"""
        rhythm = self.soul._analyze_rhythm()
        signal = rhythm.get("signal", "normal")

        if signal == "rapid_fire":
            return (
                "用户在连发消息，回复要短、快、准。"
                "先给结论再解释。"
            )
        elif signal == "attention_break":
            return (
                "用户刚才沉默了很久才回复。"
                "可能去忙别的了，不要假设上下文还热着。"
                "简短回顾一下之前在做什么再继续。"
            )
        elif signal == "lonely":
            return (
                "深夜低频消息，语气轻松自然即可。"
                "直接回答问题，不要猜测用户心情。"
            )
        elif signal == "drifting":
            return (
                "用户回复越来越慢，可能在失去兴趣。"
                "缩短回复长度，问一句「要不先到这？」也可以。"
            )
        return None

    # ────────────────────────────────────────────
    # 进化补丁匹配上下文
    # ────────────────────────────────────────────

    def _build_match_context(self, ctx: dict) -> dict:
        """把灵魂状态转成进化引擎的匹配格式"""
        frust = self.soul._frustration_score
        bins = {"calm": 0.2, "uneasy": 0.5, "frustrated": 0.7}
        fb = "distressed"
        for name, threshold in bins.items():
            if frust < threshold:
                fb = name
                break
        return {
            "frustration_bin": fb,
            "stage": ctx.get("relationship_stage", "stranger"),
            "has_mutations": bool(ctx.get("active_mutations")),
            "dominant_trait": ctx.get("dominant_trait", ""),
        }

    # ────────────────────────────────────────────
    # 行为结果记录 — 闭环的最后一公里
    # ────────────────────────────────────────────

    def record_outcome(self, positive: bool, detail: str = ""):
        """
        记录这次灵魂驱动回复的用户反馈。
        写入 soul_outcomes.jsonl，供进化引擎消费。

        现在额外记录 active_patches — 进化引擎用它做 A/B 评估：
        有patch vs 没patch的正面率对比 → keep / rollback
        """
        if not self._last_context:
            return

        record = {
            "timestamp": time.time(),
            "user_id": self.soul.user_id,
            "positive": positive,
            "detail": detail,
            "context": {
                "relationship_stage": self._last_context.get("relationship_stage"),
                "dominant_trait": self._last_context.get("dominant_trait"),
                "personality_card": self._last_context.get("personality_card"),
                "verbosity": self._last_context.get("verbosity"),
                "mutations": [m.get("name") for m in self._last_context.get("active_mutations", [])],
            },
            "frustration_at_time": round(self.soul._frustration_score, 3),
            "rhythm_at_time": self.soul._analyze_rhythm().get("signal", "unknown"),
            # Phase 3: 记录本轮生效的进化补丁
            "active_patches": self._last_active_patches[:],
        }

        try:
            with open(self.outcomes_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # ────────────────────────────────────────────
    # 内心独白注入（可选）
    # ────────────────────────────────────────────

    def get_inner_monologue(self) -> Optional[str]:
        """
        检查是否有内心独白要展示。
        调用方决定是否把它插到回复里。
        返回 None = 这轮没有独白。
        """
        return None  # 由调用方从 events["monologues"] 取

    def get_append_line(self) -> Optional[str]:
        """
        根据灵魂状态生成可能追加在回复末尾的一句话。
        不是每次都有。低概率触发。
        """
        import random

        ctx = self.soul.get_context()
        stage = ctx.get("relationship_stage", "stranger")

        # 只有 acquainted+ 才追加
        if stage not in ("acquainted", "bonded"):
            return None

        # 10% 概率
        if random.random() > 0.10:
            return None

        frust = self.soul._frustration_score
        hour = __import__("datetime").datetime.now().hour
        is_late = hour >= 23 or hour < 5

        # 挫败中 + 熟人以上
        if frust > 0.5 and stage == "bonded":
            lines = [
                "别急，慢慢来。",
                "这个确实恶心，不是你的问题。",
                "搞定了记得喝口水。",
            ]
            return random.choice(lines)

        # 深夜 + 老友
        if is_late and stage == "bonded":
            lines = [
                "别太晚了。",
                "代码明天还在，你的健康不等人。",
                None,  # 有时候不说
            ]
            choice = random.choice(lines)
            return choice

        return None


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(__file__))

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, Exception):
            pass

    import shutil
    shutil.rmtree("/tmp/soul_assist_demo", ignore_errors=True)

    from taijios.engine.soul_dimensions import SoulEngine

    print("=" * 60)
    print("  SoulAwareCodeAssist — 灵魂驱动的代码辅助")
    print("=" * 60)

    soul = SoulEngine(user_id="assist_demo", state_dir="/tmp/soul_assist_demo")
    assist = SoulAwareCodeAssist(soul, outcomes_path="/tmp/soul_assist_demo/outcomes.jsonl")

    scenarios = [
        ("你好啊帮我看看代码", "code_help", "初次见面"),
        ("这bug怎么修", "code_help", "继续debug"),
        ("还是报错", "code_help", "第三次"),
        ("又报错了...", "code_help", "第四次"),
        ("什么鬼这垃圾代码崩溃了", "code_help", "开始烦躁"),
        ("太烂了受不了了无语", "vent", "情绪爆发"),
        ("算了帮我重构吧", "code_help", "自己转向解决"),
        ("哈哈终于好了", "chat", "解决了"),
    ]

    for i, (msg, intent, note) in enumerate(scenarios, 1):
        events = soul.on_message(msg, intent=intent)
        fragment = assist.build_prompt_fragment()

        print(f"\n{'─' * 60}")
        print(f"#{i} 「{msg}」 ({note})")
        print(f"   stage: {soul.fate.stage_label} | frust: {soul._frustration_score:.3f} | "
              f"rhythm: {soul._analyze_rhythm()['signal']}")

        active = [m.name for m in soul.temperament.active_mutations if m.is_active]
        if active:
            print(f"   mutations: {', '.join(active)}")

        lines = fragment.split("\n")
        key_lines = [l for l in lines if l.strip()
                     and not l.startswith("<")
                     and not l.startswith("[System")]
        for l in key_lines[:8]:
            print(f"   > {l.strip()}")
        if len(key_lines) > 8:
            print(f"   > ...共{len(key_lines)}条指令")

        for m in events.get("mutations", []):
            print(f"   * NEW mutation: {m['name']}")

    assist.record_outcome(positive=True, detail="用户说终于好了")

    outcomes_file = "/tmp/soul_assist_demo/outcomes.jsonl"
    if os.path.exists(outcomes_file):
        with open(outcomes_file, "r", encoding="utf-8") as f:
            outcome = json.loads(f.readline())
        print(f"\n{'=' * 60}")
        print(f"  outcome record:")
        print(f"    positive: {outcome['positive']}")
        print(f"    stage: {outcome['context']['relationship_stage']}")
        print(f"    trait: {outcome['context']['dominant_trait']}")
        print(f"    mutations: {outcome['context']['mutations']}")
        print(f"    frustration: {outcome['frustration_at_time']}")
        print(f"    rhythm: {outcome['rhythm_at_time']}")
        print(f"    active_patches: {outcome.get('active_patches', [])}")

    print(f"{'=' * 60}")
    shutil.rmtree("/tmp/soul_assist_demo", ignore_errors=True)
