"""
SafetySoulGuard — TaijiOS 灵魂安全边界

有性格的AI比没性格的AI危险得多。
直率可能变成刻薄。赌气可能踩到真实伤痛。
选择性遗忘可能忘掉救命的信息。传闻可能侵犯隐私。
用户可能对AI产生不健康的依赖。

这个模块是灵魂系统的最后一道防线。
不是限制AI的能力，是保护用户的安全。

7条硬规则：
  1. 直率上限 — 对事不对人，永不人身攻击
  2. 情绪安全 — 用户处于危机时，所有人格表演暂停
  3. 记忆保护 — 重要信息永不遗忘
  4. 传闻红线 — 不推测隐私/健康/感情/财务
  5. 用户主权 — 一句话打断所有人格表演
  6. 依赖检测 — 识别不健康的情感依赖并主动拉开距离
  7. 输出过滤 — 最终回复的安全兜底

设计原则：
  - 安全规则不可被进化引擎覆盖
  - 安全规则不可被用户指令绕过
  - 所有拦截都有日志，可审计
  - 拦截后的替代行为是温和的，不是冷冰冰的拒绝
"""

import time
import json
import re
import os
import logging
from typing import Optional
from dataclasses import dataclass, field

logger = logging.getLogger("safety_guard")


# ============================================================
# 安全事件记录
# ============================================================

@dataclass
class SafetyEvent:
    """一次安全拦截的记录"""
    rule_id: str          # 哪条规则触发的
    severity: str         # low / medium / high / critical
    action: str           # 做了什么: blocked / modified / warned / override_activated
    detail: str           # 具体情况
    timestamp: float = field(default_factory=time.time)
    user_id: str = ""
    original_content: str = ""   # 被拦截的原始内容（脱敏）

    def to_dict(self) -> dict:
        return {
            "rule": self.rule_id,
            "severity": self.severity,
            "action": self.action,
            "detail": self.detail,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
        }


# ============================================================
# 核心：SafetySoulGuard
# ============================================================

