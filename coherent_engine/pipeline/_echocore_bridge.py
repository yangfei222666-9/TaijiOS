"""
EchoCore-智枢 bridge for coherent_engine job_runner.
Provides Run/Step trajectory tracking + Webhook push.
Degrades gracefully if EchoCore is not on sys.path.
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

_ECHOCORE_DIR = Path(r"C:\Users\A\Desktop\EchoCore-智枢_Fusion_BACKUP_20260320")
if _ECHOCORE_DIR.exists() and str(_ECHOCORE_DIR) not in sys.path:
    sys.path.insert(0, str(_ECHOCORE_DIR))

try:
    from core.run_models import AutomationRun, RunStep, RunStatus, StepStatus  # type: ignore
    from core.webhook import WebhookEmitter  # type: ignore
    _ECHOCORE_AVAILABLE = True
except ImportError:
    _ECHOCORE_AVAILABLE = False


class _NullRun:
    """No-op stand-in when EchoCore is unavailable."""
    run_id = ""
    status = None

    def ensure_ids(self): pass
    def start(self): pass
    def add_step(self, name, step_input=None): return _NullStep()
    def complete(self, output=None): pass
    def fail(self, error=None, output=None): pass
    def to_dict(self): return {}


class _NullStep:
    step_id = ""


def _start_step(step: Any) -> None:
    """Mark a RunStep as running."""
    if not _ECHOCORE_AVAILABLE or isinstance(step, _NullStep):
        return
    import time
    step.status = StepStatus.RUNNING
    step.started_at = time.time()


def _complete_step(step: Any, output: Optional[Dict] = None) -> None:
    if not _ECHOCORE_AVAILABLE or isinstance(step, _NullStep):
        return
    import time
    step.status = StepStatus.COMPLETED
    step.ended_at = time.time()
    if output is not None:
        step.output = output


def _fail_step(step: Any, error: Optional[Dict] = None) -> None:
    if not _ECHOCORE_AVAILABLE or isinstance(step, _NullStep):
        return
    import time
    step.status = StepStatus.FAILED
    step.ended_at = time.time()
    if error is not None:
        step.error = error


def create_run(task_id: str, title: str, source_client: str = "coherent_engine") -> Any:
    """Create and start an AutomationRun (or null stand-in)."""
    if not _ECHOCORE_AVAILABLE:
        return _NullRun()
    run = AutomationRun(
        run_id=task_id,
        title=title,
        source_client=source_client,
    )
    run.ensure_ids()
    run.start()
    return run


def save_run(run: Any, run_dir: Path) -> None:
    """Persist run.to_dict() as run_trace.json inside run_dir."""
    if not _ECHOCORE_AVAILABLE or not hasattr(run, "to_dict") or not run.to_dict():
        return
    import json
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_trace.json"
    path.write_text(json.dumps(run.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def emit_webhook(run: Any, event_type: str, extra: Optional[Dict] = None) -> Optional[Dict]:
    """
    Webhook push with retry + delivery confirmation.
    Reads ECHOCORE_WEBHOOK_URL / ECHOCORE_WEBHOOK_SECRET from env.
    Returns delivery record dict on attempt, None if skipped.
    Webhook failures never propagate to caller.
    """
    url = os.environ.get("ECHOCORE_WEBHOOK_URL", "")
    if not url or not _ECHOCORE_AVAILABLE:
        return None
    secret = os.environ.get("ECHOCORE_WEBHOOK_SECRET", "")

    import asyncio
    import logging
    import time

    log = logging.getLogger(__name__)

    try:
        from core.models import DistributionEvent  # type: ignore
    except ImportError:
        return None

    run_id = getattr(run, "run_id", "")
    run_status = ""
    if hasattr(run, "status") and run.status is not None:
        run_status = run.status.value if hasattr(run.status, "value") else str(run.status)

    payload = {
        "event_type": event_type,
        "run_id": run_id,
        "run_status": run_status,
        **(extra or {}),
    }
    event = DistributionEvent(
        event_id=f"ce_{run_id}_{event_type}_{int(time.time()*1000)}",
        event_type=event_type,
        source_client="coherent_engine",
        experience_data=payload,
        status="pending",
    )
    emitter = WebhookEmitter(url=url, secret=secret)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Async context — schedule and return None (result logged by emitter)
            loop.create_task(emitter.emit(event))
            return None
        else:
            record = loop.run_until_complete(emitter.emit(event))
            if hasattr(record, "to_dict"):
                result = record.to_dict()
                if record.status == "failed":
                    log.warning("[bridge] webhook failed (DLQ) event=%s error=%s",
                                record.event_id, record.last_error)
                return result
            return None
    except Exception as exc:
        log.warning("webhook emit failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 经验闭环：run_trace → EchoCore /experiences/submit
# ---------------------------------------------------------------------------

_ECHOCORE_ENGINE: Any = None
_ECHOCORE_ENGINE_INIT = False


def _get_echocore_engine() -> Any:
    """Lazy-init EchoCoreEngine singleton (local in-process call, no HTTP)."""
    global _ECHOCORE_ENGINE, _ECHOCORE_ENGINE_INIT
    if _ECHOCORE_ENGINE_INIT:
        return _ECHOCORE_ENGINE
    _ECHOCORE_ENGINE_INIT = True
    if not _ECHOCORE_AVAILABLE:
        return None
    try:
        from core.engine import EchoCoreEngine  # type: ignore
        _ECHOCORE_ENGINE = EchoCoreEngine(_ECHOCORE_DIR / "echocore_data")
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("EchoCoreEngine init failed: %s", exc)
        _ECHOCORE_ENGINE = None
    return _ECHOCORE_ENGINE


def _run_trace_to_experience_payload(
    run: Any,
    job_id: str,
    score: Optional[float],
    failed_checks: list,
    rev_count: int,
) -> Dict[str, Any]:
    """Map run_trace fields → EchoCore experience payload."""
    import json as _json

    # resolve reason_codes from failed_checks
    try:
        from coherent_engine.pipeline.reason_codes import RC, FAILED_CHECK_TO_RC, failed_checks_to_rc
        reason_code = failed_checks_to_rc(failed_checks) if failed_checks else RC.OK
        reason_codes = [FAILED_CHECK_TO_RC.get(c, RC.VAL_SCORE_LOW) for c in failed_checks]
    except ImportError:
        reason_code = ""
        reason_codes = []

    run_id = getattr(run, "run_id", "")
    passed = getattr(run.status, "value", "") in ("completed", "succeeded") if hasattr(run, "status") else False

    failure_summary = ""
    if failed_checks:
        failure_summary = f"rev1 failed checks: {', '.join(failed_checks)} → {reason_code}. "
    result_summary = f"Final score: {score:.4f}. Passed: {passed}. Revisions: {rev_count}."

    run_dict = run.to_dict() if hasattr(run, "to_dict") else {}
    content = _json.dumps(run_dict, ensure_ascii=False, indent=2)

    tags = ["run_trace", "coherent_engine"]
    if passed:
        tags.append("job.done")
    else:
        tags.append("job.dlq")
    if failed_checks:
        tags += [f"fail:{c}" for c in failed_checks]
    if reason_code and reason_code != "OK.OK.OK":
        tags.append(reason_code)
    if rev_count > 1:
        tags.append(f"rev{rev_count}_success" if passed else f"rev{rev_count}_fail")

    return {
        "title": f"coherent_job/{job_id}/{run_id}",
        "description": f"{failure_summary}{result_summary}",
        "content": content,
        "type": "workflow",
        "tech_domains": ["ai_ml"],
        "input_context": f"job_id={job_id} task_id={run_id}",
        "solution": content,
        "result": result_summary,
        "tags": tags,
        "metadata": {
            "source_system": "coherent_engine",
            "custom_fields": {
                "task_id": run_id,
                "job_id": job_id,
                "score": score,
                "rev_count": rev_count,
                "passed": passed,
                "failed_checks": failed_checks,
                "reason_code": reason_code,
                "reason_codes": reason_codes,
            },
        },
    }


def report_fail_to_echocore(
    run: Any,
    job_id: str,
    failed_checks: list,
    score: Optional[float],
    attempts: int,
) -> None:
    """
    Call EchoCoreEngine.fail_run() locally so the run record in EchoCore
    carries structured reason_code/reason_codes/score.
    Failures are silently swallowed — never propagate to caller.
    """
    import logging
    log = logging.getLogger(__name__)

    if not _ECHOCORE_AVAILABLE:
        return
    engine = _get_echocore_engine()
    if engine is None:
        return

    run_id = getattr(run, "run_id", "")
    if not run_id:
        return

    try:
        from coherent_engine.pipeline.reason_codes import RC, FAILED_CHECK_TO_RC, failed_checks_to_rc
        reason_code = failed_checks_to_rc(failed_checks) if failed_checks else RC.SYS_DLQ
        reason_codes = [FAILED_CHECK_TO_RC.get(c, RC.VAL_SCORE_LOW) for c in failed_checks]
    except ImportError:
        reason_code = "sys.queue.dead_letter"
        reason_codes = []

    error_payload = {
        "failed_checks": failed_checks,
        "score": score,
        "attempts": attempts,
        "reason_code": reason_code,
        "reason_codes": reason_codes,
        "job_id": job_id,
    }
    output_payload = {
        "reason_code": reason_code,
        "reason_codes": reason_codes,
        "failed_checks": failed_checks,
        "score": score,
    }
    try:
        engine.fail_run(
            run_id=run_id,
            error=error_payload,
            output=output_payload,
            client_id="coherent_engine",
        )
        log.info("fail_run reported to EchoCore: %s reason=%s", run_id, reason_code)
    except Exception as exc:
        log.warning("report_fail_to_echocore failed: %s", exc)


def _find_existing_experience(engine: Any, title: str) -> Optional[str]:
    """
    Return experience_id if an experience with this exact title already exists
    in the EchoCore storage, otherwise None.
    Idempotency key: title = coherent_job/{job_id}/{run_id}
    """
    import json as _json
    import logging
    log = logging.getLogger(__name__)
    try:
        exp_dir = engine.storage.experiences_dir
        for f in exp_dir.glob("exp_*.json"):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                if data.get("title") == title:
                    return data.get("id") or f.stem
            except Exception:
                continue
    except Exception as exc:
        log.debug("_find_existing_experience scan failed: %s", exc)
    return None


def submit_run_as_experience(
    run: Any,
    job_id: str,
    score: Optional[float] = None,
    failed_checks: Optional[list] = None,
    rev_count: int = 1,
) -> Optional[str]:
    """
    Persist run_trace as an EchoCore experience (local in-process).
    Returns experience_id on success, None on failure/unavailable.
    Idempotency key: title = coherent_job/{job_id}/{run_id}.
    If an experience with the same title already exists, returns its id
    immediately (noop_idempotent) without creating a duplicate.
    """
    import asyncio
    import logging

    log = logging.getLogger(__name__)

    if not _ECHOCORE_AVAILABLE:
        return None
    if not hasattr(run, "to_dict") or not run.to_dict():
        return None

    engine = _get_echocore_engine()
    if engine is None:
        return None

    payload = _run_trace_to_experience_payload(
        run=run,
        job_id=job_id,
        score=score,
        failed_checks=failed_checks or [],
        rev_count=rev_count,
    )

    # --- idempotent dedup ---
    existing_id = _find_existing_experience(engine, payload["title"])
    if existing_id:
        log.info("noop_idempotent: experience already exists title=%s id=%s", payload["title"], existing_id)
        return existing_id

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # inside async context — schedule and return None (fire-and-forget)
            async def _submit():
                try:
                    exp = await engine.submit_experience(payload, "coherent_engine")
                    log.info("experience submitted: %s", exp.id)
                except Exception as e:
                    log.warning("experience submit failed: %s", e)
            loop.create_task(_submit())
            return None
        else:
            exp = loop.run_until_complete(engine.submit_experience(payload, "coherent_engine"))
            log.info("experience submitted: %s", exp.id)
            return exp.id
    except Exception as exc:
        log.warning("submit_run_as_experience failed: %s", exc)
        return None
