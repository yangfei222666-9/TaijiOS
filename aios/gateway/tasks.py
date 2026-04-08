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
    """Validate generated content. Uses LLM scoring if available, else simulated."""
    result = _validate_with_llm(content, message)
    if result is not None:
        return result
    # Fallback: simulated
    score = 0.35 + (attempt - 1) * 0.55
    passed = score >= 0.80
    failed_checks = []
    if not passed:
        failed_checks = ["style_consistency", "character_consistency"]
    return {
        "score": round(score, 4),
        "passed": passed,
        "failed_checks": failed_checks,
        "reason_code": "OK" if passed else "coherent.validator.style_consistency",
    }


def _validate_with_llm(content: str, message: str) -> dict | None:
    """Use LLM to score generated content quality. Returns score dict or None."""
    if not content or not message:
        return None
    try:
        from .config import load_config
        from .router import ProviderRouter
        from .providers import create_provider
        from .schemas import ChatCompletionRequest, ChatMessage

        cfg = load_config()
        router = ProviderRouter(cfg)
        provider_cfg = router.select("deepseek-chat")
        if provider_cfg is None:
            return None

        provider = create_provider(provider_cfg)

        prompt = (
            f"Rate the following AI response on a scale of 0.0 to 1.0.\n"
            f"Task: {message}\n"
            f"Response: {content}\n\n"
            f"Score criteria: relevance, completeness, clarity.\n"
            f"Reply with ONLY a JSON object: {{\"score\": 0.XX, \"passed\": true/false, \"failed_checks\": [], \"reason_code\": \"OK\"}}\n"
            f"passed = true if score >= 0.7. If failed, set failed_checks to relevant issues and reason_code to a short code."
        )

        req = ChatCompletionRequest(
            model=provider_cfg.models[0] if provider_cfg.models else "deepseek-chat",
            messages=[
                ChatMessage(role="system", content="You are a strict quality evaluator. Reply with only valid JSON, no markdown."),
                ChatMessage(role="user", content=prompt),
            ],
            max_tokens=128,
            temperature=0.1,
        )
        resp = provider.complete(req)
        if not resp.choices:
            return None

        raw = resp.choices[0].message.content.strip()
        # Parse JSON from response
        result = json.loads(raw)
        score = float(result.get("score", 0))
        passed = result.get("passed", score >= 0.7)
        return {
            "score": round(score, 4),
            "passed": passed,
            "failed_checks": result.get("failed_checks", []),
            "reason_code": result.get("reason_code", "OK" if passed else "quality.low"),
        }
    except Exception as e:
        log.warning(f"LLM validate failed, falling back to simulation: {e}")
        return None


def _guidance_from_failures(failed_checks: list) -> dict:
    guidance = {}
    if "style_consistency" in failed_checks:
        guidance["stable_style"] = True
    if "character_consistency" in failed_checks:
        guidance["stable_character"] = True
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
        provider_cfg = router.select("deepseek-chat")
        if provider_cfg is None:
            return None

        provider = create_provider(provider_cfg)

        prompt = f"Task: {message}"
        if guidance:
            prompt += f"\nGuidance from previous attempt: {json.dumps(guidance)}"
        if revision > 1:
            prompt += f"\nThis is revision {revision}. Improve based on the guidance above."

        req = ChatCompletionRequest(
            model=provider_cfg.models[0] if provider_cfg.models else "deepseek-chat",
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
    return {
        "total": total,
        "running": running,
        "succeeded": succeeded,
        "failed": failed,
        "self_healed": healed,
        "avg_score": avg_score,
        "uptime_s": round(time.time() - _boot_time, 1),
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
        },
        "events": record.events,
    }
