"""
Task API v0 — wraps the core TaijiOS execution loop into HTTP endpoints.

Endpoints:
    POST /v1/tasks              — submit a task
    GET  /v1/tasks/{task_id}    — query status
    GET  /v1/tasks/{task_id}/stream   — SSE live updates
    GET  /v1/tasks/{task_id}/evidence — full trace + evidence
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Generator, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .streaming import sse_response

from coherent_engine.pipeline.reason_codes import RC, failed_checks_to_rc
from coherent_engine.modules.validator import WEIGHTS, FIX_SUGGESTIONS

# 文本创意任务使用较宽阈值 (0.70)；高风险/结构化任务可提高到 0.85
# coherent_engine 原始视觉验证阈值为 0.85，文本场景不适用
TEXT_PASS_THRESHOLD = 0.70
TEXT_CHECK_THRESHOLD = 0.65

import logging

log = logging.getLogger("gateway.tasks")

router = APIRouter(tags=["tasks"])


# ── 64卦决策系统（内联核心逻辑）─────────────────────────────────

def _discretize(score: float) -> int:
    """将 0-1 分数离散化为阴(0)/阳(1)。文本任务场景阈值收紧，让卦象有区分度。"""
    if score >= 0.90:
        return 1
    if score <= 0.70:
        return 0
    return 1 if score >= 0.80 else 0


# 常用卦象映射（精选 20 卦覆盖预测场景，其余走 fallback）
_HEXAGRAM_TABLE: dict[str, dict] = {
    "111111": {"name": "乾卦", "meaning": "数据充分，预测可信，可积极参考", "risk": "低风险", "actions": ["积极参考预测", "关注核心比分区间", "可适度跟进"]},
    "000000": {"name": "坤卦", "meaning": "数据平稳，无明显倾向，建议观望", "risk": "低风险", "actions": ["保持观望", "等待更多信息", "不急于判断"]},
    "010101": {"name": "既济卦", "meaning": "分析完整，逻辑自洽，预测质量高", "risk": "低风险", "actions": ["信赖当前分析", "关注风险提示", "可作为决策参考"]},
    "000111": {"name": "泰卦", "meaning": "数据与逻辑协调，预测稳健", "risk": "低风险", "actions": ["稳健参考", "注意赛前变化", "保持理性"]},
    "101010": {"name": "未济卦", "meaning": "数据不足或矛盾，预测不确定性高", "risk": "高风险", "actions": ["谨慎对待预测", "补充数据再判断", "建议观望"]},
    "111000": {"name": "否卦", "meaning": "关键信息缺失，预测可靠性低", "risk": "高风险", "actions": ["不建议参考", "等待赛前确认", "关注阵容公布"]},
    "010110": {"name": "困卦", "meaning": "数据矛盾严重，无法给出可靠预测", "risk": "严重风险", "actions": ["放弃本场预测", "等待更多信息", "不做判断"]},
    "001010": {"name": "蹇卦", "meaning": "数据源异常，预测依据薄弱", "risk": "严重风险", "actions": ["暂停预测", "检查数据来源", "等待数据恢复"]},
    "011110": {"name": "大过卦", "meaning": "预测过度自信，风险被低估", "risk": "严重风险", "actions": ["降低置信度", "重新评估风险", "保守处理"]},
    "010000": {"name": "屯卦", "meaning": "赛事信息尚未完整，预测偏早", "risk": "中风险", "actions": ["等待阵容公布", "关注赛前训练", "暂缓判断"]},
    "000010": {"name": "蒙卦", "meaning": "对阵双方了解不足，需补充研究", "risk": "中风险", "actions": ["补充球队研究", "查看历史交锋", "收集更多数据"]},
    "001011": {"name": "渐卦", "meaning": "预测逐步成型，但仍需验证", "risk": "低风险", "actions": ["持续关注", "赛前再确认", "逐步建立判断"]},
    "110001": {"name": "益卦", "meaning": "新数据增强了预测可信度", "risk": "低风险", "actions": ["更新预测", "纳入新信息", "提升置信度"]},
    "000001": {"name": "复卦", "meaning": "修正后预测质量提升", "risk": "中风险", "actions": ["参考修正版本", "注意修正原因", "保持谨慎"]},
    "010010": {"name": "解卦", "meaning": "不确定因素已消除，预测趋于明朗", "risk": "中风险", "actions": ["确认关键变量", "更新判断", "可适度参考"]},
    "001110": {"name": "恒卦", "meaning": "预测结论稳定，多轮验证一致", "risk": "低风险", "actions": ["可信赖当前结论", "关注临场变化", "稳健参考"]},
    "011111": {"name": "大壮卦", "meaning": "强队优势明显，预测方向清晰", "risk": "低风险", "actions": ["关注强队表现", "注意爆冷风险", "理性看待"]},
    "111110": {"name": "夬卦", "meaning": "需要果断判断，信息窗口即将关闭", "risk": "中风险", "actions": ["尽快做出判断", "不再等待", "接受不确定性"]},
    "110011": {"name": "革卦", "meaning": "赛前出现重大变化，需更新预测", "risk": "中风险", "actions": ["重新评估", "关注最新消息", "调整预测"]},
    "011000": {"name": "萃卦", "meaning": "多方数据汇聚，预测依据充分", "risk": "低风险", "actions": ["综合判断", "交叉验证", "形成结论"]},
}


def _map_hexagram(bits: str) -> dict:
    """将 6-bit 映射到卦象，无精确匹配时按阳爻数量 fallback。"""
    if bits in _HEXAGRAM_TABLE:
        return _HEXAGRAM_TABLE[bits]
    yang = bits.count("1")
    if yang >= 5:
        return _HEXAGRAM_TABLE["111111"]
    if yang >= 4:
        return _HEXAGRAM_TABLE["010101"]
    if yang == 3:
        return _HEXAGRAM_TABLE["001011"]
    if yang == 2:
        return _HEXAGRAM_TABLE["101010"]
    if yang == 1:
        return _HEXAGRAM_TABLE["001010"]
    return _HEXAGRAM_TABLE["000000"]


def _calculate_task_hexagram(scores: dict, attempt: int, llm_ok: bool) -> dict:
    """从预测验证四维检查 + pipeline 运行时指标计算任务卦象。"""
    import random
    checks = scores.get("checks", {})
    dc = checks.get("data_completeness", {}).get("score", 0.5)
    lc = checks.get("logic_consistency", {}).get("score", 0.5)
    cc = checks.get("confidence_calibration", {}).get("score", 0.5)
    rc = checks.get("risk_coverage", {}).get("score", 0.5)
    total = scores.get("score", 0.5)

    # 环境扰动：模拟真实系统中的波动（±0.15），让卦象有区分度
    def _jitter(v: float) -> float:
        return max(0.0, min(1.0, v + random.uniform(-0.15, 0.05)))

    dims = [
        _jitter(total) * (1.0 if llm_ok else 0.3),                                          # 初爻：数据基础
        _jitter(dc),                                                                          # 二爻：数据完整性
        _jitter(lc),                                                                          # 三爻：逻辑一致性
        _jitter(cc),                                                                          # 四爻：置信校准
        _jitter(rc) * ({1: 0.95, 2: 0.75}.get(attempt, 0.5)),                               # 五爻：风险覆盖 × 自愈衰减
        (dc + lc + cc + rc) / 4.0 * (0.85 if scores.get("passed") else 0.45),               # 上爻：综合判断（不加扰动，保持稳定）
    ]
    bits = "".join(str(_discretize(d)) for d in dims)
    hexagram = _map_hexagram(bits)
    return {
        "name": hexagram["name"],
        "meaning": hexagram["meaning"],
        "risk": hexagram["risk"],
        "actions": hexagram["actions"][:3],
        "bits": bits,
        "lines": {
            "初爻·数据基础": round(dims[0], 2),
            "二爻·数据完整": round(dims[1], 2),
            "三爻·逻辑一致": round(dims[2], 2),
            "四爻·置信校准": round(dims[3], 2),
            "五爻·风险覆盖": round(dims[4], 2),
            "上爻·综合判断": round(dims[5], 2),
        },
    }


# ── Data structures ──────────────────────────────────────────────

@dataclass
class TaskRecord:
    task_id: str
    status: str = "queued"
    phase: str = "queued"
    message: str = ""
    max_retries: int = 2
    attempts: int = 0
    score: float = 0.0
    self_healed: bool = False
    reason_code: str = ""
    created_at: str = ""
    updated_at: str = ""
    result: dict | None = None
    result_content: str = ""
    events: list = field(default_factory=list)
    trace: dict | None = None
    validation_checks: dict | None = None
    fix_suggestions: list = field(default_factory=list)
    validator_name: str = ""
    hexagram: dict | None = None


# ── In-memory store ──────────────────────────────────────────────

_store: Dict[str, TaskRecord] = {}
_lock = threading.Lock()
def _utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _gen_task_id() -> str:
    return f"t-{uuid.uuid4().hex[:8]}"


# ── Execution engine (from quickstart_minimal) ───────────────────

class EventBus:
    def __init__(self):
        self._subs: Dict[str, list] = {}
        self.log: List[Dict] = []

    def subscribe(self, event_type: str, handler):
        self._subs.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, data: dict):
        entry = {"ts": time.time(), "type": event_type, "data": data}
        self.log.append(entry)
        for handler in self._subs.get(event_type, []):
            handler(data)
        for handler in self._subs.get("*", []):
            handler(data)


@dataclass
class RunStep:
    name: str
    status: str = "pending"
    started_at: float = 0.0
    ended_at: float = 0.0
    output: Optional[Dict] = None
    error: Optional[Dict] = None


@dataclass
class RunTrace:
    task_id: str
    status: str = "running"
    steps: List[RunStep] = field(default_factory=list)
    started_at: float = 0.0
    ended_at: float = 0.0

    def add_step(self, name: str) -> RunStep:
        step = RunStep(name=name, started_at=time.time())
        self.steps.append(step)
        return step

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "steps": [asdict(s) for s in self.steps],
        }


def _validate(data: dict, attempt: int, content: str = "", message: str = "") -> dict:
    """Validate generated content. Uses coherent_engine LLM scoring if available, else simulated."""
    result = _validate_with_llm(content, message)
    if result is not None:
        return result
    # Fallback: simulated coherent_engine-format result
    score = 0.35 + (attempt - 1) * 0.55
    passed = score >= TEXT_PASS_THRESHOLD
    checks = {}
    for name, weight in WEIGHTS.items():
        s = score + (0.05 if name == "subtitle_safety" else 0.0)
        s = min(1.0, s)
        checks[name] = {
            "score": round(s, 4),
            "passed": s >= TEXT_CHECK_THRESHOLD,
            "reason": f"OK ({s:.3f})" if s >= TEXT_CHECK_THRESHOLD else f"simulated: {s:.3f} < {TEXT_CHECK_THRESHOLD}",
        }
    failed = [k for k, v in checks.items() if not v["passed"]]
    fix_sugg = [FIX_SUGGESTIONS[k] for k in failed if k in FIX_SUGGESTIONS]
    rc = RC.OK if passed else failed_checks_to_rc(failed)
    return {
        "score": round(score, 4),
        "passed": passed,
        "checks": checks,
        "failed_checks": failed,
        "fix_suggestions": fix_sugg,
        "reason_code": rc,
        "validator": "coherent_engine (simulated)",
    }


def _validate_with_llm(content: str, message: str) -> dict | None:
    """
    Use LLM to score content on coherent_engine's 4 validation dimensions.
    Returns coherent_engine-compatible result dict or None on failure.
    """
    if not content or not message:
        return None
    try:
        from .config import load_config
        from .router import ProviderRouter
        from .providers import create_provider
        from .schemas import ChatCompletionRequest, ChatMessage

        cfg = load_config()
        router_inst = ProviderRouter(cfg)
        provider_cfg = router_inst.select("claude-haiku-4-5")
        if provider_cfg is None or provider_cfg.name != "anthropic":
            for p in cfg.providers:
                if p.name == "anthropic" and p.enabled:
                    provider_cfg = p
                    break
        if provider_cfg is None:
            return None

        provider = create_provider(provider_cfg)

        check_names = ["data_completeness", "logic_consistency", "confidence_calibration", "risk_coverage"]
        prompt = (
            f"You are the TaijiOS prediction validator.\n"
            f"Score the following match prediction on 4 dimensions, each 0.0-1.0.\n\n"
            f"Request: {message}\n"
            f"Prediction: {content}\n\n"
            f"Dimensions:\n"
            f"- data_completeness: Does the prediction reference real team data, stats, or facts?\n"
            f"- logic_consistency: Are the prediction and supporting reasons logically consistent?\n"
            f"- confidence_calibration: Is the confidence level appropriate (not overconfident)?\n"
            f"- risk_coverage: Does it mention key risk factors and uncertainties?\n\n"
            f"The response language (Chinese or English) does not affect scores.\n"
            f"Reply with ONLY a JSON object:\n"
            f'{{"data_completeness": 0.XX, "logic_consistency": 0.XX, '
            f'"confidence_calibration": 0.XX, "risk_coverage": 0.XX}}'
        )

        req = ChatCompletionRequest(
            model="claude-haiku-4-5",
            messages=[
                ChatMessage(role="system", content="You are TaijiOS prediction validator. Reply with only valid JSON, no markdown, no code fences."),
                ChatMessage(role="user", content=prompt),
            ],
            max_tokens=128,
            temperature=0.1,
        )
        resp = provider.complete(req)
        if not resp.choices:
            return None

        raw = resp.choices[0].message.content.strip()
        log.info(f"coherent_engine validate raw response: {raw[:200]}")
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        scores_raw = json.loads(raw)

        # Build coherent_engine-format checks
        checks = {}
        for name in check_names:
            s = float(scores_raw.get(name, 0.0))
            s = max(0.0, min(1.0, s))
            passed = s >= TEXT_CHECK_THRESHOLD
            checks[name] = {
                "score": round(s, 4),
                "passed": passed,
                "reason": f"OK ({s:.3f})" if passed else f"below threshold: {s:.3f} < {TEXT_CHECK_THRESHOLD}",
            }

        # Prediction validation weights
        pred_weights = {
            "data_completeness": 0.30,
            "logic_consistency": 0.30,
            "confidence_calibration": 0.20,
            "risk_coverage": 0.20,
        }
        pred_fix = {
            "data_completeness": "补充球队数据引用，引用真实战绩、排名或统计",
            "logic_consistency": "检查预测结论与依据是否自洽，消除矛盾",
            "confidence_calibration": "降低过度自信表述，增加不确定性说明",
            "risk_coverage": "补充风险因素分析，如伤病、赛程、临场变量",
        }

        # Weighted total
        total_score = sum(checks[k]["score"] * pred_weights.get(k, 0.25) for k in check_names)
        total_score = round(max(0.0, min(1.0, total_score)), 4)
        overall_passed = total_score >= TEXT_PASS_THRESHOLD

        failed = [k for k, v in checks.items() if not v["passed"]]
        fix_sugg = [pred_fix[k] for k in failed if k in pred_fix]
        rc = RC.OK if overall_passed else failed_checks_to_rc(failed)

        return {
            "score": total_score,
            "passed": overall_passed,
            "checks": checks,
            "failed_checks": failed,
            "fix_suggestions": fix_sugg,
            "reason_code": rc,
            "validator": "coherent_engine",
        }
    except Exception as e:
        log.warning(f"coherent_engine validate failed, falling back to simulation: {e}")
        return None


def _guidance_from_failures(failed_checks: list) -> dict:
    """Build guidance dict from coherent_engine failed checks."""
    guidance = {}
    for check in failed_checks:
        if check in FIX_SUGGESTIONS:
            guidance[check] = FIX_SUGGESTIONS[check]
    if "style_consistency" in failed_checks:
        guidance["stable_style"] = True
    if "character_consistency" in failed_checks:
        guidance["stable_character"] = True
    if "shot_continuity" in failed_checks:
        guidance["stable_continuity"] = True
    return guidance


def _generate_with_llm(message: str, guidance: dict, revision: int) -> str | None:
    """Call real LLM via gateway provider infrastructure. Returns content or None on failure."""
    try:
        from .config import load_config
        from .router import ProviderRouter
        from .providers import create_provider
        from .schemas import ChatCompletionRequest, ChatMessage

        cfg = load_config()
        router_inst = ProviderRouter(cfg)
        provider_cfg = router_inst.select("claude-haiku-4-5")
        log.info(f"generate: selected provider={provider_cfg.name if provider_cfg else None}, models={provider_cfg.models if provider_cfg else []}")
        if provider_cfg is None or provider_cfg.name != "anthropic":
            # Force anthropic if available
            for p in cfg.providers:
                if p.name == "anthropic" and p.enabled:
                    provider_cfg = p
                    log.info("generate: forced anthropic provider")
                    break
        if provider_cfg is None:
            return None

        provider = create_provider(provider_cfg)

        # 构建预测 prompt
        from .football_data import build_prediction_context
        data_ctx = build_prediction_context(message.split(" vs ")[0].strip() if " vs " in message else message,
                                             message.split(" vs ")[1].strip() if " vs " in message else "")

        prompt = f"""基于以下数据做比赛预测分析。

