#!/usr/bin/env python3
# aios/core/budget.py - 资源管理系统
"""
资源感知系统，追踪 token 和时间预算。

Token Usage Schema:
{
  "ts": "ISO-8601",
  "epoch": unix_seconds,
  "input_tokens": int,
  "output_tokens": int,
  "total_tokens": int,
  "model": "model_name",
  "task": "task_description"
}

Budget Config Schema:
{
  "daily_token_budget": int,
  "weekly_token_budget": int,
  "heartbeat_time_limit_seconds": int
}
"""

import json
import time
from pathlib import Path
from typing import Dict, Optional
from datetime import datetime

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.config import get_path


def _usage_path() -> Path:
    """获取 token 使用日志路径"""
    base = get_path("paths.data")
    if base:
        return base / "token_usage.jsonl"
    return Path(__file__).resolve().parent.parent / "data" / "token_usage.jsonl"


def _config_path() -> Path:
    """获取预算配置路径"""
    base = get_path("paths.data")
    if base:
        return base / "budget_config.json"
    return Path(__file__).resolve().parent.parent / "data" / "budget_config.json"


def _heartbeat_path() -> Path:
    """获取心跳时间日志路径"""
    base = get_path("paths.data")
    if base:
        return base / "heartbeat_time.jsonl"
    return Path(__file__).resolve().parent.parent / "data" / "heartbeat_time.jsonl"


def _baseline_path() -> Path:
    """获取历史基线数据路径"""
    return Path(__file__).resolve().parent.parent / "learning" / "baseline.jsonl"


