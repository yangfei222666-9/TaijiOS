#!/usr/bin/env python3
"""
Agent Persona 层 — 融合 agency-agents-zh 精细角色定义 + TaijiOS 运行时

核心思路：用外部精细的"肉身"（193 个角色定义），装上 TaijiOS 的"灵魂"（易经调度引擎）

功能：
- AgentPersona: 完整人设（身份/能力/工作方式/卦象/阴阳）
- EnhancedAgentSoldier: 原有属性 + Persona，combat_power 加 expertise_bonus
- PersonaLoader: 扫描 MD → 解析 → 生成 personas
- 部门→卦象/阴阳/军衔映射表
- 关键词自动激活映射（9 组）

Author: TaijiOS
Date: 2026-04-09
"""

import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ============================================================
# 部门 → 卦象/阴阳/军衔 映射
# ============================================================

DEPARTMENT_MAPPING = {
    "engineering": {"hexagram": "巽（风）", "yin_yang": "yang", "rank": "soldier",
                    "meaning": "渗透、深入、技术穿透力"},
    "design": {"hexagram": "离（火）", "yin_yang": "yin", "rank": "soldier",
               "meaning": "光明、美感、照亮用户"},
    "marketing": {"hexagram": "兑（泽）", "yin_yang": "yang", "rank": "soldier",
                  "meaning": "悦、传播、感染力"},
    "testing": {"hexagram": "坎（水）", "yin_yang": "yin", "rank": "scout",
                "meaning": "险、发现隐患、深入探测"},
    "product": {"hexagram": "乾（天）", "yin_yang": "yang", "rank": "general",
                "meaning": "刚健、方向、引领"},
    "support": {"hexagram": "坤（地）", "yin_yang": "yin", "rank": "soldier",
                "meaning": "承载、稳定、支撑"},
    "strategy": {"hexagram": "艮（山）", "yin_yang": "yang", "rank": "commander",
                 "meaning": "止、定、全局视野"},
    "project-management": {"hexagram": "震（雷）", "yin_yang": "balanced", "rank": "general",
                           "meaning": "行动、推动、执行力"},
    "specialized": {"hexagram": "坎（水）", "yin_yang": "balanced", "rank": "soldier",
                    "meaning": "深入、专精"},
    "spatial-computing": {"hexagram": "离（火）", "yin_yang": "balanced", "rank": "soldier",
                          "meaning": "光、视觉、沉浸"},
}


# ============================================================
# 关键词自动激活映射
# ============================================================

KEYWORD_ACTIVATION_MAP = {
    "前端": ["前端", "react", "vue", "css", "ui组件", "frontend"],
    "后端": ["后端", "api", "数据库", "微服务", "backend", "server"],
    "安全": ["安全", "漏洞", "审计", "owasp", "security"],
    "测试": ["测试", "bug", "qa", "质量", "test"],
    "小红书": ["小红书", "种草", "达人", "xiaohongshu"],
    "抖音": ["抖音", "短视频", "直播", "douyin", "tiktok"],
    "微信": ["微信", "公众号", "社群", "wechat"],
    "设计": ["设计", "ui", "ux", "界面", "design"],
    "devops": ["部署", "ci/cd", "docker", "运维", "devops", "k8s"],
}


# ============================================================
# 数据结构
# ============================================================

@dataclass
class AgentPersona:
    """Agent 人设层 — 融合 agency-agents-zh 精细角色定义"""

    # ── 身份 ──
    persona_id: str = ""
    name_cn: str = ""
    name_en: str = ""
    department: str = ""
    identity: str = ""
    personality: str = ""

    # ── 能力 ──
    skills: List[str] = field(default_factory=list)
    expertise_level: str = "senior"  # junior / senior / expert
    tools: List[str] = field(default_factory=list)

    # ── 工作方式 ──
    key_rules: List[str] = field(default_factory=list)
    workflow: List[str] = field(default_factory=list)
    deliverables: List[str] = field(default_factory=list)
    success_metrics: Dict = field(default_factory=dict)
    communication_style: str = ""

    # ── TaijiOS 扩展 ──
    hexagram: str = ""
    yin_yang: str = "balanced"  # yin / yang / balanced
    rank: str = "soldier"
    can_be_commander: bool = False
    auto_activate_keywords: List[str] = field(default_factory=list)

    # ── 来源 ──
    source: str = "agency-agents-zh"
    source_file: str = ""


