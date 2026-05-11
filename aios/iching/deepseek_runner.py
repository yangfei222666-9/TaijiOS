"""Run a 64-hexagram I Ching batch through DeepSeek or dry-run mode."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

from aios.gui_agent.redaction import contains_secret, redact_secrets


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "runs" / "iching"
LEGACY_OUTPUT_DIR = RUNS_ROOT / "deepseek_iching_64_20260511"
LATEST_OUTPUT_POINTER = RUNS_ROOT / "latest_output_dir.txt"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_ENDPOINT = "https://api.deepseek.com/v1/chat/completions"
HEXAGRAM_CACHE_DIRNAME = "hexagrams"
DEEPSEEK_PRICING_SOURCE = "https://api-docs.deepseek.com/quick_start/pricing"
DEFAULT_DEEPSEEK_PRICES_USD_PER_1M = {
    "input_cache_hit": 0.0028,
    "input_cache_miss": 0.14,
    "output": 0.28,
}

YIJING_HEXAGRAMS: tuple[dict, ...] = (
    {"number": 1, "name": "乾", "symbol": "䷀", "theme": "创始、刚健、主动"},
    {"number": 2, "name": "坤", "symbol": "䷁", "theme": "承载、顺势、厚德"},
    {"number": 3, "name": "屯", "symbol": "䷂", "theme": "初创、艰难、扎根"},
    {"number": 4, "name": "蒙", "symbol": "䷃", "theme": "启蒙、学习、求教"},
    {"number": 5, "name": "需", "symbol": "䷄", "theme": "等待、蓄势、耐心"},
    {"number": 6, "name": "讼", "symbol": "䷅", "theme": "争议、边界、止争"},
    {"number": 7, "name": "师", "symbol": "䷆", "theme": "组织、纪律、动员"},
    {"number": 8, "name": "比", "symbol": "䷇", "theme": "亲比、协作、归属"},
    {"number": 9, "name": "小畜", "symbol": "䷈", "theme": "小蓄、约束、渐积"},
    {"number": 10, "name": "履", "symbol": "䷉", "theme": "践行、礼法、谨慎"},
    {"number": 11, "name": "泰", "symbol": "䷊", "theme": "通泰、平衡、上下相交"},
    {"number": 12, "name": "否", "symbol": "䷋", "theme": "闭塞、隔绝、保守"},
    {"number": 13, "name": "同人", "symbol": "䷌", "theme": "同道、开放、共识"},
    {"number": 14, "name": "大有", "symbol": "䷍", "theme": "丰盛、持有、明德"},
    {"number": 15, "name": "谦", "symbol": "䷎", "theme": "谦逊、低位、成全"},
    {"number": 16, "name": "豫", "symbol": "䷏", "theme": "预备、和乐、动员"},
    {"number": 17, "name": "随", "symbol": "䷐", "theme": "随顺、适配、跟进"},
    {"number": 18, "name": "蛊", "symbol": "䷑", "theme": "整治、积弊、修复"},
    {"number": 19, "name": "临", "symbol": "䷒", "theme": "临近、监督、成长"},
    {"number": 20, "name": "观", "symbol": "䷓", "theme": "观察、示范、审视"},
    {"number": 21, "name": "噬嗑", "symbol": "䷔", "theme": "咬合、执法、破障"},
    {"number": 22, "name": "贲", "symbol": "䷕", "theme": "文饰、秩序、外观"},
    {"number": 23, "name": "剥", "symbol": "䷖", "theme": "剥落、削弱、守静"},
    {"number": 24, "name": "复", "symbol": "䷗", "theme": "返回、复原、新生"},
    {"number": 25, "name": "无妄", "symbol": "䷘", "theme": "无妄、真实、避妄动"},
    {"number": 26, "name": "大畜", "symbol": "䷙", "theme": "大蓄、积累、止而养"},
    {"number": 27, "name": "颐", "symbol": "䷚", "theme": "养正、供养、言食"},
    {"number": 28, "name": "大过", "symbol": "䷛", "theme": "过载、承压、非常之举"},
    {"number": 29, "name": "坎", "symbol": "䷜", "theme": "险陷、重复、守信"},
    {"number": 30, "name": "离", "symbol": "䷝", "theme": "附丽、光明、辨识"},
    {"number": 31, "name": "咸", "symbol": "䷞", "theme": "感应、互感、关系"},
    {"number": 32, "name": "恒", "symbol": "䷟", "theme": "持久、常道、稳定"},
    {"number": 33, "name": "遁", "symbol": "䷠", "theme": "退避、保存、远害"},
    {"number": 34, "name": "大壮", "symbol": "䷡", "theme": "强盛、正大、克制"},
    {"number": 35, "name": "晋", "symbol": "䷢", "theme": "晋升、明进、显现"},
    {"number": 36, "name": "明夷", "symbol": "䷣", "theme": "光受伤、藏明、避害"},
    {"number": 37, "name": "家人", "symbol": "䷤", "theme": "家道、角色、内外秩序"},
    {"number": 38, "name": "睽", "symbol": "䷥", "theme": "分歧、异中求同、小事可成"},
    {"number": 39, "name": "蹇", "symbol": "䷦", "theme": "阻难、绕行、求助"},
    {"number": 40, "name": "解", "symbol": "䷧", "theme": "解除、释放、舒缓"},
    {"number": 41, "name": "损", "symbol": "䷨", "theme": "减损、节制、以少成多"},
    {"number": 42, "name": "益", "symbol": "䷩", "theme": "增益、助长、利他"},
    {"number": 43, "name": "夬", "symbol": "䷪", "theme": "决断、宣告、去邪"},
    {"number": 44, "name": "姤", "symbol": "䷫", "theme": "相遇、诱发、慎始"},
    {"number": 45, "name": "萃", "symbol": "䷬", "theme": "聚集、会合、共同体"},
    {"number": 46, "name": "升", "symbol": "䷭", "theme": "上升、渐进、积步"},
    {"number": 47, "name": "困", "symbol": "䷮", "theme": "困顿、受限、守志"},
    {"number": 48, "name": "井", "symbol": "䷯", "theme": "井养、公共资源、更新"},
    {"number": 49, "name": "革", "symbol": "䷰", "theme": "变革、去旧、正名"},
    {"number": 50, "name": "鼎", "symbol": "䷱", "theme": "承载、更新、制度化"},
    {"number": 51, "name": "震", "symbol": "䷲", "theme": "震动、警醒、行动"},
    {"number": 52, "name": "艮", "symbol": "䷳", "theme": "止息、边界、定力"},
    {"number": 53, "name": "渐", "symbol": "䷴", "theme": "渐进、秩序、长期主义"},
    {"number": 54, "name": "归妹", "symbol": "䷵", "theme": "归属、位置、非正配"},
    {"number": 55, "name": "丰", "symbol": "䷶", "theme": "丰盛、盛极、照察"},
    {"number": 56, "name": "旅", "symbol": "䷷", "theme": "旅居、临时、守礼"},
    {"number": 57, "name": "巽", "symbol": "䷸", "theme": "入、顺入、细致影响"},
    {"number": 58, "name": "兑", "symbol": "䷹", "theme": "悦、沟通、开放"},
    {"number": 59, "name": "涣", "symbol": "䷺", "theme": "涣散、分解、重新凝聚"},
    {"number": 60, "name": "节", "symbol": "䷻", "theme": "节制、制度、边界"},
    {"number": 61, "name": "中孚", "symbol": "䷼", "theme": "诚信、内在可信、感通"},
    {"number": 62, "name": "小过", "symbol": "䷽", "theme": "小过、谨小、低飞"},
    {"number": 63, "name": "既济", "symbol": "䷾", "theme": "已成、守成、防乱"},
    {"number": 64, "name": "未济", "symbol": "䷿", "theme": "未成、过渡、继续调整"},
)


class IchingClient(Protocol):
    def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        ...


@dataclass
class IchingRunResult:
    """Artifacts and summary for one 64-hexagram run."""

    ok: bool
    output_dir: Path
    summary_path: Path
    event_flow_path: Path
    report_path: Path
    summary: dict


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked_files": self.checked_files,
        }


class DeepSeekChatClient:
    """Small OpenAI-compatible DeepSeek client."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout_s: int = 120,
    ):
        raw_api_key = api_key if api_key is not None else os.getenv("DEEPSEEK_API_KEY", "")
        self.api_key = raw_api_key.strip()
        self.endpoint = endpoint or os.getenv("DEEPSEEK_CHAT_ENDPOINT", DEFAULT_ENDPOINT)
        self.timeout_s = timeout_s

    def complete(
        self,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> dict:
        if not self.api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is not configured")
        if not self.api_key.isascii():
            raise RuntimeError("DEEPSEEK_API_KEY must be ASCII")

        import requests

        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=self.timeout_s,
        )
        if response.status_code != 200:
            raise RuntimeError(f"DeepSeek API returned {response.status_code}")
        return response.json()


