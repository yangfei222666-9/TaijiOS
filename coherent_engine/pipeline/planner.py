import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class JobRequest:
    job_id: str
    brand_rules_id: str
    character_id: str
    shot_template_id: str
    script: List[str]
    language: str = "zh-CN"
    shots_per_video: int = 4
    target_duration_s: Optional[float] = None


def normalize_job_request(raw: Dict[str, Any]) -> JobRequest:
    job_id = str(raw.get("job_id") or "").strip()
    brand_rules_id = str(raw.get("brand_rules_id") or "").strip()
    character_id = str(raw.get("character_id") or "").strip()
    shot_template_id = str(raw.get("shot_template_id") or "").strip()
    script_raw = raw.get("script")
    language = str(raw.get("language") or "zh-CN").strip()
    shots_per_video = int(raw.get("shots_per_video") or 4)
    target_duration_s = raw.get("target_duration_s")

    if not job_id:
        raise ValueError("JOB_REQUEST_ERROR: job_id is required")
    if not brand_rules_id:
        raise ValueError("JOB_REQUEST_ERROR: brand_rules_id is required")
    if not character_id:
        raise ValueError("JOB_REQUEST_ERROR: character_id is required")
    if not shot_template_id:
        raise ValueError("JOB_REQUEST_ERROR: shot_template_id is required")
    if not isinstance(script_raw, list) or not script_raw:
        raise ValueError("JOB_REQUEST_ERROR: script must be a non-empty list")

    script: List[str] = []
    for i, s in enumerate(script_raw):
        text = str(s or "").strip()
        if not text:
            raise ValueError(f"JOB_REQUEST_ERROR: script[{i}] is empty")
        script.append(text)

    if shots_per_video <= 0:
        raise ValueError("JOB_REQUEST_ERROR: shots_per_video must be positive")

    tds: Optional[float]
    if target_duration_s is None:
        tds = None
    else:
        tds = float(target_duration_s)

    return JobRequest(
        job_id=job_id,
        brand_rules_id=brand_rules_id,
        character_id=character_id,
        shot_template_id=shot_template_id,
        script=script,
        language=language or "zh-CN",
        shots_per_video=shots_per_video,
        target_duration_s=tds,
    )


PLAN_SCHEMA_VERSION = "1.0"