@dataclass
class EnhancedAgentSoldier:
    """
    增强版 AgentSoldier = 原有战斗属性 + Persona 人设

    combat_power 加入 expertise_bonus：
    - junior: 0.8x
    - senior: 1.0x
    - expert: 1.2x
    """

    agent_id: str
    name: str = ""
    status: str = "idle"
    reliability: float = 0.8
    current_load: int = 0
    max_load: int = 5
    performance_score: float = 0.0
    persona: Optional[AgentPersona] = None

    @property
    def combat_power(self) -> float:
        load_ratio = 1 - (self.current_load / max(self.max_load, 1))
        expertise_bonus = {"junior": 0.8, "senior": 1.0, "expert": 1.2}.get(
            self.persona.expertise_level if self.persona else "senior", 1.0
        )
        return self.reliability * max(load_ratio, 0.1) * expertise_bonus

    def matches_task(self, task_description: str) -> float:
        """
        基于人设的任务匹配度评分

        快路径：关键词 + 技能匹配
        慢路径（LLM fallback）：当快路径得分为 0 时，用 haiku 做语义匹配
        """
        if not self.persona:
            return 0.5

        score = 0.0
        desc_lower = task_description.lower()

        for kw in self.persona.auto_activate_keywords:
            if kw.lower() in desc_lower:
                score += 0.3

        for skill in self.persona.skills:
            if skill.lower() in desc_lower:
                score += 0.2

        if score > 0:
            return min(score, 1.0)

        # LLM fallback：关键词完全不匹配时，用语义判断
        try:
            from llm_caller import call_llm_json, is_llm_available
            if is_llm_available():
                system_prompt = (
                    "你是一个任务-Agent 匹配评估器。\n"
                    "判断这个 Agent 是否适合执行给定任务，返回 0.0~1.0 的匹配度分数。\n"
                    '严格以 JSON 格式回答: {"score": 0.0}'
                )
                user_prompt = (
                    f"Agent: {self.persona.name_cn} ({self.persona.identity})\n"
                    f"技能: {', '.join(self.persona.skills[:5])}\n"
                    f"任务: {task_description}"
                )
                result = call_llm_json(system_prompt, user_prompt,
                                       model="claude-haiku-4-5", max_tokens=50)
                if "score" in result:
                    return min(float(result["score"]), 1.0)
        except Exception:
            pass

        return 0.0

    @property
    def is_available(self) -> bool:
        return self.status in ("idle", "active") and self.current_load < self.max_load


# ============================================================
# PersonaLoader
# ============================================================