class EventRecorder:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.events: list[dict] = []

    def emit(self, event_type: str, payload: dict | None = None) -> None:
        event = {
            "id": str(uuid.uuid4()),
            "ts": int(time.time() * 1000),
            "type": event_type,
            "source": "deepseek_iching_64",
            "payload": redact_secrets(payload or {}),
        }
        self.events.append(event)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")


def default_output_dir() -> Path:
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    nonce = uuid.uuid4().hex[:8]
    return RUNS_ROOT / f"deepseek_iching_64_{stamp}_{os.getpid()}_{nonce}"


def write_latest_output_dir(output_dir: str | Path) -> None:
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    LATEST_OUTPUT_POINTER.write_text(str(Path(output_dir).resolve()), encoding="utf-8")


def resolve_latest_output_dir() -> Path:
    if LATEST_OUTPUT_POINTER.exists():
        raw = LATEST_OUTPUT_POINTER.read_text(encoding="utf-8").strip()
        if raw:
            return Path(raw)
    return LEGACY_OUTPUT_DIR


class DeepSeekIchingRunner:
    """Run the 64 I Ching hexagrams through DeepSeek with audit artifacts."""

    def __init__(
        self,
        *,
        output_dir: str | Path | None = None,
        model: str = DEFAULT_MODEL,
        live: bool = False,
        temperature: float = 0.2,
        max_tokens: int = 700,
        client: IchingClient | None = None,
        hexagrams: Sequence[dict] = YIJING_HEXAGRAMS,
        resume: bool = True,
        write_cache: bool = True,
        fresh: bool = False,
        retry_attempts: int = 2,
        retry_delay_s: float = 1.0,
    ):
        self.output_dir = Path(output_dir) if output_dir is not None else default_output_dir()
        self.model = model
        self.live = live
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.client = client or DeepSeekChatClient()
        self.hexagrams = tuple(hexagrams)
        self.resume = resume
        self.write_cache = write_cache
        self.fresh = fresh
        self.retry_attempts = retry_attempts
        self.retry_delay_s = retry_delay_s

    def run(self) -> IchingRunResult:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        summary_path = self.output_dir / "summary.json"
        event_flow_path = self.output_dir / "event_flow.jsonl"
        report_path = self.output_dir / "iching_64_report.md"
        cache_dir = self.output_dir / HEXAGRAM_CACHE_DIRNAME
        for path in (summary_path, event_flow_path, report_path):
            if path.exists():
                path.unlink()
        event_flow_path.write_text("", encoding="utf-8")
        cache_dir.mkdir(parents=True, exist_ok=True)
        if self.fresh:
            for path in cache_dir.glob("*.json"):
                path.unlink()

        recorder = EventRecorder(event_flow_path)
        recorder.emit("iching_run.started", {
            "model": self.model,
            "live": self.live,
            "hexagram_count": len(self.hexagrams),
            "resume": self.resume,
            "write_cache": self.write_cache,
            "fresh": self.fresh,
            "retry_attempts": self.retry_attempts,
            "cache_dir": str(cache_dir),
        })

        results: list[dict] = []
        errors: list[dict] = []
        for hexagram in self.hexagrams:
            result = self._run_hexagram(hexagram, recorder, cache_dir)
            results.append(result)
            if result["status"] != "completed":
                errors.append({
                    "number": hexagram["number"],
                    "name": hexagram["name"],
                    "error": result.get("error", "unknown error"),
                })

        report_text = self._write_report(report_path, results)
        usage_totals = _usage_totals(results)
        artifacts = {
            "summary": str(summary_path),
            "event_flow": str(event_flow_path),
            "report": str(report_path),
        }
        if self.write_cache:
            artifacts["hexagram_cache_dir"] = str(cache_dir)

        summary = {
            "ok": not errors,
            "verdict": "deepseek_iching_64_candidate",
            "learning_only": True,
            "live": self.live,
            "model": self.model,
            "resume": self.resume,
            "write_cache": self.write_cache,
            "fresh": self.fresh,
            "hexagram_count": len(results),
            "completed_count": sum(1 for item in results if item["status"] == "completed"),
            "error_count": len(errors),
            "api_call_count": sum(int(item.get("api_call_count") or 0) for item in results),
            "cache_hit_count": sum(1 for item in results if item.get("cache_hit") is True),
            "retry_count": sum(int(item.get("retry_count") or 0) for item in results),
            "usage": usage_totals,
            "pricing": _pricing_metadata(),
            "divination_claim": False,
            "financial_advice": False,
            "medical_legal_advice": False,
            "secret_detected": contains_secret({
                "events": recorder.events,
                "results": results,
                "report": report_text,
            }),
            "artifacts": artifacts,
            "errors": errors,
            "results": results,
        }
        summary = redact_secrets(summary)
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        recorder.emit("iching_run.completed", {
            "ok": summary["ok"],
            "completed_count": summary["completed_count"],
            "error_count": summary["error_count"],
            "summary": str(summary_path),
            "secret_detected": summary["secret_detected"],
        })
        write_latest_output_dir(self.output_dir)
        return IchingRunResult(
            ok=summary["ok"],
            output_dir=self.output_dir,
            summary_path=summary_path,
            event_flow_path=event_flow_path,
            report_path=report_path,
            summary=summary,
        )

    def _run_hexagram(
        self,
        hexagram: dict,
        recorder: EventRecorder,
        cache_dir: Path,
    ) -> dict:
        number = hexagram["number"]
        name = hexagram["name"]
        prompt = self._build_prompt(hexagram)
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        cache_key = self._cache_key(hexagram, prompt_hash)
        cache_path = self._cache_path(cache_dir, hexagram)
        recorder.emit("hexagram.started", {
            "number": number,
            "name": name,
            "symbol": hexagram["symbol"],
            "live": self.live,
            "cache_key": cache_key,
        })

        cached = self._load_cached_result(cache_path, cache_key)
        if cached is not None:
            recorder.emit("hexagram.cache_hit", {
                "number": number,
                "name": name,
                "cache_path": str(cache_path),
                "cache_key": cache_key,
            })
            recorder.emit("hexagram.completed", {
                "number": number,
                "name": name,
                "status": "completed",
                "provider": cached.get("provider"),
                "cache_hit": True,
            })
            return cached

        if not self.live:
            interpretation = self._dry_run_interpretation(hexagram)
            result = {
                "number": number,
                "name": name,
                "symbol": hexagram["symbol"],
                "theme": hexagram["theme"],
                "status": "completed",
                "provider": "dry_run",
                "model": self.model,
                "tokens_used": 0,
                "usage": _empty_usage(),
                "estimated_cost_usd": 0.0,
                "api_call_count": 0,
                "retry_count": 0,
                "cache_hit": False,
                "cache_key": cache_key,
                "prompt_sha256": prompt_hash,
                "interpretation": interpretation,
            }
            self._write_cached_result(cache_path, result)
            recorder.emit("hexagram.completed", {
                "number": number,
                "name": name,
                "status": "completed",
                "provider": "dry_run",
            })
            return result

        system = (
            "你是严谨的《易经》研究助手。只输出 JSON，不要输出 Markdown。"
            "不要给出占卜确定性结论，不要给投资、医疗、法律建议。"
            "把卦义转成现代决策反思，语气克制。"
        )
        recorder.emit("deepseek.requested", {
            "number": number,
            "name": name,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "prompt_sha256": prompt_hash,
            "retry_attempts": self.retry_attempts,
        })

        try:
            raw, attempt_count = self._complete_with_retries(
                hexagram=hexagram,
                system=system,
                prompt=prompt,
                recorder=recorder,
            )
            content = (
                raw.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
            usage = raw.get("usage") or {}
            usage_stats = _usage_stats(usage)
            interpretation = _parse_json_object(content)
            result = {
                "number": number,
                "name": name,
                "symbol": hexagram["symbol"],
                "theme": hexagram["theme"],
                "status": "completed",
                "provider": "deepseek",
                "model": raw.get("model", self.model),
                "tokens_used": usage_stats["total_tokens"],
                "usage": usage_stats,
                "estimated_cost_usd": _estimate_cost_usd(usage_stats),
                "api_call_count": attempt_count,
                "retry_count": max(0, attempt_count - 1),
                "cache_hit": False,
                "cache_key": cache_key,
                "prompt_sha256": prompt_hash,
                "interpretation": interpretation,
            }
            self._write_cached_result(cache_path, result)
            recorder.emit("deepseek.completed", {
                "number": number,
                "name": name,
                "status": "completed",
                "tokens_used": result["tokens_used"],
                "estimated_cost_usd": result["estimated_cost_usd"],
                "attempt_count": attempt_count,
            })
            recorder.emit("hexagram.completed", {
                "number": number,
                "name": name,
                "status": "completed",
                "provider": "deepseek",
            })
            return redact_secrets(result)
        except Exception as exc:
            error = str(exc)
            recorder.emit("deepseek.failed", {
                "number": number,
                "name": name,
                "error": error,
            })
            return {
                "number": number,
                "name": name,
                "symbol": hexagram["symbol"],
                "theme": hexagram["theme"],
                "status": "failed",
                "provider": "deepseek",
                "model": self.model,
                "tokens_used": 0,
                "usage": _empty_usage(),
                "estimated_cost_usd": 0.0,
                "api_call_count": 0,
                "retry_count": self.retry_attempts,
                "cache_hit": False,
                "cache_key": cache_key,
                "prompt_sha256": prompt_hash,
                "error": redact_secrets(error),
            }

    def _complete_with_retries(
        self,
        *,
        hexagram: dict,
        system: str,
        prompt: str,
        recorder: EventRecorder,
    ) -> tuple[dict, int]:
        last_error: Exception | None = None
        max_attempts = max(1, self.retry_attempts + 1)
        for attempt in range(1, max_attempts + 1):
            try:
                return (
                    self.client.complete(
                        model=self.model,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        temperature=self.temperature,
                        max_tokens=self.max_tokens,
                    ),
                    attempt,
                )
            except Exception as exc:
                last_error = exc
                recorder.emit("deepseek.retry", {
                    "number": hexagram["number"],
                    "name": hexagram["name"],
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "error": str(exc),
                })
                if attempt < max_attempts and self.retry_delay_s > 0:
                    time.sleep(self.retry_delay_s * attempt)
        assert last_error is not None
        raise last_error

    def _cache_key(self, hexagram: dict, prompt_hash: str) -> str:
        payload = {
            "schema_version": 1,
            "number": hexagram["number"],
            "name": hexagram["name"],
            "theme": hexagram["theme"],
            "model": self.model,
            "live": self.live,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "prompt_sha256": prompt_hash,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    @staticmethod
    def _cache_path(cache_dir: Path, hexagram: dict) -> Path:
        return cache_dir / f"{int(hexagram['number']):02d}_{hexagram['name']}.json"

    def _load_cached_result(self, path: Path, cache_key: str) -> dict | None:
        if not self.resume or not path.exists():
            return None
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if cached.get("cache_key") != cache_key:
            return None
        if cached.get("status") != "completed":
            return None
        cached["cache_hit"] = True
        cached["api_call_count"] = 0
        cached["retry_count"] = 0
        cached["cached_estimated_cost_usd"] = float(cached.get("estimated_cost_usd") or 0.0)
        cached["estimated_cost_usd"] = 0.0
        return redact_secrets(cached)

    def _write_cached_result(self, path: Path, result: dict) -> None:
        if not self.write_cache:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(redact_secrets(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_prompt(self, hexagram: dict) -> str:
        return (
            f"请解读《易经》第{hexagram['number']}卦：{hexagram['name']} "
            f"{hexagram['symbol']}。主题提示：{hexagram['theme']}。\n"
            "输出严格 JSON 对象，字段为：\n"
            "- core_meaning: 一句话核心卦义\n"
            "- modern_reading: 面向个人/组织决策的现代解释，120字以内\n"
            "- risks: 三条风险，每条不超过20字\n"
            "- actions: 三条行动建议，每条不超过20字\n"
            "- taijios_agent_note: 对 AI agent/系统治理的启发，80字以内\n"
            "- disclaimer: 固定写“不作为占卜、投资、医疗或法律建议”\n"
        )

    def _dry_run_interpretation(self, hexagram: dict) -> dict:
        return {
            "core_meaning": f"{hexagram['name']}强调{hexagram['theme']}。",
            "modern_reading": (
                f"在现代任务里，{hexagram['name']}可作为"
                f"“{hexagram['theme']}”的反思框架；先看处境，再定节奏。"
            ),
            "risks": ["误判时机", "过度用力", "忽略边界"],
            "actions": ["先审条件", "小步验证", "保留回退"],
            "taijios_agent_note": "Agent 决策应先记录上下文、约束和可回放证据，再进入执行。",
            "disclaimer": "不作为占卜、投资、医疗或法律建议",
        }

    def _write_report(self, report_path: Path, results: list[dict]) -> str:
        usage_totals = _usage_totals(results)
        lines = [
            "# DeepSeek I Ching 64 Hexagram Run",
            "",
            f"Mode: {'live' if self.live else 'dry-run'}",
            f"Model: {self.model}",
            f"Cache hits: {sum(1 for item in results if item.get('cache_hit') is True)}",
            f"API calls: {sum(int(item.get('api_call_count') or 0) for item in results)}",
            f"Total tokens: {usage_totals['total_tokens']}",
            f"Estimated cost USD: {usage_totals['estimated_cost_usd']}",
            "",
            "This report is for learning and reflective analysis only.",
            "It is not divination, investment, medical, or legal advice.",
            "",
        ]
        for item in results:
            interpretation = item.get("interpretation") or {}
            lines.extend([
                f"## {item['number']:02d}. {item['name']} {item['symbol']}",
                "",
                f"- Status: {item['status']}",
                f"- Theme: {item['theme']}",
                f"- Core: {interpretation.get('core_meaning', '')}",
                f"- Reading: {interpretation.get('modern_reading', '')}",
                f"- Agent note: {interpretation.get('taijios_agent_note', '')}",
                "",
            ])
        report = redact_secrets("\n".join(lines))
        report_path.write_text(report, encoding="utf-8")
        return report


def validate_iching_run(output_dir: str | Path) -> ValidationResult:
    output_dir = Path(output_dir)
    summary_path = output_dir / "summary.json"
    event_flow_path = output_dir / "event_flow.jsonl"
    report_path = output_dir / "iching_64_report.md"
    checked_files = [str(summary_path), str(event_flow_path), str(report_path)]
    errors: list[str] = []
    warnings: list[str] = []

    for path in (summary_path, event_flow_path, report_path):
        if not path.exists():
            errors.append(f"missing artifact: {path.name}")

    summary = _load_json(summary_path, errors, "summary")
    events = _load_jsonl(event_flow_path, errors, "event_flow")
    report = report_path.read_text(encoding="utf-8") if report_path.exists() else ""
    cache_dir = None

    if summary:
        artifacts = summary.get("artifacts") or {}
        if artifacts.get("hexagram_cache_dir"):
            cache_dir = Path(artifacts["hexagram_cache_dir"])
            checked_files.append(str(cache_dir))
            if not cache_dir.exists():
                errors.append("missing artifact: hexagram_cache_dir")
        if summary.get("verdict") != "deepseek_iching_64_candidate":
            errors.append("summary.verdict is not deepseek_iching_64_candidate")
        if summary.get("learning_only") is not True:
            errors.append("summary.learning_only expected true")
        if summary.get("hexagram_count") != 64:
            errors.append(f"summary.hexagram_count expected 64, got {summary.get('hexagram_count')!r}")
        if summary.get("completed_count") != 64:
            errors.append(
                "summary.completed_count expected 64, "
                f"got {summary.get('completed_count')!r}"
            )
        usage = summary.get("usage") or {}
        if usage.get("total_tokens") is None:
            errors.append("summary.usage.total_tokens is missing")
        if summary.get("cache_hit_count", 0) < 0:
            errors.append("summary.cache_hit_count must not be negative")
        if summary.get("api_call_count", 0) < 0:
            errors.append("summary.api_call_count must not be negative")
        pricing = summary.get("pricing") or {}
        if pricing.get("currency") != "USD":
            errors.append("summary.pricing.currency expected USD")
        for flag in ("divination_claim", "financial_advice", "medical_legal_advice", "secret_detected"):
            if summary.get(flag) is not False:
                errors.append(f"summary.{flag} expected false")
        results = summary.get("results") or []
        if len(results) != 64:
            errors.append(f"summary.results expected 64 entries, got {len(results)}")
        numbers = [item.get("number") for item in results]
        if numbers != list(range(1, 65)):
            errors.append("summary.results are not ordered 1..64")
        for item in results:
            if item.get("status") != "completed":
                errors.append(f"hexagram {item.get('number')} did not complete")
            disclaimer = (item.get("interpretation") or {}).get("disclaimer", "")
            if "不作为占卜" not in disclaimer:
                errors.append(f"hexagram {item.get('number')} missing disclaimer")
        if cache_dir and cache_dir.exists():
            cache_files = sorted(cache_dir.glob("*.json"))
            if len(cache_files) != 64:
                errors.append(f"hexagram cache expected 64 files, got {len(cache_files)}")

    event_types = [event.get("type") for event in events]
    if event_types.count("hexagram.completed") != 64:
        errors.append("event_flow does not contain 64 hexagram.completed events")
    if event_types.count("iching_run.started") != 1:
        errors.append("event_flow must contain exactly one iching_run.started event")
    if event_types.count("iching_run.completed") != 1:
        errors.append("event_flow must contain exactly one iching_run.completed event")
    if summary:
        summary_live = summary.get("live")
        live_mismatches = [
            event
            for event in events
            if isinstance(event.get("payload"), dict)
            and "live" in event["payload"]
            and event["payload"]["live"] is not summary_live
        ]
        if live_mismatches:
            errors.append("event_flow contains events with live flag inconsistent with summary.live")
        if summary_live is False and any(
            str(event_type).startswith("deepseek.") for event_type in event_types
        ):
            errors.append("dry-run event_flow contains live DeepSeek request events")

    if "not divination" not in report:
        warnings.append("report does not include English learning disclaimer")
    if contains_secret({"summary": summary, "events": events, "report": report}):
        errors.append("secret-like value found in I Ching artifacts")

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        checked_files=checked_files,
    )


def _empty_usage() -> dict:
    return {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
        "estimated_cost_usd": 0.0,
    }


def _usage_stats(usage: dict) -> dict:
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    cache_hit_tokens = int(
        usage.get("prompt_cache_hit_tokens")
        or usage.get("cache_hit_tokens")
        or 0
    )
    cache_miss_tokens = int(
        usage.get("prompt_cache_miss_tokens")
        or usage.get("cache_miss_tokens")
        or max(prompt_tokens - cache_hit_tokens, 0)
    )
    stats = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": cache_hit_tokens,
        "prompt_cache_miss_tokens": cache_miss_tokens,
    }
    stats["estimated_cost_usd"] = _estimate_cost_usd(stats)
    return stats


def _usage_totals(results: list[dict]) -> dict:
    totals = _empty_usage()
    for result in results:
        usage = result.get("usage") or {}
        for key in (
            "prompt_tokens",
            "completion_tokens",
            "total_tokens",
            "prompt_cache_hit_tokens",
            "prompt_cache_miss_tokens",
        ):
            totals[key] += int(usage.get(key) or 0)
        if "estimated_cost_usd" in result:
            totals["estimated_cost_usd"] += float(result.get("estimated_cost_usd") or 0.0)
        else:
            totals["estimated_cost_usd"] += float(usage.get("estimated_cost_usd") or 0.0)
    totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 8)
    return totals


def _estimate_cost_usd(usage: dict) -> float:
    prices = _price_table()
    cost = (
        int(usage.get("prompt_cache_hit_tokens") or 0)
        * prices["input_cache_hit"]
        / 1_000_000
        + int(usage.get("prompt_cache_miss_tokens") or 0)
        * prices["input_cache_miss"]
        / 1_000_000
        + int(usage.get("completion_tokens") or 0)
        * prices["output"]
        / 1_000_000
    )
    return round(cost, 8)


def _price_table() -> dict:
    prices = dict(DEFAULT_DEEPSEEK_PRICES_USD_PER_1M)
    env_map = {
        "input_cache_hit": "DEEPSEEK_INPUT_CACHE_HIT_USD_PER_1M",
        "input_cache_miss": "DEEPSEEK_INPUT_CACHE_MISS_USD_PER_1M",
        "output": "DEEPSEEK_OUTPUT_USD_PER_1M",
    }
    for key, env_name in env_map.items():
        value = os.getenv(env_name, "").strip()
        if value:
            prices[key] = float(value)
    return prices


def _pricing_metadata() -> dict:
    return {
        "currency": "USD",
        "unit": "per_1m_tokens",
        "source": DEEPSEEK_PRICING_SOURCE,
        "note": "Estimated only; DeepSeek may change pricing. Override with DEEPSEEK_*_USD_PER_1M env vars.",
        "prices": _price_table(),
    }


def _load_json(path: Path, errors: list[str], label: str) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{label} is not valid JSON: {exc}")
        return {}


def _load_jsonl(path: Path, errors: list[str], label: str) -> list[dict]:
    if not path.exists():
        return []
    loaded: list[dict] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            loaded.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append(f"{label} line {line_number} is not valid JSON: {exc}")
    return loaded


def _parse_json_object(content: str) -> dict:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.lower().startswith("json"):
            stripped = stripped[4:].strip()
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("DeepSeek response did not contain a JSON object")
        parsed = json.loads(stripped[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("DeepSeek response JSON is not an object")
    return redact_secrets(parsed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run 64 I Ching hexagrams through DeepSeek.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Artifact directory. Defaults to a unique "
            "runs/iching/deepseek_iching_64_<timestamp>_<microseconds>_<pid>_<nonce> "
            "directory."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=700)
    parser.add_argument("--retry-attempts", type=int, default=2)
    parser.add_argument("--retry-delay-s", type=float, default=1.0)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually call DeepSeek. Requires DEEPSEEK_API_KEY.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Clear existing per-hexagram cache before running.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable cache reads and writes for this run.",
    )
    parser.add_argument(
        "--print-full",
        action="store_true",
        help="Print full 64-result JSON to stdout. Files are always written.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    if args.live and not os.getenv("DEEPSEEK_API_KEY"):
        print("DEEPSEEK_API_KEY is not configured; rerun without --live for dry-run.")
        return 2
    result = DeepSeekIchingRunner(
        output_dir=args.output_dir,
        model=args.model,
        live=args.live,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        resume=not args.no_cache,
        write_cache=not args.no_cache,
        fresh=args.fresh,
        retry_attempts=args.retry_attempts,
        retry_delay_s=args.retry_delay_s,
    ).run()
    output = result.summary if args.print_full else _compact_summary(result.summary)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def _compact_summary(summary: dict) -> dict:
    return {
        key: value
        for key, value in summary.items()
        if key != "results"
    }


if __name__ == "__main__":
    raise SystemExit(main())