def build_plan(
    raw_request: Dict[str, Any],
    planner_mode: str = "mock",
    llm_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    生成 plan.json。

    planner_mode:
        "mock" - 直接从 job_request 构造结构化 plan（不调用 LLM，用于测试/CI）
        "llm"  - 调用 llm_client 生成分镜细节（llm_client 必须实现 .chat(system, user, model)）
    """
    req = normalize_job_request(raw_request)

    constraints: Dict[str, Any] = {"shots_per_video": req.shots_per_video, "language": req.language}
    if req.target_duration_s is not None:
        constraints["target_duration_s"] = req.target_duration_s

    now = datetime.now(timezone.utc).isoformat()

    shots: List[Dict[str, Any]] = []
    effective_mode = planner_mode
    llm_model = ""
    _prompt_hash = ""
    _plan_hash = ""

    if planner_mode == "llm" and llm_client is not None:
        try:
            from coherent_engine.pipeline.llm_client import prompt_hash as _ph, plan_hash as _plh
            system_prompt = "你是专业短视频分镜规划师。根据脚本生成结构化分镜计划，输出合法 JSON，不要输出任何额外文字。"
            _inj = (os.environ.get("COHERENT_EXPERIENCE_INJECT") or "").strip()
            if _inj:
                system_prompt = system_prompt + "\n" + _inj
            user_prompt = (
                f"脚本（{len(req.script)} 条）：{json.dumps(req.script, ensure_ascii=False)}\n"
                f"请生成 {len(req.script)} 个镜头的分镜。"
            )
            _prompt_hash = _ph(system_prompt, user_prompt)
        except Exception:
            pass
        shots = _build_shots_via_llm(req, llm_client)
        llm_model = getattr(llm_client, "_model", "claude-sonnet-4-6")
    else:
        if planner_mode == "llm":
            effective_mode = "mock"  # llm requested but no client — fallback
        shots = _build_shots_mock(req)

    plan = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "job_id": req.job_id,
        "brand_rules": req.brand_rules_id,
        "style": "",
        "character": req.character_id,
        "shot_template": req.shot_template_id,
        "scripts": req.script,
        "shots": shots,
        "constraints": constraints,
        "meta": {
            "created_at": now,
            "planner": "coherent_engine.pipeline.planner",
            "planner_mode": effective_mode,
            "llm_model": llm_model,
            "prompt_hash": _prompt_hash,
        },
    }
    try:
        from coherent_engine.pipeline.llm_client import plan_hash as _plh
        _plan_hash = _plh(plan)
        plan["meta"]["plan_hash"] = _plan_hash
    except Exception:
        pass
    return plan


def _build_shots_mock(req: "JobRequest") -> List[Dict[str, Any]]:
    """mock 模式：从 script 直接构造最小镜头列表，不调用 LLM。"""
    return [
        {
            "shot_id": f"shot_{i+1:03d}",
            "duration_s": 3.0,
            "scene": "室内-客厅",
            "action": "",
            "dialogue": line,
            "subtitle": line,
            "camera_framing": "medium",
            "camera_angle": "eye",
            "camera_movement": "static",
            "must_keep": [],
            "must_avoid": [],
        }
        for i, line in enumerate(req.script)
    ]


def _build_shots_via_llm(
    req: "JobRequest",
    llm_client: Any,
    model: str = "",
) -> List[Dict[str, Any]]:
    """llm 模式：调用 LLM 生成结构化分镜，解析失败时降级为 mock，并记录 reason_code。"""
    import logging
    from coherent_engine.pipeline.reason_codes import RC
    log = logging.getLogger(__name__)

    system = "你是专业短视频分镜规划师。根据脚本生成结构化分镜计划，输出合法 JSON，不要输出任何额外文字。"
    _inj = (os.environ.get("COHERENT_EXPERIENCE_INJECT") or "").strip()
    if _inj:
        system = system + "\n" + _inj
    user = (
        f"脚本（{len(req.script)} 条）：{json.dumps(req.script, ensure_ascii=False)}\n"
        f"请生成 {len(req.script)} 个镜头的分镜。要求：每个 scene 必须是具体场景描述（如：室内-客厅-白天），不能为空字符串。\n"
        "输出格式："
        '{"shots": [{"shot_id": "shot_001", "duration_s": 3.0, "scene": "室内-客厅-白天", "action": "", '
        '"dialogue": "", "subtitle": "", "camera_framing": "medium", "camera_angle": "eye", '
        '"camera_movement": "static", "must_keep": [], "must_avoid": []}]}'
    )
    try:
        _model = model or getattr(llm_client, "_model", "")
        response_text, prompt_tokens, completion_tokens = llm_client.chat(system=system, user=user, model=_model)
        log.debug("llm raw len=%s head=%r first_ord=%s",
                  len(response_text or ""), (response_text or "")[:120],
                  ord((response_text or "\0")[0]))
        # 1. strip BOM / zero-width chars
        text = (response_text or "").lstrip("\ufeff\u200b\u200c\u200d").strip()
        if not text:
            raise ValueError(RC.DEP_ANTHROPIC_EMPTY)
        # 2. strip markdown code fences
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        # 3. extract JSON substring (handles leading prose / BOM remnants)
        i1 = min([p for p in [text.find("{"), text.find("[")] if p != -1], default=-1)
        if i1 > 0:
            text = text[i1:]
        j1 = max(text.rfind("}"), text.rfind("]"))
        if j1 != -1:
            text = text[:j1 + 1]
        if not text:
            raise ValueError(RC.DEP_ANTHROPIC_NON_JSON)

        data = json.loads(text)
        shots = data.get("shots")
        if not isinstance(shots, list) or not shots:
            log.warning("planner llm: invalid schema, fallback. reason=%s", RC.PLAN_INVALID_SCHEMA)
            return _build_shots_mock(req)
        for i, shot in enumerate(shots):
            if isinstance(shot, dict):
                scene = (shot.get("scene") or "").strip()
                if not scene:
                    shot["scene"] = f"scene_{i+1:03d}"
        log.info("planner llm ok: shots=%d prompt_tokens=%d completion_tokens=%d",
                 len(shots), prompt_tokens, completion_tokens)
        return shots
    except Exception as exc:
        from coherent_engine.pipeline.reason_codes import llm_exc_to_rc
        rc = llm_exc_to_rc(exc)
        log.warning("planner llm fallback reason=%s exc=%s", rc, exc)
        return _build_shots_mock(req)


def write_plan(job_dir: Path, plan: Dict[str, Any]) -> Path:
    job_dir.mkdir(parents=True, exist_ok=True)
    path = job_dir / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
