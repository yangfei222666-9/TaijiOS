"""pipeline/ unit tests — reason_codes, prompt_builder, planner."""
import json
import pytest
from pathlib import Path

from coherent_engine.pipeline.reason_codes import RC, failed_checks_to_rc, llm_exc_to_rc
from coherent_engine.pipeline.prompt_builder import build_prompt, build_prompts
from coherent_engine.pipeline.planner import normalize_job_request, build_plan, write_plan


# ── ReasonCodes ──────────────────────────────────────────────────────

class TestReasonCodes:
    def test_failed_checks_character(self):
        assert failed_checks_to_rc(["character_consistency"]) == RC.VAL_CHARACTER

    def test_failed_checks_first_match(self):
        assert failed_checks_to_rc(["shot_continuity", "style_consistency"]) == RC.VAL_MOTION

    def test_failed_checks_empty_fallback(self):
        assert failed_checks_to_rc([]) == RC.VAL_SCORE_LOW

    def test_failed_checks_unknown_fallback(self):
        assert failed_checks_to_rc(["unknown_check"]) == RC.VAL_SCORE_LOW

    def test_llm_exc_no_key(self):
        assert llm_exc_to_rc(ValueError("no_api_key")) == RC.DEP_ANTHROPIC_NO_KEY

    def test_llm_exc_rate_limit(self):
        assert llm_exc_to_rc(Exception("rate limit exceeded")) == RC.DEP_ANTHROPIC_RATE_LIMIT

    def test_llm_exc_timeout(self):
        assert llm_exc_to_rc(TimeoutError("timed out")) == RC.DEP_ANTHROPIC_TIMEOUT

    def test_llm_exc_json_parse(self):
        assert llm_exc_to_rc(ValueError("json decode error")) == RC.PLAN_LLM_PARSE_ERROR

    def test_llm_exc_generic_http(self):
        assert llm_exc_to_rc(Exception("something broke")) == RC.DEP_ANTHROPIC_HTTP


# ── PromptBuilder ────────────────────────────────────────────────────

class TestPromptBuilder:
    def test_minimal_shot(self):
        res = build_prompt({"shot_id": "s001"})
        assert res["shot_id"] == "s001"
        assert "positive_prompt" in res
        assert "negative_prompt" in res
        assert "prompt_hash" in res

    def test_scene_in_positive(self):
        res = build_prompt({"scene": "室内-客厅"})
        assert "室内-客厅" in res["positive_prompt"]

    def test_scene_tags_mapped(self):
        res = build_prompt({"scene_tags": ["室内", "白天"]})
        assert "indoor" in res["positive_prompt"]
        assert "daytime" in res["positive_prompt"]

    def test_must_keep_and_avoid(self):
        res = build_prompt({"must_keep": ["red dress"], "must_avoid": ["watermark"]})
        assert "red dress" in res["positive_prompt"]
        assert "watermark" in res["negative_prompt"]

    def test_defaults(self):
        res = build_prompt({})
        assert res["cfg"] == 7.0
        assert res["steps"] == 20
        assert res["seed"] == -1

    def test_build_prompts_batch(self):
        shots = [{"shot_id": f"s{i}"} for i in range(3)]
        results = build_prompts(shots)
        assert len(results) == 3
        assert all(r["prompt_hash"] for r in results)

    def test_deterministic_hash(self):
        a = build_prompt({"scene": "test"})
        b = build_prompt({"scene": "test"})
        assert a["prompt_hash"] == b["prompt_hash"]


# ── Planner ──────────────────────────────────────────────────────────

_VALID_RAW = {
    "job_id": "j001",
    "brand_rules_id": "brand.example.v1",
    "character_id": "char.xiaojiu.v1",
    "shot_template_id": "tpl.default",
    "script": ["你好世界", "第二句台词"],
}


class TestNormalizeJobRequest:
    def test_valid(self):
        req = normalize_job_request(_VALID_RAW)
        assert req.job_id == "j001"
        assert len(req.script) == 2

    def test_missing_job_id(self):
        raw = {**_VALID_RAW, "job_id": ""}
        with pytest.raises(ValueError, match="job_id"):
            normalize_job_request(raw)

    def test_empty_script(self):
        raw = {**_VALID_RAW, "script": []}
        with pytest.raises(ValueError, match="script"):
            normalize_job_request(raw)

    def test_script_with_blank_entry(self):
        raw = {**_VALID_RAW, "script": ["ok", ""]}
        with pytest.raises(ValueError, match="script\\[1\\]"):
            normalize_job_request(raw)

    def test_negative_shots_per_video(self):
        raw = {**_VALID_RAW, "shots_per_video": -1}
        with pytest.raises(ValueError, match="shots_per_video"):
            normalize_job_request(raw)

    def test_defaults(self):
        req = normalize_job_request(_VALID_RAW)
        assert req.language == "zh-CN"
        assert req.shots_per_video == 4
        assert req.target_duration_s is None


class TestBuildPlan:
    def test_mock_mode(self):
        plan = build_plan(_VALID_RAW, planner_mode="mock")
        assert plan["schema_version"] == "1.0"
        assert len(plan["shots"]) == 2
        assert plan["meta"]["planner_mode"] == "mock"

    def test_llm_fallback_without_client(self):
        plan = build_plan(_VALID_RAW, planner_mode="llm", llm_client=None)
        assert plan["meta"]["planner_mode"] == "mock"  # fallback

    def test_plan_has_required_keys(self):
        plan = build_plan(_VALID_RAW)
        for key in ["job_id", "brand_rules", "character", "shots", "constraints", "meta"]:
            assert key in plan

    def test_shots_match_script_count(self):
        plan = build_plan(_VALID_RAW)
        assert len(plan["shots"]) == len(_VALID_RAW["script"])


class TestWritePlan:
    def test_write_and_read(self, tmp_path):
        plan = build_plan(_VALID_RAW)
        path = write_plan(tmp_path / "job_test", plan)
        assert path.exists()
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["job_id"] == "j001"
