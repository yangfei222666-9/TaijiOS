import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_AGENT_SYSTEM = _ROOT / "aios" / "agent_system"
if _AGENT_SYSTEM.exists() and str(_AGENT_SYSTEM) not in sys.path:
    sys.path.insert(0, str(_AGENT_SYSTEM))

import numpy as np

from coherent_engine.modules.validator import validate
from coherent_engine.pipeline.planner import build_plan, write_plan, normalize_job_request
from coherent_engine.pipeline._echocore_bridge import (
    create_run, save_run, emit_webhook,
    _start_step, _complete_step, _fail_step,
    submit_run_as_experience, report_fail_to_echocore,
)
from coherent_engine.pipeline.reason_codes import RC, failed_checks_to_rc
from coherent_engine.pipeline.llm_client import make_llm_client


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _refresh_quality_report(cycle_id: str = ""):
    """Silently refresh experience_quality_latest.json after each job."""
    try:
        from coherent_engine.pipeline.experience_retrieval import generate_report
        generate_report(cycle_id=cycle_id)
    except Exception:
        pass


def _sha1_text(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _jobs_root() -> Path:
    env = os.environ.get("TAIJI_JOBS_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[1] / "jobs"


def _revision_dir(job_dir: Path, rev: int) -> Path:
    return job_dir / f"rev_{rev}"


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def _artifact_ledger_append(
    *,
    task_id: str,
    artifact_path: Path,
    artifact_type: str,
    producer: str,
    status: str,
    reason_code: str,
    created_at: str,
    revision_artifact_jsonl: Path,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from artifact_ledger import append_artifact_event

    record = append_artifact_event(
        task_id=task_id,
        artifact_path=str(artifact_path),
        artifact_type=artifact_type,
        producer=producer,
        status=status,
        reason_code=reason_code,
        created_at=created_at,
        metadata=metadata or {},
    )
    _append_jsonl(revision_artifact_jsonl, record)
    return record


def _enqueue_dlq(*, task_id: str, attempts: int, last_error: str, metadata: Dict[str, Any]) -> None:
    from dlq import enqueue_dead_letter

    enqueue_dead_letter(
        task_id=task_id,
        attempts=attempts,
        last_error=last_error,
        error_type="validation_failed",
        metadata=metadata,
    )


def _generate_frames_4shot(
    *,
    req: Dict[str, Any],
    revision: int,
    out_dir: Path,
    guidance: Optional[Dict[str, Any]] = None,
) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    script: List[str] = list(req["script"])
    colors: List[Tuple[int, int, int]] = []

    base_seed = int(_sha1_text(req["job_id"])[:8], 16) ^ int(revision)
    rng = np.random.default_rng(base_seed)

    stable_style = bool((guidance or {}).get("stable_style"))
    stable_character = bool((guidance or {}).get("stable_character"))
    stable_motion = bool((guidance or {}).get("stable_motion"))

    if stable_style or stable_character:
        r = int(rng.integers(40, 220))
        g = int(rng.integers(40, 220))
        b = int(rng.integers(40, 220))
        colors = [(r, g, b) for _ in range(4)]
    else:
        for i in range(4):
            h = int(_sha1_text(script[i % len(script)])[:6], 16)
            r = (h >> 16) & 0xFF
            g = (h >> 8) & 0xFF
            b = h & 0xFF
            colors.append((int(r), int(g), int(b)))

    frames: List[Path] = []
    for i in range(4):
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        img[:, :] = colors[i]

        if not stable_motion:
            cx = int(rng.integers(10, 54))
            cy = int(rng.integers(10, 54))
        else:
            cx, cy = 32, 32
        rr = 8
        y, x = np.ogrid[:64, :64]
        mask = (x - cx) ** 2 + (y - cy) ** 2 <= rr ** 2
        img[mask] = (255, 255, 255)

        p = out_dir / f"shot_{i+1:02d}.npy"
        np.save(str(p), img)
        frames.append(p)

    return frames


def _load_frames(frame_files: List[Path]) -> List[np.ndarray]:
    frames: List[np.ndarray] = []
    for p in frame_files:
        frames.append(np.load(str(p)))
    return frames


def load_frames_from_dir(frames_dir: Path) -> List[np.ndarray]:
    """
    从目录读取真实图片帧（jpg/jpeg/png），按文件名排序。
    空目录 → raise ValueError(RC.SYS_FRAMES_EMPTY)
    少于2帧 → raise ValueError(RC.SYS_FRAMES_TOOFEW)
    单张读失败 → 记录警告并跳过；全部失败 → raise ValueError(RC.SYS_FRAMES_CORRUPT)
    尺寸不一致 → resize 到第一帧尺寸（不阻断）
    """
    import logging
    from coherent_engine.pipeline.reason_codes import RC
    log = logging.getLogger(__name__)

    exts = {".jpg", ".jpeg", ".png"}
    files = sorted([p for p in Path(frames_dir).iterdir() if p.suffix.lower() in exts])
    if not files:
        raise ValueError(RC.SYS_FRAMES_EMPTY)

    try:
        from PIL import Image as _PIL
        _use_pil = True
    except ImportError:
        _use_pil = False

    frames: List[np.ndarray] = []
    target_shape = None
    for p in files:
        try:
            if _use_pil:
                img = np.array(_PIL.open(p).convert("RGB"))[..., ::-1]  # RGB→BGR
            else:
                import cv2  # type: ignore
                img = cv2.imread(str(p))
                if img is None:
                    raise ValueError(f"cv2.imread returned None for {p}")
            img = img.astype(np.uint8)
            if target_shape is None:
                target_shape = img.shape[:2]
            elif img.shape[:2] != target_shape:
                if _use_pil:
                    from PIL import Image as _PIL2
                    pil_img = _PIL2.fromarray(img[..., ::-1]).resize(
                        (target_shape[1], target_shape[0]))
                    img = np.array(pil_img)[..., ::-1].astype(np.uint8)
                else:
                    import cv2 as _cv2  # type: ignore
                    img = _cv2.resize(img, (target_shape[1], target_shape[0]))
                log.warning("frame resized to %s: %s", target_shape, p.name)
            frames.append(img)
        except Exception as e:
            log.warning("skip corrupt frame %s: %s", p.name, e)

    if not frames:
        raise ValueError(RC.SYS_FRAMES_CORRUPT)
    if len(frames) < 2:
        raise ValueError(RC.SYS_FRAMES_TOOFEW)
    return frames


def _build_frames_manifest(frame_files: List[Path]) -> Dict[str, Any]:
    entries: List[Dict[str, Any]] = []
    for p in frame_files:
        entries.append(
            {
                "path": str(p),
                "name": p.name,
                "bytes": int(p.stat().st_size) if p.exists() else 0,
                "sha256": _sha256_file(p) if p.exists() else "",
            }
        )
    return {"count": len(entries), "frames": entries}


def _guidance_from_failed_checks(failed_checks: List[str]) -> Dict[str, Any]:
    guidance: Dict[str, Any] = {}
    if "character_consistency" in failed_checks:
        guidance["stable_character"] = True
    if "style_consistency" in failed_checks:
        guidance["stable_style"] = True
    if "shot_continuity" in failed_checks:
        guidance["stable_motion"] = True
    return guidance


def run_job(
    *,
    task_id: str,
    job_request: Dict[str, Any],
    max_retries: int = 2,
) -> Dict[str, Any]:
    req = normalize_job_request(job_request)
    jobs_root = _jobs_root()
    job_dir = jobs_root / req.job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    # EchoCore run trace
    run = create_run(task_id=task_id, title=f"coherent_job:{req.job_id}")

    _exp_reason = str(job_request.get("reason_code") or os.environ.get("COHERENT_REASON_CODE_HINT", "") or "").strip()
    _experience = None
    step_exp = run.add_step("experience_retrieval", step_input={"reason_code": _exp_reason, "brand_rules_id": req.brand_rules_id, "character_id": req.character_id})
    _start_step(step_exp)
    try:
        if _exp_reason:
            from coherent_engine.pipeline.experience_retrieval import retrieve_experience
            _experience = retrieve_experience(brand_rules_id=req.brand_rules_id, character_id=req.character_id, reason_code=_exp_reason)
        if _experience:
            os.environ["COHERENT_EXPERIENCE_INJECT"] = str(_experience.get("content") or "")
            os.environ["COHERENT_EXPERIENCE_ID"] = str(_experience.get("source_experience_id") or "")
            _write_json(job_dir / "experience_inject.json", _experience)
            _complete_step(step_exp, output={"experience_hit": True, "matched_key": _experience.get("matched_key", ""), "confidence": _experience.get("confidence", 0), "inject_to": _experience.get("inject_to", ""), "source_experience_id": _experience.get("source_experience_id", "")})
        else:
            _complete_step(step_exp, output={"experience_hit": False})
    except Exception as _exp_exc:
        _complete_step(step_exp, output={"experience_hit": False, "error": str(_exp_exc)})
    save_run(run, job_dir)

    _planner_mode = os.environ.get("COHERENT_PLANNER_MODE", "mock")
    _llm_client = make_llm_client() if _planner_mode == "llm" else None
    if _planner_mode == "llm" and _llm_client is None:
        import logging as _log
        _log.getLogger(__name__).warning("planner_mode=llm but no API key, falling back to mock. reason=%s", RC.DEP_ANTHROPIC_NO_KEY)
    plan = build_plan(job_request, planner_mode=_planner_mode, llm_client=_llm_client)
    if _experience and isinstance(plan.get("meta"), dict):
        plan["meta"]["experience_id"] = str(_experience.get("source_experience_id") or "")
        plan["meta"]["experience_key"] = str(_experience.get("matched_key") or "")
    plan_path = write_plan(job_dir, plan)

    # PromptBuilderSkill：shots → prompts，落盘 prompt_plan.json
    _prompt_plan: list = []
    try:
        from coherent_engine.pipeline.prompt_builder import build_prompts
        _shots = plan.get("shots") or []
        # 注入 brand_rules_id / character_id 到每个 shot
        for _shot in _shots:
            if "brand_rules_id" not in _shot:
                _shot["brand_rules_id"] = req.brand_rules_id
            if "character_id" not in _shot:
                _shot["character_id"] = req.character_id
        _prompt_plan = build_prompts(_shots)
        _prompt_plan_path = job_dir / "prompt_plan.json"
        _write_json(_prompt_plan_path, _prompt_plan)
        import logging as _log
        _log.getLogger(__name__).info("prompt_builder ok: shots=%d", len(_prompt_plan))
    except Exception as _pb_exc:
        import logging as _log
        _log.getLogger(__name__).warning("prompt_builder failed (non-blocking): %s", _pb_exc)

    # 真实帧目录（优先于合成帧）
    _frames_dir = job_request.get("frames_dir") or os.environ.get("COHERENT_FRAMES_DIR", "")

    created_at = _utc_now()
    deliverable_dir = job_dir / "deliverable"

    last_scores: Optional[Dict[str, Any]] = None
    last_failed_checks: List[str] = []
    guidance: Dict[str, Any] = {}

    for attempt in range(max_retries + 1):
        rev = attempt + 1
        rev_dir = _revision_dir(job_dir, rev)
        frames_dir = rev_dir / "frames"
        frames_manifest_path = rev_dir / "frames_manifest.json"
        scores_path = rev_dir / "scores.json"
        rev_artifact_jsonl = rev_dir / "artifact.jsonl"
        state_path = rev_dir / "state.json"

        _write_json(
            state_path,
            {
                "job_id": req.job_id,
                "task_id": task_id,
                "revision": rev,
                "attempt": attempt,
                "state": "GENERATING",
                "created_at": created_at,
                "updated_at": _utc_now(),
                "guidance": guidance,
            },
        )

        step_gen = run.add_step(f"generate_frames:rev{rev}", step_input={"revision": rev, "guidance": guidance})
        _start_step(step_gen)
        _frames_source = "synthetic"
        if _frames_dir:
            import logging as _log
            try:
                frames = load_frames_from_dir(Path(_frames_dir))
                frame_files = []  # 真实帧不走 .npy 路径
                _frames_source = "real"
                _log.getLogger(__name__).info(
                    "real frames loaded: count=%d dir=%s", len(frames), _frames_dir)
            except ValueError as e:
                _log.getLogger(__name__).warning(
                    "load_frames_from_dir failed reason=%s, fallback to synthetic", e)
                frame_files = _generate_frames_4shot(
                    req=job_request, revision=rev, out_dir=frames_dir, guidance=guidance)
                frames = _load_frames(frame_files)
        else:
            frame_files = _generate_frames_4shot(
                req=job_request, revision=rev, out_dir=frames_dir, guidance=guidance)
            frames = _load_frames(frame_files)
        if frame_files:
            _write_json(frames_manifest_path, _build_frames_manifest(frame_files))
        else:
            _write_json(frames_manifest_path, {"count": len(frames), "frames": [], "source": _frames_source, "frames_dir": str(_frames_dir)})
        _complete_step(step_gen, output={
            "frame_count": len(frames),
            "frames_source": _frames_source,
            "frames_dir": str(_frames_dir) if _frames_dir else "",
            "planner_mode": plan.get("meta", {}).get("planner_mode", ""),
            "llm_model": plan.get("meta", {}).get("llm_model", ""),
            "prompt_hash": plan.get("meta", {}).get("prompt_hash", ""),
            "plan_hash": plan.get("meta", {}).get("plan_hash", ""),
            "prompt_builder_count": len(_prompt_plan),
        })
        _gen_evidence = [{"type": "frames_manifest", "path": str(frames_manifest_path), "sha256": _sha256_file(frames_manifest_path) if frames_manifest_path.exists() else ""}]
        if plan_path.exists():
            _gen_evidence.append({"type": "plan", "path": str(plan_path), "sha256": _sha256_file(plan_path), "revision": rev})
        _prompt_plan_path = job_dir / "prompt_plan.json"
        if _prompt_plan_path.exists():
            _gen_evidence.append({"type": "prompt_plan", "path": str(_prompt_plan_path), "sha256": _sha256_file(_prompt_plan_path), "revision": rev})
        step_gen.evidence = _gen_evidence
        save_run(run, job_dir)

        _write_json(
            state_path,
            {
                "job_id": req.job_id,
                "task_id": task_id,
                "revision": rev,
                "attempt": attempt,
                "state": "VALIDATING",
                "created_at": created_at,
                "updated_at": _utc_now(),
                "guidance": guidance,
                "frames": [str(p) for p in frame_files],
            },
        )

        step_val = run.add_step(f"validate:rev{rev}", step_input={"revision": rev})
        _start_step(step_val)
        scores = validate(frames=frames, safe_area={"top_pct": 5, "bottom_pct": 15, "left_pct": 5, "right_pct": 5})
        last_scores = scores
        last_failed_checks = list(scores.get("failed_checks") or [])
        if scores.get("passed"):
            _complete_step(step_val, output={"score": scores.get("score"), "passed": True})
            step_val.evidence = [{"type": "scores", "path": str(scores_path), "sha256": _sha256_file(scores_path) if scores_path.exists() else ""}]
        else:
            rc = failed_checks_to_rc(last_failed_checks)
            _fail_step(step_val, error={"failed_checks": last_failed_checks, "score": scores.get("score"), "reason_code": rc})
        save_run(run, job_dir)

        _write_json(scores_path, scores)

        _artifact_ledger_append(
            task_id=task_id,
            artifact_path=plan_path,
            artifact_type="plan",
            producer="coherent_engine.pipeline.planner",
            status="created",
            reason_code="ok",
            created_at=_utc_now(),
            revision_artifact_jsonl=rev_artifact_jsonl,
            metadata={"job_id": req.job_id, "revision": rev},
        )
        _artifact_ledger_append(
            task_id=task_id,
            artifact_path=frames_manifest_path,
            artifact_type="frames",
            producer="coherent_engine.pipeline.job_runner",
            status="created",
            reason_code="ok",
            created_at=_utc_now(),
            revision_artifact_jsonl=rev_artifact_jsonl,
            metadata={"job_id": req.job_id, "revision": rev, "count": len(frame_files), "frames_dir": str(frames_dir)},
        )
        _artifact_ledger_append(
            task_id=task_id,
            artifact_path=scores_path,
            artifact_type="scores",
            producer="coherent_engine.modules.validator",
            status="created",
            reason_code="ok" if scores.get("passed") else "validation_failed",
            created_at=_utc_now(),
            revision_artifact_jsonl=rev_artifact_jsonl,
            metadata={"job_id": req.job_id, "revision": rev, "score": scores.get("score"), "failed_checks": last_failed_checks},
        )

        if scores.get("passed"):
            step_del = run.add_step(f"deliver:rev{rev}", step_input={"revision": rev})
            _start_step(step_del)
            _write_json(
                state_path,
                {
                    "job_id": req.job_id,
                    "task_id": task_id,
                    "revision": rev,
                    "attempt": attempt,
                    "state": "DELIVERING",
                    "created_at": created_at,
                    "updated_at": _utc_now(),
                    "passed": True,
                    "score": scores.get("score"),
                    "failed_checks": last_failed_checks,
                },
            )

            deliverable_dir.mkdir(parents=True, exist_ok=True)
            (deliverable_dir / "frames").mkdir(parents=True, exist_ok=True)
            for p in frame_files:
                (deliverable_dir / "frames" / p.name).write_bytes(p.read_bytes())
            (deliverable_dir / "scores.json").write_bytes(scores_path.read_bytes())
            (deliverable_dir / "plan.json").write_bytes(plan_path.read_bytes())
            (deliverable_dir / "revision.txt").write_text(str(rev), encoding="utf-8")
            # provenance: 追溯到具体 revision 和 artifact hash
            _write_json(deliverable_dir / "provenance.json", {
                "job_id": req.job_id,
                "task_id": task_id,
                "revision": rev,
                "plan_sha256": _sha256_file(plan_path),
                "scores_sha256": _sha256_file(scores_path),
                "frames_sha256": {p.name: _sha256_file(p) for p in frame_files},
                "created_at": _utc_now(),
            })

            _complete_step(step_del, output={"deliverable_dir": str(deliverable_dir)})
            run.complete(output={"job_id": req.job_id, "revision": rev, "score": scores.get("score")})
            save_run(run, job_dir)
            submit_run_as_experience(
                run=run, job_id=req.job_id,
                score=scores.get("score"), failed_checks=last_failed_checks, rev_count=rev,
            )
            emit_webhook(run, "job.done", extra={"job_id": req.job_id, "revision": rev, "score": scores.get("score"), "deliverable_dir": str(deliverable_dir)})
            # Record experience outcome (quality feedback)
            _exp_id = os.environ.get("COHERENT_EXPERIENCE_ID", "")
            if _exp_id:
                try:
                    from coherent_engine.pipeline.experience_retrieval import record_outcome
                    record_outcome(_exp_id, passed=True)
                except Exception:
                    pass
            _write_json(
                state_path,
                {
                    "job_id": req.job_id,
                    "task_id": task_id,
                    "revision": rev,
                    "attempt": attempt,
                    "state": "DONE",
                    "created_at": created_at,
                    "updated_at": _utc_now(),
                    "passed": True,
                    "score": scores.get("score"),
                    "failed_checks": last_failed_checks,
                    "deliverable_dir": str(deliverable_dir),
                },
            )
            _refresh_quality_report(cycle_id=f"job:{req.job_id}")
            return {
                "job_id": req.job_id,
                "task_id": task_id,
                "revision": rev,
                "passed": True,
                "scores_path": str(scores_path),
                "deliverable_dir": str(deliverable_dir),
            }

        retry_record = {
            "job_id": req.job_id,
            "task_id": task_id,
            "revision": rev,
            "attempt": attempt,
            "score": scores.get("score"),
            "failed_checks": last_failed_checks,
            "fix_suggestions": scores.get("fix_suggestions", []),
            "checks_detail": scores.get("checks", {}),
            "timestamp": _utc_now(),
        }
        _append_jsonl(job_dir / "retry_log.jsonl", retry_record)
        _write_json(
            state_path,
            {
                "job_id": req.job_id,
                "task_id": task_id,
                "revision": rev,
                "attempt": attempt,
                "state": "RETRYING",
                "created_at": created_at,
                "updated_at": _utc_now(),
                "passed": False,
                "score": scores.get("score"),
                "failed_checks": last_failed_checks,
                "fix_suggestions": scores.get("fix_suggestions"),
            },
        )

        if attempt >= max_retries:
            _enqueue_dlq(
                task_id=task_id,
                attempts=attempt + 1,
                last_error=json.dumps(scores, ensure_ascii=False),
                metadata={"job_id": req.job_id, "revision": rev, "failed_checks": last_failed_checks},
            )
            run.fail(error={"failed_checks": last_failed_checks, "score": scores.get("score"), "attempts": attempt + 1, "reason_code": RC.SYS_DLQ})
            save_run(run, job_dir)
            report_fail_to_echocore(
                run=run, job_id=req.job_id,
                failed_checks=last_failed_checks, score=scores.get("score"), attempts=attempt + 1,
            )
            submit_run_as_experience(
                run=run, job_id=req.job_id,
                score=scores.get("score"), failed_checks=last_failed_checks, rev_count=rev,
            )
            emit_webhook(run, "job.dlq", extra={"job_id": req.job_id, "revision": rev, "failed_checks": last_failed_checks})
            # Record experience outcome (quality feedback — failure)
            _exp_id = os.environ.get("COHERENT_EXPERIENCE_ID", "")
            if _exp_id:
                try:
                    from coherent_engine.pipeline.experience_retrieval import record_outcome
                    record_outcome(_exp_id, passed=False)
                except Exception:
                    pass
            _write_json(
                state_path,
                {
                    "job_id": req.job_id,
                    "task_id": task_id,
                    "revision": rev,
                    "attempt": attempt,
                    "state": "DLQ",
                    "created_at": created_at,
                    "updated_at": _utc_now(),
                    "passed": False,
                    "score": scores.get("score"),
                    "failed_checks": last_failed_checks,
                },
            )
            _refresh_quality_report(cycle_id=f"job:{req.job_id}")
            return {
                "job_id": req.job_id,
                "task_id": task_id,
                "revision": rev,
                "passed": False,
                "scores_path": str(scores_path),
                "deliverable_dir": None,
            }

        guidance = _guidance_from_failed_checks(last_failed_checks)

    return {
        "job_id": req.job_id,
        "task_id": task_id,
        "revision": max_retries + 1,
        "passed": False,
        "scores_path": None,
        "deliverable_dir": None,
    }


def _enqueue_job_to_durable_queue(task_id: str, payload: Dict[str, Any], max_retries: int) -> None:
    from task_queue import TaskQueue
    from paths import TASK_QUEUE

    q = TaskQueue(queue_file=str(TASK_QUEUE))
    q.enqueue_task(task_id=task_id, payload=payload, max_retries=max_retries)


def run_worker_once(worker_id: str) -> Optional[Dict[str, Any]]:
    from task_queue import TaskQueue
    from paths import TASK_QUEUE

    q = TaskQueue(queue_file=str(TASK_QUEUE))
    task = q.acquire_task(worker_id=worker_id)
    if not task:
        return None

    task_id = task.task_id
    payload = dict(task.payload or {})

    try:
        result = run_job(task_id=task_id, job_request=payload, max_retries=int(payload.get("max_retries", 2)))
        if result.get("passed"):
            q.transition_status(task_id, "running", "succeeded")
        else:
            q.transition_status(task_id, "running", "permanently_failed")
        return result
    except Exception as e:
        q.transition_status(task_id, "running", "failed")
        return {"task_id": task_id, "passed": False, "error": str(e)}


def run_worker_forever(
    worker_id: str,
    poll_interval_s: float = 1.0,
    max_tasks: Optional[int] = None,
) -> Dict[str, Any]:
    processed = 0
    while True:
        if max_tasks is not None and processed >= max_tasks:
            return {"processed": processed, "stopped_reason": "max_tasks_reached"}

        res = run_worker_once(worker_id)
        if res is None:
            time.sleep(poll_interval_s)
            continue

        processed += 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--enqueue", action="store_true")
    p.add_argument("--run-once", action="store_true")
    p.add_argument("--run-worker", action="store_true")
    p.add_argument("--task-id", type=str, default="")
    p.add_argument("--job-id", type=str, default="brand-video-001")
    p.add_argument("--brand-rules-id", type=str, default="brand.example.v1")
    p.add_argument("--character-id", type=str, default="char.xiaojiu.v1")
    p.add_argument("--shot-template-id", type=str, default="tpl.4shot.brand.v1")
    p.add_argument("--worker-id", type=str, default="coherent_job_runner")
    p.add_argument("--max-retries", type=int, default=2)
    p.add_argument("--poll-interval-s", type=float, default=1.0)
    p.add_argument("--max-tasks", type=int, default=0)
    p.add_argument("--frames-dir", type=str, default="", help="真实帧目录（jpg/jpeg/png），设置后跳过合成帧生成")
    args = p.parse_args()

    if args.enqueue:
        task_id = args.task_id or f"coherent:{args.job_id}:{int(time.time())}"
        payload = {
            "job_id": args.job_id,
            "brand_rules_id": args.brand_rules_id,
            "character_id": args.character_id,
            "shot_template_id": args.shot_template_id,
            "script": ["第1条台词", "第2条台词", "第3条台词", "第4条台词"],
            "shots_per_video": 4,
            "max_retries": args.max_retries,
        }
        _enqueue_job_to_durable_queue(task_id=task_id, payload=payload, max_retries=args.max_retries)
        print(json.dumps({"enqueued": True, "task_id": task_id}, ensure_ascii=False))
        return 0

    if args.run_once:
        res = run_worker_once(args.worker_id)
        print(json.dumps(res or {"no_task": True}, ensure_ascii=False, indent=2))
        return 0

    if args.run_worker:
        max_tasks: Optional[int]
        if int(args.max_tasks) <= 0:
            max_tasks = None
        else:
            max_tasks = int(args.max_tasks)
        res = run_worker_forever(args.worker_id, poll_interval_s=float(args.poll_interval_s), max_tasks=max_tasks)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    if args.task_id:
        payload = {
            "job_id": args.job_id,
            "brand_rules_id": args.brand_rules_id,
            "character_id": args.character_id,
            "shot_template_id": args.shot_template_id,
            "script": ["第1条台词", "第2条台词", "第3条台词", "第4条台词"],
            "shots_per_video": 4,
        }
        if args.frames_dir:
            payload["frames_dir"] = args.frames_dir
        res = run_job(task_id=args.task_id, job_request=payload, max_retries=args.max_retries)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