def _append_jsonl(path: Path, obj: dict):
    """追加 JSONL 记录"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _load_config() -> Dict:
    """加载预算配置"""
    path = _config_path()
    if not path.exists():
        # 默认配置
        default = {
            "daily_token_budget": 100000,
            "weekly_token_budget": 500000,
            "heartbeat_time_limit_seconds": 30,
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(default, f, indent=2, ensure_ascii=False)
        return default

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _save_config(config: Dict):
    """保存预算配置"""
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def record_usage(
    input_tokens: int, output_tokens: int, model: str, task: str = "unknown"
):
    """
    记录 token 使用。

    Args:
        input_tokens: 输入 token 数
        output_tokens: 输出 token 数
        model: 模型名称
        task: 任务描述
    """
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "epoch": int(time.time()),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "model": model,
        "task": task,
    }
    _append_jsonl(_usage_path(), record)


def record_heartbeat_time(seconds: float):
    """
    记录心跳执行时间。

    Args:
        seconds: 执行时间（秒）
    """
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "epoch": int(time.time()),
        "seconds": round(seconds, 3),
    }
    _append_jsonl(_heartbeat_path(), record)


def _get_usage_in_period(since_epoch: int) -> int:
    """获取指定时间段内的 token 使用量"""
    path = _usage_path()
    if not path.exists():
        return 0

    total = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("epoch", 0) >= since_epoch:
                    total += record.get("total_tokens", 0)
            except Exception:
                continue

    return total


def _load_baseline_tokens() -> int:
    """从 baseline.jsonl 读取历史平均 token 消耗（估算）"""
    path = _baseline_path()
    if not path.exists():
        return 0

    # 读取最近的基线数据，估算每日 token 消耗
    # baseline.jsonl 没有直接的 token 字段，这里返回 0
    # 实际使用中可以根据 tool_p95_ms 等指标估算
    return 0


def check_budget() -> Dict:
    """
    检查预算使用情况。

    Returns:
        {
            "daily_used": int,
            "daily_budget": int,
            "daily_pct": float,
            "weekly_used": int,
            "weekly_budget": int,
            "weekly_pct": float,
            "alert_level": "ok|warn|crit"
        }
    """
    config = _load_config()
    now = int(time.time())

    # 计算今日和本周的起始时间
    today_start = now - (now % 86400) + time.timezone
    week_start = today_start - (datetime.now().weekday() * 86400)

    daily_used = _get_usage_in_period(today_start)
    weekly_used = _get_usage_in_period(week_start)

    daily_budget = config.get("daily_token_budget", 100000)
    weekly_budget = config.get("weekly_token_budget", 500000)

    daily_pct = daily_used / daily_budget if daily_budget > 0 else 0
    weekly_pct = weekly_used / weekly_budget if weekly_budget > 0 else 0

    # 告警级别
    max_pct = max(daily_pct, weekly_pct)
    if max_pct >= 0.9:
        alert_level = "crit"
    elif max_pct >= 0.7:
        alert_level = "warn"
    else:
        alert_level = "ok"

    return {
        "daily_used": daily_used,
        "daily_budget": daily_budget,
        "daily_pct": round(daily_pct, 3),
        "weekly_used": weekly_used,
        "weekly_budget": weekly_budget,
        "weekly_pct": round(weekly_pct, 3),
        "alert_level": alert_level,
    }


def get_heartbeat_stats(days: int = 7) -> Dict:
    """
    获取心跳时间统计。

    Returns:
        {
            "count": int,
            "avg_seconds": float,
            "max_seconds": float,
            "over_limit_count": int
        }
    """
    path = _heartbeat_path()
    if not path.exists():
        return {
            "count": 0,
            "avg_seconds": 0.0,
            "max_seconds": 0.0,
            "over_limit_count": 0,
        }

    config = _load_config()
    limit = config.get("heartbeat_time_limit_seconds", 30)
    cutoff = time.time() - days * 86400

    times = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("epoch", 0) >= cutoff:
                    times.append(record.get("seconds", 0))
            except Exception:
                continue

    if not times:
        return {
            "count": 0,
            "avg_seconds": 0.0,
            "max_seconds": 0.0,
            "over_limit_count": 0,
        }

    return {
        "count": len(times),
        "avg_seconds": round(sum(times) / len(times), 2),
        "max_seconds": round(max(times), 2),
        "over_limit_count": sum(1 for t in times if t > limit),
    }


def update_config(
    daily_budget: Optional[int] = None,
    weekly_budget: Optional[int] = None,
    heartbeat_limit: Optional[int] = None,
):
    """
    更新预算配置。

    Args:
        daily_budget: 每日 token 预算
        weekly_budget: 每周 token 预算
        heartbeat_limit: 心跳时间限制（秒）
    """
    config = _load_config()

    if daily_budget is not None:
        config["daily_token_budget"] = daily_budget
    if weekly_budget is not None:
        config["weekly_token_budget"] = weekly_budget
    if heartbeat_limit is not None:
        config["heartbeat_time_limit_seconds"] = heartbeat_limit

    _save_config(config)


# ── CLI ──


def _format_budget(budget: Dict, fmt: str = "default") -> str:
    """格式化预算信息"""
    alert_emoji = {"ok": "✅", "warn": "⚠️", "crit": "🚨"}.get(
        budget["alert_level"], "❓"
    )

    if fmt == "telegram":
        return (
            f"{alert_emoji} Token 预算\n"
            f"今日: {budget['daily_used']}/{budget['daily_budget']} ({budget['daily_pct']:.1%})\n"
            f"本周: {budget['weekly_used']}/{budget['weekly_budget']} ({budget['weekly_pct']:.1%})"
        )
    else:
        return (
            f"=== Token Budget Status ===\n"
            f"Alert Level: {budget['alert_level'].upper()}\n"
            f"\n"
            f"Daily:\n"
            f"  Used: {budget['daily_used']:,}\n"
            f"  Budget: {budget['daily_budget']:,}\n"
            f"  Percentage: {budget['daily_pct']:.1%}\n"
            f"\n"
            f"Weekly:\n"
            f"  Used: {budget['weekly_used']:,}\n"
            f"  Budget: {budget['weekly_budget']:,}\n"
            f"  Percentage: {budget['weekly_pct']:.1%}"
        )


def _format_heartbeat(stats: Dict, fmt: str = "default") -> str:
    """格式化心跳统计"""
    if fmt == "telegram":
        return (
            f"⏱️ 心跳统计\n"
            f"次数: {stats['count']} | 平均: {stats['avg_seconds']}s\n"
            f"最大: {stats['max_seconds']}s | 超限: {stats['over_limit_count']}"
        )
    else:
        return (
            f"=== Heartbeat Time Statistics ===\n"
            f"Count: {stats['count']}\n"
            f"Average: {stats['avg_seconds']}s\n"
            f"Max: {stats['max_seconds']}s\n"
            f"Over Limit: {stats['over_limit_count']}"
        )


def main():
    import argparse
    import sys
    import io

    # 修复 Windows 控制台编码
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    parser = argparse.ArgumentParser(description="资源预算 CLI")
    parser.add_argument("action", choices=["status", "record", "config"], help="操作")
    parser.add_argument("--input", type=int, help="输入 token 数")
    parser.add_argument("--output", type=int, help="输出 token 数")
    parser.add_argument("--model", help="模型名称")
    parser.add_argument("--task", default="manual", help="任务描述")
    parser.add_argument("--daily", type=int, help="设置每日预算")
    parser.add_argument("--weekly", type=int, help="设置每周预算")
    parser.add_argument("--heartbeat-limit", type=int, help="设置心跳时间限制")
    parser.add_argument(
        "--format", choices=["default", "telegram"], default="default", help="输出格式"
    )
    args = parser.parse_args()

    if args.action == "status":
        budget = check_budget()
        print(_format_budget(budget, args.format))
        print()
        heartbeat = get_heartbeat_stats()
        print(_format_heartbeat(heartbeat, args.format))

    elif args.action == "record":
        if args.input is None or args.output is None or args.model is None:
            print("错误: --input, --output, --model 必须提供")
            return
        record_usage(args.input, args.output, args.model, args.task)
        print(f"已记录: {args.input + args.output} tokens ({args.model})")

    elif args.action == "config":
        if args.daily or args.weekly or args.heartbeat_limit:
            update_config(args.daily, args.weekly, args.heartbeat_limit)
            print("配置已更新")
        config = _load_config()
        print(json.dumps(config, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
