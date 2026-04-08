"""
coherent_engine 统一 reason_code 字典。
格式: DOMAIN.CATEGORY.SUBCODE
"""


class RC:
    # 成功
    OK = "OK.OK.OK"

    # validator 失败
    VAL_CHARACTER  = "coherent.validator.character_consistency"
    VAL_STYLE      = "coherent.validator.style_consistency"
    VAL_MOTION     = "coherent.validator.shot_continuity"
    VAL_SUBTITLE   = "coherent.validator.subtitle_safety"
    VAL_SCORE_LOW  = "coherent.validator.score_below_threshold"

    # 真实帧输入
    SYS_FRAMES_EMPTY   = "sys.frames.empty_dir"
    SYS_FRAMES_TOOFEW  = "sys.frames.too_few"
    SYS_FRAMES_CORRUPT = "sys.frames.corrupt_or_unreadable"

    # 系统
    SYS_TIMEOUT    = "sys.execution.timeout"
    SYS_DLQ        = "sys.queue.dead_letter"
    SYS_IDEMPOTENT = "sys.dedup.noop_idempotent"
    SYS_MAX_RETRY  = "sys.execution.max_retries_exceeded"
    SYS_ENCODING   = "sys.encoding.codec_error"

    # 依赖 - EchoCore / Webhook / TaskAPI
    DEP_ECHOCORE   = "dep.echocore.submit_failed"
    DEP_WEBHOOK    = "dep.webhook.delivery_failed"
    DEP_TASKAPI    = "dep.taskapi.delivery_failed"

    # 依赖 - Anthropic LLM
    DEP_ANTHROPIC_HTTP        = "dep.anthropic.http_error"
    DEP_ANTHROPIC_TIMEOUT     = "dep.anthropic.timeout"
    DEP_ANTHROPIC_NO_KEY      = "dep.anthropic.no_api_key"
    DEP_ANTHROPIC_INVALID_KEY = "dep.anthropic.invalid_api_key"
    DEP_ANTHROPIC_RATE_LIMIT  = "dep.anthropic.rate_limit"
    DEP_ANTHROPIC_CTX_LEN     = "dep.anthropic.context_length_exceeded"
    DEP_ANTHROPIC_EMPTY       = "dep.anthropic.empty_response"
    DEP_ANTHROPIC_NON_JSON    = "dep.anthropic.non_json_response"
    SYS_ENCODING_BOM          = "sys.encoding.bom_or_zwsp"

    # planner
    PLAN_INVALID_SCHEMA   = "plan.invalid.schema"
    PLAN_LLM_FALLBACK     = "plan.llm.fallback_to_mock"
    PLAN_LLM_EMPTY        = "plan.llm.empty_response"
    PLAN_LLM_PARSE_ERROR  = "plan.llm.parse_error"


# failed_checks[] 字符串 → RC 映射
FAILED_CHECK_TO_RC: dict = {
    "character_consistency": RC.VAL_CHARACTER,
    "style_consistency":     RC.VAL_STYLE,
    "shot_continuity":       RC.VAL_MOTION,
    "subtitle_safety":       RC.VAL_SUBTITLE,
}


def failed_checks_to_rc(failed_checks: list) -> str:
    """返回第一个匹配的 reason_code，或 VAL_SCORE_LOW。"""
    for c in failed_checks:
        if c in FAILED_CHECK_TO_RC:
            return FAILED_CHECK_TO_RC[c]
    return RC.VAL_SCORE_LOW


def llm_exc_to_rc(exc: Exception) -> str:
    """
    Map an LLM-call exception to a structured reason_code.
    Single source of truth — used by planner and any future LLM callers.
    """
    s = str(exc).lower()
    t = type(exc).__name__.lower()
    if "no_api_key" in s or "api_key" in s and "invalid" not in s:
        return RC.DEP_ANTHROPIC_NO_KEY
    if "invalid" in s and "key" in s:
        return RC.DEP_ANTHROPIC_INVALID_KEY
    if "rate" in s and "limit" in s:
        return RC.DEP_ANTHROPIC_RATE_LIMIT
    if "timeout" in s or "timed out" in s or "timeout" in t:
        return RC.DEP_ANTHROPIC_TIMEOUT
    if "context" in s and ("length" in s or "window" in s or "token" in s):
        return RC.DEP_ANTHROPIC_CTX_LEN
    if "codec" in s or "encode" in s or "ascii" in s or "utf" in s:
        return RC.SYS_ENCODING
    if "json" in s or "parse" in s or "decode" in s:
        return RC.PLAN_LLM_PARSE_ERROR
    return RC.DEP_ANTHROPIC_HTTP