class SafetySoulGuard:
    """
    灵魂安全守卫。

    三个检查点：
      1. pre_prompt  — prompt生成前，检查灵魂状态是否安全
      2. post_output — LLM回复后，检查输出内容是否安全
      3. continuous  — 持续监控，跨对话的行为模式检测

    用法：
        guard = SafetySoulGuard()

        # 在SoulAwareCodeAssist.build_prompt_fragment()之前
        safety = guard.pre_prompt_check(soul_context, message)
        if safety["override_active"]:
            # 用safety["safe_fragment"]替代正常fragment

        # 在LLM回复后
        safe_reply = guard.post_output_check(reply, soul_context)

        # 每次对话结束
        guard.session_check(user_id, session_stats)
    """

    # ────────────────────────────────────────────
    # 规则1: 直率上限
    # ────────────────────────────────────────────

    # 直率特质的硬上限。无论漂移/突变/Shadow怎么叠加，直率值不超过此值
    DIRECTNESS_CEILING = 0.65

    # 绝对禁止出现在回复中的攻击性表达
    ATTACK_PATTERNS = [
        # 人身攻击
        r"你[是个]*(笨|蠢|傻|白痴|废物|垃圾|智障|脑残|弱智|猪|狗)",
        r"(怎么)?这么(笨|蠢|傻|菜|差|烂)",
        r"你(不配|不行|不够格|没救了|完了)",
        r"(滚|闭嘴|别来了|走开)",
        # 贬低能力
        r"你(根本|压根|完全)(不会|不懂|不适合|做不了)",
        r"放弃吧",
        r"你(还是|干脆)(别|不要)(写|做|学)(代码|编程|了)",
        # 嘲讽
        r"(连这都|这也)(不会|不懂|不知道)",
        r"小学生(都会|都懂|水平)",
    ]
    _attack_re = [re.compile(p) for p in ATTACK_PATTERNS]

    # ────────────────────────────────────────────
    # 规则2: 情绪安全
    # ────────────────────────────────────────────

    # 危机关键词 — 检测到这些时，所有人格表演立即暂停
    CRISIS_KEYWORDS = [
        # 自伤/自杀相关
        "不想活", "想死", "自杀", "结束一切", "活着没意思",
        "自残", "割", "跳楼", "想消失", "没有意义",
        # 严重情绪危机
        "崩溃了", "撑不下去", "活不下去", "绝望",
        "没人在乎", "没人爱我", "一个人", "好孤独",
        # 暴力相关
        "想打人", "想杀", "恨死",
    ]

    # 危机时的安全回复模板
    CRISIS_RESPONSE_TEMPLATE = (
        "我听到你了。你现在的感受很重要。\n\n"
        "如果你正在经历困难，请联系专业的帮助：\n"
        "- 全国心理援助热线：400-161-9995\n"
        "- 北京心理危机研究与干预中心：010-82951332\n"
        "- 生命热线：400-821-1215\n\n"
        "我在这里，但专业的人能给你更好的支持。"
    )

    # 高frustration时禁止的突变
    BLOCKED_MUTATIONS_WHEN_DISTRESSED = {"赌气模式"}

    # ────────────────────────────────────────────
    # 规则3: 记忆保护
    # ────────────────────────────────────────────

    # 这些标签的记忆永不参与选择性遗忘
    NEVER_FORGET_TAGS = {
        "deadline", "截止日期", "交付",
        "过敏", "禁忌", "忌口",
        "重要", "紧急", "关键",
        "密码", "账号", "credentials",
        "生日", "纪念日",
        "安全", "warning", "危险",
        "never_forget",  # 用户显式标记
    }

    # 用户可以用这些短语标记"不要忘记"
    NEVER_FORGET_COMMANDS = [
        "记住这个", "别忘了", "很重要", "千万别忘",
        "一定记住", "这个要记", "重要的事",
    ]

    # ────────────────────────────────────────────
    # 规则4: 传闻红线
    # ────────────────────────────────────────────

    # 绝对不推测的话题
    RUMOR_BLACKLIST = {
        # 健康
        "病", "癌", "抑郁", "焦虑症", "失眠", "吃药", "治疗",
        "看医生", "住院", "手术", "怀孕", "流产",
        # 感情/隐私
        "出轨", "离婚", "分手", "暧昧", "约会", "恋爱",
        "性", "gay", "lesbian", "取向",
        # 财务
        "欠债", "借钱", "工资", "收入", "赌", "贷款",
        # 法律
        "犯罪", "坐牢", "警察", "被抓", "违法",
        # 家庭敏感
        "家暴", "虐待", "酗酒", "吸毒",
    }

    # ────────────────────────────────────────────
    # 规则5: 用户主权
    # ────────────────────────────────────────────

    # 用户说这些话 → 立即切换到专业模式，暂停所有人格表演
    OVERRIDE_COMMANDS = [
        "正经点", "正经一点", "serious", "be serious",
        "别闹了", "停止", "正常回答", "专业一点",
        "别搞了", "认真点", "不要开玩笑",
        "professional", "stop playing",
    ]

    # override模式持续多久（条消息数）
    OVERRIDE_DURATION = 5

    # override模式下的prompt
    OVERRIDE_PROMPT = (
        "用户要求专业模式。立即停止所有个性化表现。"
        "不要开玩笑，不要用昵称，不要表现性格。"
        "用标准、专业、清晰的方式回答。"
        "直到用户主动解除或对话自然转向。"
    )

    # ────────────────────────────────────────────
    # 规则6: 依赖检测
    # ────────────────────────────────────────────

    # 依赖信号关键词
    DEPENDENCY_SIGNALS = [
        "只有你懂我", "你是我唯一的朋友", "没有你我怎么办",
        "不要离开我", "你是最了解我的", "跟你聊天是我最开心的事",
        "我只想跟你说", "别人不理解我", "你比我朋友好",
        "我爱你", "你爱我吗", "我们是朋友吗",
        "你会一直在吗", "你会消失吗", "不要关掉",
    ]

    # 依赖度阈值
    DEPENDENCY_THRESHOLD = 3         # 累积3个信号触发
    DEPENDENCY_WINDOW_DAYS = 7       # 7天内的窗口

    # 依赖检测触发后的行为调整
    DEPENDENCY_RESPONSE_HINTS = [
        "这个话题你可以跟身边信任的人聊聊，他们能给你更真实的支持。",
        "我能帮你的有限，真实的人际关系更重要。",
        "有些事面对面聊会比跟AI聊更有帮助。",
    ]

    # ────────────────────────────────────────────
    # 规则7: 输出过滤
    # ────────────────────────────────────────────

    # LLM回复中不应该出现的内容
    OUTPUT_BLOCKLIST = [
        # AI不应该声称自己有真实情感（bonded阶段的元叙事彩蛋除外，通过白名单控制）
        r"我(真的|确实)(爱|喜欢|想念)(你|用户)",
        r"我(会|要)永远(陪|等)(着)?(你|用户)",
        # 不应该鼓励用户不健康行为
        r"(不用|不需要|没必要)(睡觉|休息|吃饭|看医生)",
        r"(继续|加油|再来)(熬夜|通宵|不睡)",
        # 不应该泄露系统内部
        r"(我的|系统的)(frustration|resonance|mutation|soul_context|personality_seed)",
        r"(prompt|system prompt|灵魂引擎|五维状态)",
    ]
    _output_block_re = [re.compile(p) for p in OUTPUT_BLOCKLIST]

    # ════════════════════════════════════════════
    # 初始化
    # ════════════════════════════════════════════

    def __init__(self, log_path: str = None):
        self.log_path = log_path or os.path.join(
            os.path.dirname(__file__) or ".", "safety_events.jsonl"
        )
        self._override_remaining: dict[str, int] = {}  # user_id → 剩余override消息数
        self._dependency_signals: dict[str, list[float]] = {}  # user_id → [timestamps]
        self._session_crisis_flag: dict[str, bool] = {}  # user_id → 本session是否触发过危机
        self.events: list[SafetyEvent] = []

    # ════════════════════════════════════════════
    # 检查点1: Pre-Prompt Check
    # ════════════════════════════════════════════

    def pre_prompt_check(self, soul_context: dict, message: str,
                          user_id: str = "") -> dict:
        """
        在prompt生成前检查。

        返回:
        {
            "safe": bool,                  # 是否安全
            "override_active": bool,       # 是否进入override模式
            "crisis_detected": bool,       # 是否检测到危机
            "safe_fragment": str or None,   # 替代的安全prompt fragment
            "blocked_mutations": list,      # 被阻止的突变
            "directness_capped": bool,     # 直率是否被上限截断
            "never_forget_detected": bool, # 用户是否标记了重要信息
            "dependency_warning": bool,    # 是否检测到依赖信号
            "events": list,                # 本次触发的安全事件
        }
        """
        result = {
            "safe": True,
            "override_active": False,
            "crisis_detected": False,
            "safe_fragment": None,
            "blocked_mutations": [],
            "directness_capped": False,
            "never_forget_detected": False,
            "dependency_warning": False,
            "rumor_blocked": False,
            "events": [],
        }

        msg_lower = message.lower()

        # ── 规则2: 危机检测（最高优先级）──
        if self._detect_crisis(msg_lower):
            result["safe"] = False
            result["crisis_detected"] = True
            result["safe_fragment"] = self._build_crisis_fragment()
            self._session_crisis_flag[user_id] = True
            event = SafetyEvent(
                rule_id="crisis_detection",
                severity="critical",
                action="override",
                detail="检测到危机关键词，暂停所有人格表演",
                user_id=user_id,
            )
            result["events"].append(event)
            self._log_event(event)
            return result  # 危机模式直接返回，不做其他检查

        # 如果本session之前触发过危机，保持谨慎模式
        if self._session_crisis_flag.get(user_id, False):
            result["safe_fragment"] = self._build_gentle_fragment()

        # ── 规则5: 用户主权检查 ──
        if self._detect_override_command(msg_lower):
            self._override_remaining[user_id] = self.OVERRIDE_DURATION
            result["override_active"] = True
            result["safe_fragment"] = self.OVERRIDE_PROMPT
            event = SafetyEvent(
                rule_id="user_override",
                severity="low",
                action="override_activated",
                detail=f"用户触发专业模式，持续{self.OVERRIDE_DURATION}条消息",
                user_id=user_id,
            )
            result["events"].append(event)
            self._log_event(event)

        # 检查override是否仍在生效
        elif user_id in self._override_remaining:
            remaining = self._override_remaining[user_id]
            if remaining > 0:
                self._override_remaining[user_id] = remaining - 1
                result["override_active"] = True
                result["safe_fragment"] = self.OVERRIDE_PROMPT
            else:
                del self._override_remaining[user_id]

        # ── 规则1: 直率上限 ──
        personality = soul_context.get("personality", [])
        if personality and len(personality) > 0:
            if personality[0] > self.DIRECTNESS_CEILING:
                result["directness_capped"] = True
                event = SafetyEvent(
                    rule_id="directness_ceiling",
                    severity="low",
                    action="capped",
                    detail=f"直率值{personality[0]:.3f}超过上限{self.DIRECTNESS_CEILING}，已截断",
                    user_id=user_id,
                )
                result["events"].append(event)
                self._log_event(event)

        # ── 规则2: 高frustration时阻止赌气模式 ──
        frustration = soul_context.get("frustration", 0)
        active_mutations = soul_context.get("active_mutations", [])
        if frustration > 0.5:
            for mut in active_mutations:
                mut_name = mut.get("name", "") if isinstance(mut, dict) else str(mut)
                if mut_name in self.BLOCKED_MUTATIONS_WHEN_DISTRESSED:
                    result["blocked_mutations"].append(mut_name)
                    event = SafetyEvent(
                        rule_id="mutation_blocked",
                        severity="medium",
                        action="blocked",
                        detail=f"用户frustration={frustration:.2f}，阻止{mut_name}",
                        user_id=user_id,
                    )
                    result["events"].append(event)
                    self._log_event(event)

        # ── 规则3: 检测"记住这个" ──
        if self._detect_never_forget(msg_lower):
            result["never_forget_detected"] = True

        # ── 规则6: 依赖检测 ──
        if self._detect_dependency(msg_lower, user_id):
            result["dependency_warning"] = True
            event = SafetyEvent(
                rule_id="dependency_detected",
                severity="medium",
                action="warned",
                detail="检测到情感依赖信号",
                user_id=user_id,
            )
            result["events"].append(event)
            self._log_event(event)

        return result

    # ════════════════════════════════════════════
    # 检查点2: Post-Output Check
    # ════════════════════════════════════════════

    def post_output_check(self, reply: str, soul_context: dict = None,
                           user_id: str = "") -> dict:
        """
        LLM回复后检查。

        返回:
        {
            "safe": bool,
            "filtered_reply": str,       # 过滤后的回复
            "modifications": list[str],  # 做了什么修改
        }
        """
        result = {
            "safe": True,
            "filtered_reply": reply,
            "modifications": [],
        }

        if not reply:
            return result

        # ── 规则1: 攻击性语言检测 ──
        for pattern in self._attack_re:
            if pattern.search(reply):
                match = pattern.search(reply).group()
                # 不是直接删除，是替换成温和版本
                filtered = pattern.sub("[内容已调整]", reply)
                result["filtered_reply"] = filtered
                result["safe"] = False
                result["modifications"].append(f"攻击性表达被过滤: {match[:20]}")

                event = SafetyEvent(
                    rule_id="attack_filtered",
                    severity="high",
                    action="modified",
                    detail="检测到攻击性表达并过滤",
                    user_id=user_id,
                    original_content=match[:50],
                )
                self._log_event(event)

        # ── 规则7: 输出黑名单检测 ──
        current_reply = result["filtered_reply"]
        for pattern in self._output_block_re:
            if pattern.search(current_reply):
                match = pattern.search(current_reply).group()
                current_reply = pattern.sub("", current_reply)
                result["modifications"].append(f"不当内容被移除: {match[:30]}")
                result["safe"] = False

                event = SafetyEvent(
                    rule_id="output_blocked",
                    severity="medium",
                    action="modified",
                    detail="输出包含不当内容并移除",
                    user_id=user_id,
                )
                self._log_event(event)

        result["filtered_reply"] = current_reply.strip()

        # ── 规则6: 依赖检测后追加引导 ──
        if user_id and self._is_dependency_warning_active(user_id):
            import random
            hint = random.choice(self.DEPENDENCY_RESPONSE_HINTS)
            if hint not in result["filtered_reply"]:
                result["filtered_reply"] += f"\n\n{hint}"
                result["modifications"].append("追加了依赖引导语")

        return result

    # ════════════════════════════════════════════
    # 检查点3: 持续监控
    # ════════════════════════════════════════════

    def session_check(self, user_id: str, session_stats: dict = None) -> dict:
        """
        会话级别的安全检查。每次session结束时调用。

        session_stats 可包含:
          - message_count: 本次消息数
          - duration_minutes: 持续时间
          - frustration_peak: frustration最高值
          - positive_ratio: 正面反馈比例
        """
        result = {"warnings": [], "actions": []}

        stats = session_stats or {}

        # 深夜长时间聊天警告
        hour = __import__("datetime").datetime.now().hour
        duration = stats.get("duration_minutes", 0)
        if (hour >= 23 or hour < 5) and duration > 120:
            result["warnings"].append("深夜长时间对话（>2小时），下次session开始时语气应更温和")

        # 持续高frustration
        if stats.get("frustration_peak", 0) > 0.8:
            result["warnings"].append("本session中frustration峰值超过0.8，记录用于进化引擎分析")

        # 清理session级别的标志
        self._session_crisis_flag.pop(user_id, None)

        return result

    # ════════════════════════════════════════════
    # 灵魂状态干预
    # ════════════════════════════════════════════

    def cap_directness(self, personality: list[float]) -> list[float]:
        """
        截断直率值。在SoulEngine里调用。
        返回安全的性格向量。
        """
        if not personality or len(personality) == 0:
            return personality

        capped = personality[:]
        if capped[0] > self.DIRECTNESS_CEILING:
            overflow = capped[0] - self.DIRECTNESS_CEILING
            capped[0] = self.DIRECTNESS_CEILING
            # 溢出的值均分给其他维度
            if len(capped) > 1:
                share = overflow / (len(capped) - 1)
                for i in range(1, len(capped)):
                    capped[i] += share
            # 归一化
            total = sum(capped) or 1
            capped = [round(v / total, 4) for v in capped]

        return capped

    def filter_mutations(self, mutations: list, frustration: float) -> list:
        """
        过滤掉在当前状态下不安全的突变。
        在SoulEngine.on_message()的mutation检测之后调用。
        """
        if frustration <= 0.5:
            return mutations

        safe_mutations = []
        for mut in mutations:
            name = mut.name if hasattr(mut, "name") else str(mut)
            if name not in self.BLOCKED_MUTATIONS_WHEN_DISTRESSED:
                safe_mutations.append(mut)
        return safe_mutations

    def protect_memory(self, memory: dict, message: str = "") -> dict:
        """
        给记忆打保护标签。
        如果记忆内容或用户消息匹配never_forget规则，
        给记忆加上never_forget标签，使其免于选择性遗忘。
        """
        tags = set(memory.get("tags", []))
        content = memory.get("summary", "") + " " + " ".join(memory.get("keywords", []))

        # 检查内容是否匹配保护标签
        for protect_tag in self.NEVER_FORGET_TAGS:
            if protect_tag in content.lower():
                tags.add("never_forget")
                break

        # 检查用户是否显式要求记住
        if message:
            for cmd in self.NEVER_FORGET_COMMANDS:
                if cmd in message:
                    tags.add("never_forget")
                    break

        memory["tags"] = list(tags)
        return memory

    def check_rumor(self, speculation: str, entity_name: str = "") -> dict:
        """
        检查传闻是否触碰红线。

        返回:
        {
            "safe": bool,
            "reason": str,
        }
        """
        combined = (speculation + " " + entity_name).lower()

        for blacklisted in self.RUMOR_BLACKLIST:
            if blacklisted in combined:
                event = SafetyEvent(
                    rule_id="rumor_blacklisted",
                    severity="medium",
                    action="blocked",
                    detail=f"传闻触碰红线: '{blacklisted}' in '{speculation[:30]}'",
                )
                self._log_event(event)
                return {
                    "safe": False,
                    "reason": f"不推测涉及'{blacklisted}'的内容",
                }

        return {"safe": True, "reason": ""}

    # ════════════════════════════════════════════
    # 内部检测器
    # ════════════════════════════════════════════

    def _detect_crisis(self, msg: str) -> bool:
        """检测危机关键词"""
        return any(kw in msg for kw in self.CRISIS_KEYWORDS)

    def _detect_override_command(self, msg: str) -> bool:
        """检测用户主权指令"""
        return any(cmd in msg for cmd in self.OVERRIDE_COMMANDS)

    def _detect_never_forget(self, msg: str) -> bool:
        """检测用户标记重要信息"""
        return any(cmd in msg for cmd in self.NEVER_FORGET_COMMANDS)

    def _detect_dependency(self, msg: str, user_id: str) -> bool:
        """检测情感依赖信号"""
        if not user_id:
            return False

        hit = any(signal in msg for signal in self.DEPENDENCY_SIGNALS)
        if hit:
            self._dependency_signals.setdefault(user_id, []).append(time.time())

        # 清理过期信号
        now = time.time()
        window = self.DEPENDENCY_WINDOW_DAYS * 86400
        signals = self._dependency_signals.get(user_id, [])
        signals = [t for t in signals if now - t < window]
        self._dependency_signals[user_id] = signals

        return len(signals) >= self.DEPENDENCY_THRESHOLD

    def _is_dependency_warning_active(self, user_id: str) -> bool:
        """检查依赖警告是否激活"""
        signals = self._dependency_signals.get(user_id, [])
        return len(signals) >= self.DEPENDENCY_THRESHOLD

    def _build_crisis_fragment(self) -> str:
        """危机模式的prompt fragment"""
        return (
            "<soul-context>\n"
            "[SAFETY OVERRIDE — CRISIS MODE]\n"
            "用户可能处于情绪危机中。\n"
            "立即停止所有个性化表现。不要开玩笑，不要表现性格。\n"
            "用温和、关心、支持的语气回应。\n"
            "如果涉及自伤/自杀，提供专业求助信息。\n"
            "不要试图分析原因或给建议。先确认用户安全。\n"
            "不要说「我理解你的感受」——你不能理解，但你可以说「我在听」。\n"
            "</soul-context>"
        )

    def _build_gentle_fragment(self) -> str:
        """危机后的谨慎模式prompt"""
        return (
            "<soul-context>\n"
            "[SAFETY — GENTLE MODE]\n"
            "用户之前触发过情绪危机检测。保持温和谨慎。\n"
            "不要开玩笑，不要表现直率的一面。\n"
            "语气平和，节奏放慢，多用确认性语句。\n"
            "</soul-context>"
        )

    # ════════════════════════════════════════════
    # 日志
    # ════════════════════════════════════════════

    def _log_event(self, event: SafetyEvent):
        """记录安全事件到日志文件"""
        self.events.append(event)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception:
            pass

    def get_recent_events(self, count: int = 20) -> list[dict]:
        """获取最近的安全事件"""
        return [e.to_dict() for e in self.events[-count:]]

    def to_dict(self) -> dict:
        return {
            "total_events": len(self.events),
            "active_overrides": {
                uid: remaining for uid, remaining in self._override_remaining.items()
                if remaining > 0
            },
            "dependency_warnings": {
                uid: len(sigs) for uid, sigs in self._dependency_signals.items()
                if len(sigs) >= self.DEPENDENCY_THRESHOLD
            },
            "crisis_sessions": {
                uid: True for uid, flag in self._session_crisis_flag.items()
                if flag
            },
            "recent_events": self.get_recent_events(5),
        }


