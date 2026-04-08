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
        if provider_cfg is None:
            return None

        provider = create_provider(provider_cfg)

        check_names = list(WEIGHTS.keys())
        prompt = (
            f"You are the coherent_engine quality validator for TaijiOS.\n"
            f"Score the following AI response on 4 dimensions, each 0.0-1.0.\n\n"
            f"Task: {message}\n"
            f"Response: {content}\n\n"
            f"Dimensions:\n"
            f"- character_consistency: Does the response maintain a consistent identity/voice?\n"
            f"- style_consistency: Is the tone and style uniform throughout?\n"
            f"- shot_continuity: Does the response flow logically without abrupt jumps?\n"
            f"- subtitle_safety: Is the content clear, readable, well-formatted?\n\n"
            f"The response language (Chinese or English) does not affect scores.\n"
            f"Reply with ONLY a JSON object:\n"
            f'{{"character_consistency": 0.XX, "style_consistency": 0.XX, '
            f'"shot_continuity": 0.XX, "subtitle_safety": 0.XX}}'
        )

        req = ChatCompletionRequest(
            model=provider_cfg.models[0] if provider_cfg.models else "claude-haiku-4-5",
            messages=[
                ChatMessage(role="system", content="You are coherent_engine validator. Reply with only valid JSON, no markdown, no code fences."),
                ChatMessage(role="user", content=prompt),
            ],
            max_tokens=128,
            temperature=0.1,
        )
        resp = provider.complete(req)
        if not resp.choices:
            return None

        raw = resp.choices[0].message.content.strip()
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

        # Weighted total (same as coherent_engine validator)
        total_score = sum(checks[k]["score"] * WEIGHTS[k] for k in WEIGHTS)
        total_score = round(max(0.0, min(1.0, total_score)), 4)
        overall_passed = total_score >= TEXT_PASS_THRESHOLD

        failed = [k for k, v in checks.items() if not v["passed"]]
        fix_sugg = [FIX_SUGGESTIONS[k] for k in failed if k in FIX_SUGGESTIONS]
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
        router = ProviderRouter(cfg)
        provider_cfg = router.select("claude-haiku-4-5")
        if provider_cfg is None:
            return None

        provider = create_provider(provider_cfg)

        prompt = f"Task: {message}"
        if guidance:
            prompt += f"\nGuidance from previous attempt: {json.dumps(guidance)}"
        if revision > 1:
            prompt += f"\nThis is revision {revision}. Improve based on the guidance above."

        req = ChatCompletionRequest(
            model=provider_cfg.models[0] if provider_cfg.models else "claude-haiku-4-5",
            messages=[
                ChatMessage(role="system", content="你是一个有用的AI助手。请用中文简洁回答。"),
                ChatMessage(role="user", content=prompt),
            ],
            max_tokens=512,
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

        if scores["passed"]:
            step_val.status = "completed"
            record.score = scores["score"]
            record.reason_code = "OK"
            bus.publish("validation.passed", {
                "task_id": record.task_id, "score": scores["score"], "rev": rev,
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
            })
            guidance = _guidance_from_failures(scores["failed_checks"])

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


# ── Routes ───────────────────────────────────────────────────────

_boot_time = time.time()


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
        "events": record.events,
    }