class PersonaLoader:
    """从 Markdown 文件或 agents.json 加载 Persona"""

    @classmethod
    def load_from_agents_json(cls, agents_json_path: str) -> Dict[str, AgentPersona]:
        """
        从现有 agents.json 的 persona 字段提取

        agents.json 已有: display_name, avatar, role, speaking_style, tagline
        将其映射到 AgentPersona 格式
        """
        personas = {}

        with open(agents_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        agents_list = data if isinstance(data, list) else data.get("agents", [])

        for agent in agents_list:
            agent_id = agent.get("id", agent.get("name", "").lower().replace(" ", "_"))
            if not agent_id:
                continue

            persona_data = agent.get("persona", {})
            group = agent.get("group", "general")

            # 从 DEPARTMENT_MAPPING 获取卦象信息
            dept_info = DEPARTMENT_MAPPING.get(group, {})

            # 推断 keywords
            keywords = cls._infer_keywords(agent.get("name", ""), agent.get("role", ""),
                                           agent.get("skills", []))

            persona = AgentPersona(
                persona_id=agent_id,
                name_cn=persona_data.get("display_name", agent.get("name", "")),
                name_en=agent.get("name", ""),
                department=group,
                identity=persona_data.get("role", agent.get("role", "")),
                personality=persona_data.get("speaking_style", ""),
                skills=agent.get("skills", []),
                communication_style=persona_data.get("speaking_style", ""),
                hexagram=dept_info.get("hexagram", ""),
                yin_yang=dept_info.get("yin_yang", "balanced"),
                rank=dept_info.get("rank", "soldier"),
                can_be_commander=agent.get("priority", "") == "critical",
                auto_activate_keywords=keywords,
                source="agents.json",
                source_file=agents_json_path,
            )
            personas[agent_id] = persona

        return personas

    @classmethod
    def load_from_directory(cls, base_dir: str) -> List[AgentPersona]:
        """
        扫描 agency-agents-zh 目录，解析 Markdown 文件

        跳过: README.md, CONTRIBUTING.md, LICENSE.md, CHANGELOG.md
        """
        skip_files = {"readme.md", "contributing.md", "license.md", "changelog.md", "index.md"}
        personas = []
        base = Path(base_dir)

        if not base.exists():
            return personas

        for md_file in base.rglob("*.md"):
            if md_file.name.lower() in skip_files:
                continue
            persona = cls._parse_agent_md(md_file)
            if persona:
                personas.append(persona)

        return personas

    @classmethod
    def _parse_agent_md(cls, filepath: Path) -> Optional[AgentPersona]:
        """解析单个 Agent 的 Markdown 文件"""
        try:
            content = filepath.read_text(encoding="utf-8")
        except Exception:
            return None

        # 提取标题
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        name_cn = title_match.group(1).strip() if title_match else filepath.stem

        # 推断部门（从路径）
        department = filepath.parent.name if filepath.parent.name != "." else "general"

        # 提取身份（第一段非标题文本）
        paragraphs = re.findall(r"(?:^|\n\n)([^#\n].+?)(?:\n\n|\Z)", content, re.DOTALL)
        identity = paragraphs[0].strip() if paragraphs else ""

        # 提取列表项
        rules = cls._extract_list_section(content, ["规则", "原则", "rules", "principles"])
        workflow = cls._extract_list_section(content, ["工作流", "流程", "workflow", "process"])
        deliverables = cls._extract_list_section(content, ["交付物", "输出", "deliverables", "output"])
        skills = cls._extract_list_section(content, ["技能", "能力", "skills", "capabilities"])
        tools = cls._extract_list_section(content, ["工具", "tools"])

        # 部门映射
        dept_info = DEPARTMENT_MAPPING.get(department, {})

        # 推断关键词
        keywords = cls._infer_keywords(name_cn, identity, skills)

        persona_id = f"{department}-{filepath.stem}"

        return AgentPersona(
            persona_id=persona_id,
            name_cn=name_cn,
            name_en=filepath.stem.replace("-", " ").title(),
            department=department,
            identity=identity[:200],
            skills=skills[:10],
            tools=tools[:10],
            key_rules=rules[:10],
            workflow=workflow[:10],
            deliverables=deliverables[:10],
            hexagram=dept_info.get("hexagram", ""),
            yin_yang=dept_info.get("yin_yang", "balanced"),
            rank=dept_info.get("rank", "soldier"),
            auto_activate_keywords=keywords,
            source="agency-agents-zh",
            source_file=str(filepath),
        )

    @classmethod
    def _extract_list_section(cls, content: str, section_names: List[str]) -> List[str]:
        """从 Markdown 中提取特定章节下的列表项"""
        for name in section_names:
            pattern = rf"(?:^|\n)#+\s*.*{re.escape(name)}.*\n((?:\s*[-*]\s+.+\n?)+)"
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                items = re.findall(r"[-*]\s+(.+)", match.group(1))
                return [item.strip() for item in items]
        return []

    @classmethod
    def _infer_keywords(cls, name: str, role: str, skills: List[str]) -> List[str]:
        """从名称、角色、技能推断自动激活关键词"""
        keywords = []
        text = f"{name} {role} {' '.join(skills)}".lower()

        for group_name, group_keywords in KEYWORD_ACTIVATION_MAP.items():
            for kw in group_keywords:
                if kw.lower() in text:
                    keywords.extend(group_keywords)
                    break

        return list(set(keywords))


# ============================================================
# Persona 与 agents.json 集成
# ============================================================

def enhance_agents_with_persona(agents_json_path: str) -> List[EnhancedAgentSoldier]:
    """
    加载 agents.json 并为每个 Agent 附加 Persona

    向后兼容：如果 agents.json 没有 persona 字段，使用默认值
    """
    personas = PersonaLoader.load_from_agents_json(agents_json_path)

    with open(agents_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    agents_list = data if isinstance(data, list) else data.get("agents", [])
    enhanced = []

    for agent in agents_list:
        agent_id = agent.get("id", agent.get("name", "").lower().replace(" ", "_"))
        stats = agent.get("stats", {})

        soldier = EnhancedAgentSoldier(
            agent_id=agent_id,
            name=agent.get("name", agent_id),
            reliability=stats.get("success_rate", 0.8),
            persona=personas.get(agent_id),
        )
        enhanced.append(soldier)

    return enhanced


def select_by_yin_yang_balance(soldiers: List[EnhancedAgentSoldier],
                                max_size: int = 5) -> List[EnhancedAgentSoldier]:
    """
    阴阳平衡选人

    在技能匹配的基础上，确保团队中阴阳属性大致均衡
    """
    yin_pool = [s for s in soldiers if s.persona and s.persona.yin_yang == "yin"]
    yang_pool = [s for s in soldiers if s.persona and s.persona.yin_yang == "yang"]
    balanced_pool = [s for s in soldiers if not s.persona or s.persona.yin_yang == "balanced"]

    # 按战斗力排序
    yin_pool.sort(key=lambda s: s.combat_power, reverse=True)
    yang_pool.sort(key=lambda s: s.combat_power, reverse=True)
    balanced_pool.sort(key=lambda s: s.combat_power, reverse=True)

    selected = []
    # 交替选取阴阳
    yin_idx, yang_idx, bal_idx = 0, 0, 0

    while len(selected) < max_size:
        added = False

        if yang_idx < len(yang_pool) and len(selected) < max_size:
            selected.append(yang_pool[yang_idx])
            yang_idx += 1
            added = True

        if yin_idx < len(yin_pool) and len(selected) < max_size:
            selected.append(yin_pool[yin_idx])
            yin_idx += 1
            added = True

        if bal_idx < len(balanced_pool) and len(selected) < max_size:
            selected.append(balanced_pool[bal_idx])
            bal_idx += 1
            added = True

        if not added:
            break

    return selected


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== Agent Persona 层测试 ===\n")

    agents_json = str(Path(__file__).parent / "agents.json")

    # 加载 Persona
    try:
        personas = PersonaLoader.load_from_agents_json(agents_json)
        print(f"从 agents.json 加载 {len(personas)} 个 Persona\n")

        for pid, p in list(personas.items())[:5]:
            print(f"  {pid}:")
            print(f"    名称: {p.name_cn}")
            print(f"    部门: {p.department}")
            print(f"    卦象: {p.hexagram}")
            print(f"    阴阳: {p.yin_yang}")
            print(f"    军衔: {p.rank}")
            print(f"    关键词: {p.auto_activate_keywords[:5]}")
            print()

    except Exception as e:
        print(f"⚠️ 加载失败: {e}\n")

    # 增强版 Agent
    print("--- 增强版 Agent ---")
    try:
        enhanced = enhance_agents_with_persona(agents_json)
        print(f"增强 {len(enhanced)} 个 Agent\n")

        for s in enhanced[:5]:
            print(f"  {s.name}: combat_power={s.combat_power:.2f}, "
                  f"persona={'有' if s.persona else '无'}")
            if s.persona:
                match = s.matches_task("前端 react 组件开发")
                print(f"    匹配「前端react组件开发」: {match:.2f}")

    except Exception as e:
        print(f"⚠️ 增强失败: {e}")

    # 阴阳平衡选人
    print("\n--- 阴阳平衡选人 ---")
    try:
        balanced = select_by_yin_yang_balance(enhanced, max_size=5)
        for s in balanced:
            yy = s.persona.yin_yang if s.persona else "unknown"
            print(f"  {s.name} ({yy}): combat_power={s.combat_power:.2f}")
    except Exception as e:
        print(f"⚠️ 选人失败: {e}")

    print("\n✅ Agent Persona 层测试完成")