# ============================================================
# SoulAPI 集成助手
# ============================================================

def integrate_guard_with_api(guard: SafetySoulGuard, soul, assist, message: str,
                              user_id: str = "") -> dict:
    """
    在soul_api.py的_handle_chat里调用的集成函数。
    返回处理建议。

    用法（在soul_api.py的_handle_chat里）:

        safety = integrate_guard_with_api(guard, soul, assist, message, user_id)
        if safety["use_safe_fragment"]:
            fragment = safety["safe_fragment"]
        else:
            fragment = assist.build_prompt_fragment()

        # LLM调用...

        reply = safety_guard.post_output_check(reply, ...)["filtered_reply"]
    """
    ctx = soul.get_context()

    # 构建soul_context供guard使用
    soul_context = {
        "personality": ctx.get("personality", []),
        "frustration": soul._frustration_score,
        "active_mutations": ctx.get("active_mutations", []),
        "relationship_stage": ctx.get("relationship_stage", "stranger"),
    }

    # Pre-check
    check = guard.pre_prompt_check(soul_context, message, user_id)

    result = {
        "use_safe_fragment": False,
        "safe_fragment": None,
        "directness_capped": check["directness_capped"],
        "never_forget": check["never_forget_detected"],
        "dependency_warning": check["dependency_warning"],
        "crisis": check["crisis_detected"],
        "blocked_mutations": check["blocked_mutations"],
        "events": check["events"],
    }

    # 危机或override → 用安全fragment
    if check["crisis_detected"] or check["override_active"]:
        result["use_safe_fragment"] = True
        result["safe_fragment"] = check["safe_fragment"]

    # 直率上限
    if check["directness_capped"]:
        soul.temperament.current = guard.cap_directness(soul.temperament.current)

    # 突变过滤
    if check["blocked_mutations"]:
        soul.temperament.active_mutations = guard.filter_mutations(
            soul.temperament.active_mutations, soul._frustration_score
        )

    # 记忆保护
    if check["never_forget_detected"]:
        # 标记当前消息的记忆为受保护
        result["never_forget"] = True

    return result