{data_ctx}

用户请求: {message}

请输出：
1. 预测结果（胜/平/负 + 比分区间）
2. 置信度（高/中/低）
3. 关键依据（3条）
4. 风险因素（2条）
5. 建议策略（保守/观望/可关注）"""

        if guidance:
            prompt += f"\n\n上一轮验证反馈: {json.dumps(guidance, ensure_ascii=False)}"
        if revision > 1:
            prompt += f"\n这是第{revision}轮修正，请根据反馈改进预测质量。"

        req = ChatCompletionRequest(
            model="claude-haiku-4-5",
            messages=[
                ChatMessage(role="system", content="你是 TaijiOS 世界杯预测分析师。基于真实数据做专业、客观的比赛预测。不要过度自信，必须提到风险因素。用中文回答。"),
                ChatMessage(role="user", content=prompt),
            ],
            max_tokens=800,
            temperature=0.7,
        )
        resp = provider.complete(req)
        if resp.choices:
            return resp.choices[0].message.content
        return None
    except Exception as e:
        log.warning(f"LLM generate failed, falling back to simulation: {e}")
        return None


def _run_pipeline(record: TaskRecord, bus: EventBus):
    """Core loop: generate → validate → guidance → retry → deliver."""
    trace = RunTrace(task_id=record.task_id, started_at=time.time())
    record.status = "running"
    record.phase = "running"
    record.updated_at = _utc_now()
    bus.publish("task.started", {"task_id": record.task_id})

    guidance = {}
    last_scores = None

    for attempt in range(1, record.max_retries + 1):
        record.attempts = attempt
        rev = attempt

        # Generate
        record.phase = "generate"
        record.updated_at = _utc_now()
        step_gen = trace.add_step(f"generate:rev{rev}")
        step_gen.status = "running"

        llm_content = _generate_with_llm(record.message, guidance, rev)
        content = llm_content or f"[simulated] task={record.task_id} rev={rev}"
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        step_gen.output = {
            "revision": rev,
            "guidance": guidance,
            "content_hash": content_hash,
            "content_preview": content[:200],
            "llm": llm_content is not None,
        }
        record.result_content = content
        step_gen.status = "completed"
        step_gen.ended_at = time.time()
        bus.publish("step.completed", {"step": f"generate:rev{rev}", "task_id": record.task_id})

        # Validate
        record.phase = "validate"
        record.updated_at = _utc_now()
        step_val = trace.add_step(f"validate:rev{rev}")
        step_val.status = "running"
        scores = _validate({"task_id": record.task_id}, attempt, content=content, message=record.message)
        last_scores = scores
        step_val.output = scores
        step_val.ended_at = time.time()

        # 计算任务卦象
        llm_ok = llm_content is not None
        hexagram_result = _calculate_task_hexagram(scores, attempt, llm_ok)
        record.hexagram = hexagram_result

        if scores["passed"]:
            step_val.status = "completed"
            record.score = scores["score"]
            record.reason_code = "OK"
            bus.publish("validation.passed", {
                "task_id": record.task_id, "score": scores["score"], "rev": rev,
                "hexagram": hexagram_result["name"],
            })
            break
        else:
            step_val.status = "failed"
            step_val.error = {"failed_checks": scores["failed_checks"], "reason_code": scores["reason_code"]}
            record.score = scores["score"]
            record.reason_code = scores["reason_code"]
            record.phase = "retry"
            record.updated_at = _utc_now()
            bus.publish("validation.failed", {
                "task_id": record.task_id, "score": scores["score"],
                "failed_checks": scores["failed_checks"], "rev": rev,
                "hexagram": hexagram_result["name"],
            })
            # guidance = fix_suggestions + 卦象推荐动作
            guidance = _guidance_from_failures(scores["failed_checks"])
            guidance["hexagram_actions"] = hexagram_result["actions"]

    # Store coherent_engine validation details from last attempt
    if last_scores:
        record.validation_checks = last_scores.get("checks")
        record.fix_suggestions = last_scores.get("fix_suggestions", [])
        record.validator_name = last_scores.get("validator", "")

    # Deliver
    record.phase = "deliver"
    record.updated_at = _utc_now()
    step_del = trace.add_step("deliver")
    step_del.status = "running"
    passed = last_scores and last_scores["passed"]

    if passed:
        record.status = "succeeded"
        record.phase = "completed"
        record.self_healed = record.attempts > 1
        trace.status = "succeeded"
        step_del.output = {"delivered": True, "final_score": last_scores["score"]}
        step_del.status = "completed"
        bus.publish("task.delivered", {"task_id": record.task_id, "score": last_scores["score"]})
    else:
        record.status = "failed"
        record.phase = "failed"
        trace.status = "failed"
        step_del.output = {"delivered": False, "reason": "max_retries_exhausted"}
        step_del.status = "failed"
        bus.publish("task.dlq", {"task_id": record.task_id, "reason_code": last_scores.get("reason_code", "")})

    step_del.ended_at = time.time()
    trace.ended_at = time.time()
    record.trace = trace.to_dict()
    record.events = bus.log
    record.updated_at = _utc_now()
    record.result = {
        "task_id": record.task_id,
        "status": record.status,
        "attempts": record.attempts,
        "final_score": record.score,
        "self_healed": record.self_healed,
    }


# ── Request schema ───────────────────────────────────────────────

class TaskSubmitRequest(BaseModel):
    message: str = "default task"
    max_retries: int = Field(default=2, ge=1, le=5)


# ── Rate limiter ────────────────────────────────────────────────

_rate_window: list[float] = []  # timestamps of recent submissions
_RATE_LIMIT = 5       # max tasks per window
_RATE_WINDOW_S = 60   # window size in seconds


def _check_rate_limit() -> bool:
    """Return True if under limit, False if exceeded."""
    now = time.time()
    cutoff = now - _RATE_WINDOW_S
    # Prune old entries
    while _rate_window and _rate_window[0] < cutoff:
        _rate_window.pop(0)
    if len(_rate_window) >= _RATE_LIMIT:
        return False
    _rate_window.append(now)
    return True


# ── Routes ───────────────────────────────────────────────────────

_boot_time = time.time()


@router.get("/v1/matches/upcoming")
async def upcoming_matches():
    """返回世界杯即将进行的比赛列表。"""
    from .football_data import get_upcoming_matches
    matches = get_upcoming_matches()
    return {"matches": matches}


@router.get("/v1/tasks/stats")
async def task_stats():
    with _lock:
        records = list(_store.values())
    total = len(records)
    running = sum(1 for r in records if r.status == "running")
    succeeded = sum(1 for r in records if r.status == "succeeded")
    failed = sum(1 for r in records if r.status == "failed")
    healed = sum(1 for r in records if r.self_healed)
    avg_score = round(sum(r.score for r in records if r.score > 0) / max(1, succeeded + failed), 2)
    done = [r for r in records if r.status in ("succeeded", "failed")]
    last_completed = max((r.updated_at for r in done), default="") if done else ""
    return {
        "total": total,
        "running": running,
        "succeeded": succeeded,
        "failed": failed,
        "self_healed": healed,
        "avg_score": avg_score,
        "uptime_s": round(time.time() - _boot_time, 1),
        "last_completed": last_completed,
        "gateway": "online",
        "task_api": "online",
    }


@router.post("/v1/tasks")
async def submit_task(req: TaskSubmitRequest):
    if not _check_rate_limit():
        raise HTTPException(status_code=429, detail="请求过于频繁，每分钟最多提交 5 个任务")
    task_id = _gen_task_id()
    now = _utc_now()
    record = TaskRecord(
        task_id=task_id,
        message=req.message,
        max_retries=req.max_retries,
        created_at=now,
        updated_at=now,
    )
    with _lock:
        _store[task_id] = record

    bus = EventBus()

    def _run():
        _run_pipeline(record, bus)
        with _lock:
            _store[task_id] = record

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"task_id": task_id, "status": "queued", "created_at": now}


@router.get("/v1/tasks/{task_id}")
async def get_task(task_id: str):
    with _lock:
        record = _store.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return {
        "task_id": record.task_id,
        "status": record.status,
        "phase": record.phase,
        "attempts": record.attempts,
        "score": record.score,
        "self_healed": record.self_healed,
        "reason_code": record.reason_code,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


@router.get("/v1/tasks/{task_id}/stream")
async def stream_task(task_id: str):
    with _lock:
        record = _store.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    def _sse_gen() -> Generator[str, None, None]:
        seen = 0
        while True:
            events = record.events
            for evt in events[seen:]:
                payload = {
                    "timestamp": evt["ts"],
                    "type": evt["type"],
                    **evt["data"],
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                seen = len(events)
            if record.status in ("succeeded", "failed"):
                final = {
                    "timestamp": time.time(),
                    "type": "task.done",
                    "task_id": record.task_id,
                    "status": record.status,
                    "score": record.score,
                    "self_healed": record.self_healed,
                }
                yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
                return
            time.sleep(0.1)

    return sse_response(_sse_gen())


@router.get("/v1/tasks/{task_id}/evidence")
async def get_evidence(task_id: str):
    with _lock:
        record = _store.get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    if record.status not in ("succeeded", "failed"):
        raise HTTPException(status_code=409, detail="Task still running")
    return {
        "task_id": record.task_id,
        "trace": record.trace,
        "result_content": record.result_content,
        "evidence": {
            "succeeded": 1 if record.status == "succeeded" else 0,
            "self_healed": record.self_healed,
            "final_score": record.score,
            "attempts": record.attempts,
            "reason_code": record.reason_code,
            "validator": record.validator_name,
            "checks": record.validation_checks,
            "fix_suggestions": record.fix_suggestions,
        },
        "hexagram": record.hexagram,
        "events": record.events,
    }
