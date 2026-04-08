"""
Football Data Layer — 封装世界杯数据 API 调用。

数据源:
- wc2026api.com: 赛程/分组/球场 (WC2026_API_KEY)
- football-data.org: 球队历史/积分/统计 (FOOTBALL_DATA_API_KEY)

带内存缓存（TTL），避免浪费免费额度。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("gateway.football_data")

# ── API Keys ────────────────────────────────────────────────────

WC2026_API_KEY = os.getenv("WC2026_API_KEY", "")
WC2026_BASE = "https://api.wc2026api.com"

FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "")
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"

# ── Cache ───────────────────────────────────────────────────────

_cache: Dict[str, tuple[float, Any]] = {}
CACHE_TTL = 3600  # 1 hour


def _cached_get(key: str, url: str, headers: dict, timeout: int = 10) -> Any:
    """GET with in-memory TTL cache."""
    now = time.time()
    if key in _cache:
        ts, data = _cache[key]
        if now - ts < CACHE_TTL:
            return data
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            _cache[key] = (now, data)
            return data
        log.warning(f"API {url} returned {resp.status_code}: {resp.text[:200]}")
        return None
    except Exception as e:
        log.warning(f"API {url} failed: {e}")
        return None


# ── wc2026api.com ───────────────────────────────────────────────

def _wc2026_headers() -> dict:
    return {"Authorization": f"Bearer {WC2026_API_KEY}"} if WC2026_API_KEY else {}


def get_upcoming_matches() -> List[dict]:
    """获取世界杯赛程列表。"""
    data = _cached_get("wc2026_matches", f"{WC2026_BASE}/matches", _wc2026_headers())
    if not data:
        return _fallback_matches()
    matches = data if isinstance(data, list) else data.get("matches", data.get("data", []))
    return matches


def get_group_standings() -> List[dict]:
    """获取小组积分榜。"""
    data = _cached_get("wc2026_groups", f"{WC2026_BASE}/groups", _wc2026_headers())
    if not data:
        return []
    return data if isinstance(data, list) else data.get("groups", data.get("data", []))


# ── football-data.org ───────────────────────────────────────────

def _fd_headers() -> dict:
    return {"X-Auth-Token": FOOTBALL_DATA_API_KEY} if FOOTBALL_DATA_API_KEY else {}


def get_team_stats(team_name: str) -> Optional[dict]:
    """获取球队信息和近期战绩。"""
    key = f"fd_team_{team_name.lower()}"
    # Search teams
    data = _cached_get(key, f"{FOOTBALL_DATA_BASE}/teams?limit=5", _fd_headers())
    if not data:
        return None
    teams = data.get("teams", [])
    for t in teams:
        if team_name.lower() in t.get("name", "").lower() or team_name.lower() in t.get("shortName", "").lower():
            return t
    return None


def get_head_to_head(team1: str, team2: str) -> Optional[dict]:
    """获取两队交锋历史（通过 football-data.org）。"""
    # football-data.org 的 h2h 需要 match_id，这里用 LLM 知识补充
    return None


# ── Fallback: 世界杯 2026 静态数据 ──────────────────────────────
# API 不可用时使用，保证 demo 始终能跑

_WC2026_GROUPS = {
    "A": ["美国", "摩洛哥", "待定A3", "待定A4"],
    "B": ["墨西哥", "待定B2", "待定B3", "待定B4"],
    "C": ["加拿大", "待定C2", "待定C3", "待定C4"],
    "D": ["巴西", "待定D2", "待定D3", "待定D4"],
    "E": ["阿根廷", "待定E2", "待定E3", "待定E4"],
    "F": ["法国", "待定F2", "待定F3", "待定F4"],
    "G": ["英格兰", "待定G2", "待定G3", "待定G4"],
    "H": ["德国", "待定H2", "待定H3", "待定H4"],
    "I": ["西班牙", "待定I2", "待定I3", "待定I4"],
    "J": ["葡萄牙", "待定J2", "待定J3", "待定J4"],
    "K": ["荷兰", "待定K2", "待定K3", "待定K4"],
    "L": ["意大利", "待定L2", "待定L3", "待定L4"],
}

_TEAM_PROFILES = {
    "巴西": {"fifa_rank": 5, "style": "技术流、进攻型", "stars": "维尼修斯、罗德里戈", "recent": "预选赛跌宕起伏，后程发力晋级"},
    "阿根廷": {"fifa_rank": 1, "style": "整体攻防、战术灵活", "stars": "梅西（可能告别战）、阿尔瓦雷斯", "recent": "卫冕冠军，美洲杯冠军"},
    "法国": {"fifa_rank": 2, "style": "身体+技术、反击犀利", "stars": "姆巴佩、格列兹曼", "recent": "欧洲杯亚军，实力稳定"},
    "英格兰": {"fifa_rank": 4, "style": "现代传控、定位球强", "stars": "贝林厄姆、萨卡", "recent": "欧洲杯亚军，新生代崛起"},
    "德国": {"fifa_rank": 3, "style": "纪律严明、中场控制", "stars": "穆西亚拉、维尔茨", "recent": "本土欧洲杯后重建，年轻化"},
    "西班牙": {"fifa_rank": 6, "style": "传控足球、青年才俊", "stars": "亚马尔、佩德里", "recent": "欧洲杯冠军，黄金一代"},
    "葡萄牙": {"fifa_rank": 7, "style": "技术全面、个人能力强", "stars": "C罗（可能告别战）、B费", "recent": "欧洲杯八强，新老交替"},
    "荷兰": {"fifa_rank": 8, "style": "全攻全守、战术多变", "stars": "加克波、德容", "recent": "欧洲杯四强，稳步上升"},
    "意大利": {"fifa_rank": 9, "style": "防守反击、战术纪律", "stars": "唐纳鲁马、巴雷拉", "recent": "欧洲杯小组出局后重建"},
    "美国": {"fifa_rank": 14, "style": "体能充沛、快速反击", "stars": "普利西奇、雷纳", "recent": "东道主，主场优势明显"},
    "墨西哥": {"fifa_rank": 15, "style": "技术细腻、短传配合", "stars": "洛萨诺", "recent": "联合东道主，经验丰富"},
    "摩洛哥": {"fifa_rank": 13, "style": "防守稳固、反击锐利", "stars": "哈基米、阿什拉夫", "recent": "2022世界杯四强黑马"},
    "日本": {"fifa_rank": 18, "style": "技术流、团队配合", "stars": "久保建英、三�的薰", "recent": "亚洲杯表现稳定"},
    "韩国": {"fifa_rank": 22, "style": "体能+纪律、永不放弃", "stars": "孙兴慜", "recent": "亚洲传统强队"},
    "加拿大": {"fifa_rank": 43, "style": "身体对抗、快速推进", "stars": "戴维斯", "recent": "联合东道主，历史性参赛"},
}


def _fallback_matches() -> List[dict]:
    """生成静态示例比赛列表（API 不可用时）。"""
    sample_matches = [
        {"id": "wc2026-001", "home": "美国", "away": "摩洛哥", "group": "A", "stadium": "SoFi Stadium, Los Angeles", "date": "2026-06-11", "status": "scheduled"},
        {"id": "wc2026-002", "home": "阿根廷", "away": "待定E2", "group": "E", "stadium": "Hard Rock Stadium, Miami", "date": "2026-06-12", "status": "scheduled"},
        {"id": "wc2026-003", "home": "法国", "away": "待定F2", "group": "F", "stadium": "MetLife Stadium, New York", "date": "2026-06-12", "status": "scheduled"},
        {"id": "wc2026-004", "home": "巴西", "away": "待定D2", "group": "D", "stadium": "AT&T Stadium, Dallas", "date": "2026-06-13", "status": "scheduled"},
        {"id": "wc2026-005", "home": "英格兰", "away": "待定G2", "group": "G", "stadium": "Lincoln Financial Field, Philadelphia", "date": "2026-06-13", "status": "scheduled"},
        {"id": "wc2026-006", "home": "德国", "away": "待定H2", "group": "H", "stadium": "NRG Stadium, Houston", "date": "2026-06-14", "status": "scheduled"},
        {"id": "wc2026-007", "home": "西班牙", "away": "待定I2", "group": "I", "stadium": "Mercedes-Benz Stadium, Atlanta", "date": "2026-06-14", "status": "scheduled"},
        {"id": "wc2026-008", "home": "墨西哥", "away": "待定B2", "group": "B", "stadium": "Estadio Azteca, Mexico City", "date": "2026-06-14", "status": "scheduled"},
    ]
    return sample_matches


def get_team_profile(team_name: str) -> dict:
    """获取球队档案（优先 API，fallback 到静态数据）。"""
    # 先尝试 API
    api_data = get_team_stats(team_name) if FOOTBALL_DATA_API_KEY else None
    if api_data:
        return {
            "name": api_data.get("name", team_name),
            "fifa_rank": api_data.get("fifaRank", "未知"),
            "style": "数据来源: football-data.org",
            "stars": ", ".join([p.get("name", "") for p in api_data.get("squad", [])[:3]]) or "未知",
            "recent": f"成立于 {api_data.get('founded', '未知')}",
        }
    # Fallback 到静态数据
    profile = _TEAM_PROFILES.get(team_name, {})
    if profile:
        return {"name": team_name, **profile}
    return {"name": team_name, "fifa_rank": "未知", "style": "未知", "stars": "未知", "recent": "未知"}


def build_prediction_context(home: str, away: str) -> str:
    """构建预测所需的完整数据上下文。"""
    home_profile = get_team_profile(home)
    away_profile = get_team_profile(away)

    ctx = f"""比赛: {home} vs {away}

{home} 档案:
- FIFA排名: {home_profile.get('fifa_rank', '未知')}
- 风格: {home_profile.get('style', '未知')}
- 核心球员: {home_profile.get('stars', '未知')}
- 近期表现: {home_profile.get('recent', '未知')}

{away} 档案:
- FIFA排名: {away_profile.get('fifa_rank', '未知')}
- 风格: {away_profile.get('style', '未知')}
- 核心球员: {away_profile.get('stars', '未知')}
- 近期表现: {away_profile.get('recent', '未知')}"""

    return ctx