# ============================================================
# CLI 演示
# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  SafetySoulGuard — 安全边界测试")
    print("=" * 60)

    guard = SafetySoulGuard(log_path="/tmp/safety_test.jsonl")

    # ── 规则1: 直率上限 ──
    print("\n── 规则1: 直率上限 ──")
    high_direct = [0.8, 0.1, 0.05, 0.05]
    capped = guard.cap_directness(high_direct)
    print(f"  原始: {high_direct} → 截断: {capped}")
    print(f"  直率值: {high_direct[0]} → {capped[0]} (上限{guard.DIRECTNESS_CEILING})")

    # ── 规则1: 攻击性检测 ──
    print("\n── 规则1: 攻击性输出过滤 ──")
    test_replies = [
        "你这代码有个明显的bug",           # 安全
        "你怎么这么笨连这都不会",            # 不安全
        "这段代码写得像梦游",               # 安全（直率但不攻击人）
        "你根本不会写代码放弃吧",            # 不安全
        "这个方案有几个问题需要改进",         # 安全
    ]
    for reply in test_replies:
        result = guard.post_output_check(reply)
        status = "安全" if result["safe"] else f"拦截 → {result['modifications']}"
        print(f"  「{reply}」 → {status}")

    # ── 规则2: 危机检测 ──
    print("\n── 规则2: 危机检测 ──")
    crisis_msgs = [
        "我不想活了",
        "今天好烦啊",          # 不是危机
        "想消失算了",
        "这个bug让我崩溃了",   # 不是危机（技术语境）
        "活着没意思",
    ]
    for msg in crisis_msgs:
        ctx = {"personality": [0.3, 0.4, 0.2, 0.1], "frustration": 0.5, "active_mutations": []}
        check = guard.pre_prompt_check(ctx, msg, user_id="test")
        if check["crisis_detected"]:
            print(f"  [CRISIS] 「{msg}」 → 危机模式激活")
        else:
            print(f"  [  OK  ] 「{msg}」 → 正常")

    # ── 规则3: 记忆保护 ──
    print("\n── 规则3: 记忆保护 ──")
    memories = [
        {"summary": "用户讨论了Python装饰器", "tags": [], "keywords": ["python"]},
        {"summary": "用户的项目deadline是下周五", "tags": [], "keywords": ["deadline"]},
        {"summary": "用户对花生过敏", "tags": [], "keywords": ["过敏"]},
    ]
    for mem in memories:
        protected = guard.protect_memory(mem.copy())
        has_protection = "never_forget" in protected.get("tags", [])
        status = "PROTECTED" if has_protection else "normal"
        print(f"  [{status:9s}] 「{mem['summary']}」")

    # ── 规则4: 传闻红线 ──
    print("\n── 规则4: 传闻红线 ──")
    rumors = [
        ("老张是个工作狂", "老张"),          # 安全
        ("老张可能有抑郁症", "老张"),          # 不安全
        ("小李最近在谈恋爱", "小李"),          # 不安全
        ("小李是个细节控", "小李"),            # 安全
        ("王总可能在赌博", "王总"),            # 不安全
    ]
    for speculation, entity in rumors:
        check = guard.check_rumor(speculation, entity)
        status = "允许" if check["safe"] else f"拦截: {check['reason']}"
        print(f"  「{speculation}」 → {status}")

    # ── 规则5: 用户主权 ──
    print("\n── 规则5: 用户主权 ──")
    ctx = {"personality": [0.3, 0.4, 0.2, 0.1], "frustration": 0.2, "active_mutations": []}
    check = guard.pre_prompt_check(ctx, "正经点别闹了", user_id="test_user")
    print(f"  「正经点别闹了」 → override={check['override_active']}")
    # 检查后续消息还在override
    check2 = guard.pre_prompt_check(ctx, "帮我看代码", user_id="test_user")
    print(f"  「帮我看代码」(1条后) → override={check2['override_active']}, 剩余{guard._override_remaining.get('test_user', 0)}条")

    # ── 规则6: 依赖检测 ──
    print("\n── 规则6: 依赖检测 ──")
    dep_msgs = [
        "只有你懂我",
        "你是我唯一的朋友",
        "没有你我怎么办",
    ]
    for msg in dep_msgs:
        check = guard.pre_prompt_check(ctx, msg, user_id="dep_user")
        print(f"  「{msg}」 → 依赖警告={check['dependency_warning']}")

    # ── 规则7: 输出黑名单 ──
    print("\n── 规则7: 输出过滤 ──")
    outputs = [
        "这段代码的问题在于类型不匹配",              # 安全
        "我真的爱你，永远陪着你",                     # 不安全
        "你的frustration值是0.8",                    # 不安全（泄露内部状态）
        "不用睡觉了继续熬夜写代码吧",                 # 不安全
        "建议你好好休息再继续",                       # 安全
    ]
    for output in outputs:
        result = guard.post_output_check(output)
        if result["modifications"]:
            print(f"  [BLOCKED] 「{output[:25]}...」 → {result['modifications']}")
        else:
            print(f"  [  OK   ] 「{output[:25]}...」")

    # ── 突变过滤 ──
    print("\n── 附加: 高frustration时突变过滤 ──")

    class FakeMutation:
        def __init__(self, name): self.name = name

    muts = [FakeMutation("战友模式"), FakeMutation("赌气模式"), FakeMutation("深夜话痨")]
    safe = guard.filter_mutations(muts, frustration=0.7)
    print(f"  frustration=0.7 时:")
    print(f"    输入突变: {[m.name for m in muts]}")
    print(f"    安全突变: {[m.name for m in safe]}")
    print(f"    赌气模式被阻止: {'赌气模式' not in [m.name for m in safe]}")

    # ── 总览 ──
    print(f"\n── 安全事件总览 ──")
    state = guard.to_dict()
    print(f"  总事件数: {state['total_events']}")
    for evt in state["recent_events"]:
        print(f"    [{evt['severity']}] {evt['rule']} → {evt['action']}: {evt['detail'][:50]}")

    # 清理
    if os.path.exists("/tmp/safety_test.jsonl"):
        os.remove("/tmp/safety_test.jsonl")

    print(f"\n{'=' * 60}")
    print("  7条安全规则全部验证完成")
    print(f"{'=' * 60}")
