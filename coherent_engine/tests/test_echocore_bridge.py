"""_echocore_bridge unit tests — graceful degradation, null objects, step lifecycle, save, webhook."""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from coherent_engine.pipeline._echocore_bridge import (
    _NullRun,
    _NullStep,
    _start_step,
    _complete_step,
    _fail_step,
    create_run,
    save_run,
    emit_webhook,
    submit_run_as_experience,
    report_fail_to_echocore,
    _run_trace_to_experience_payload,
    _ECHOCORE_AVAILABLE,
)


# ── NullRun / NullStep (graceful degradation) ────────────────────────

class TestNullObjects:
    def test_null_run_methods_dont_crash(self):
        r = _NullRun()
        r.ensure_ids()
        r.start()
        step = r.add_step("test")
        assert isinstance(step, _NullStep)
        r.complete(output={"ok": True})
        r.fail(error={"err": "x"})
        assert r.to_dict() == {}
        assert r.run_id == ""

    def test_null_step_has_empty_id(self):
        s = _NullStep()
        assert s.step_id == ""


# ── Step lifecycle (with NullStep — no EchoCore) ─────────────────────

class TestStepLifecycleNull:
    def test_start_step_null(self):
        s = _NullStep()
        _start_step(s)  # should not crash

    def test_complete_step_null(self):
        s = _NullStep()
        _complete_step(s, output={"done": True})  # should not crash

    def test_fail_step_null(self):
        s = _NullStep()
        _fail_step(s, error={"err": "x"})  # should not crash


# ── create_run without EchoCore ──────────────────────────────────────

class TestCreateRun:
    def test_returns_null_run_when_unavailable(self):
        with patch("coherent_engine.pipeline._echocore_bridge._ECHOCORE_AVAILABLE", False):
            r = create_run(task_id="t1", title="test")
            assert isinstance(r, _NullRun)


# ── save_run ─────────────────────────────────────────────────────────

class TestSaveRun:
    def test_save_null_run_noop(self, tmp_path):
        r = _NullRun()
        save_run(r, tmp_path / "job")
        assert not (tmp_path / "job" / "run_trace.json").exists()

    def test_save_real_run_dict(self, tmp_path):
        r = MagicMock()
        r.to_dict.return_value = {"run_id": "r1", "status": "completed"}
        with patch("coherent_engine.pipeline._echocore_bridge._ECHOCORE_AVAILABLE", True):
            save_run(r, tmp_path / "job")
        trace = tmp_path / "job" / "run_trace.json"
        assert trace.exists()
        data = json.loads(trace.read_text(encoding="utf-8"))
        assert data["run_id"] == "r1"

    def test_save_empty_dict_noop(self, tmp_path):
        r = MagicMock()
        r.to_dict.return_value = {}
        save_run(r, tmp_path / "job")
        assert not (tmp_path / "job" / "run_trace.json").exists()


# ── emit_webhook ─────────────────────────────────────────────────────

class TestEmitWebhook:
    def test_no_url_returns_none(self, monkeypatch):
        monkeypatch.delenv("ECHOCORE_WEBHOOK_URL", raising=False)
        r = _NullRun()
        assert emit_webhook(r, "job.done") is None

    def test_unavailable_returns_none(self, monkeypatch):
        monkeypatch.setenv("ECHOCORE_WEBHOOK_URL", "http://localhost:9999")
        with patch("coherent_engine.pipeline._echocore_bridge._ECHOCORE_AVAILABLE", False):
            assert emit_webhook(_NullRun(), "job.done") is None


# ── submit_run_as_experience ─────────────────────────────────────────

class TestSubmitExperience:
    def test_unavailable_returns_none(self):
        with patch("coherent_engine.pipeline._echocore_bridge._ECHOCORE_AVAILABLE", False):
            assert submit_run_as_experience(_NullRun(), job_id="j1") is None

    def test_empty_run_dict_returns_none(self):
        r = MagicMock()
        r.to_dict.return_value = {}
        with patch("coherent_engine.pipeline._echocore_bridge._ECHOCORE_AVAILABLE", True):
            assert submit_run_as_experience(r, job_id="j1") is None


# ── report_fail_to_echocore ──────────────────────────────────────────

class TestReportFail:
    def test_unavailable_noop(self):
        with patch("coherent_engine.pipeline._echocore_bridge._ECHOCORE_AVAILABLE", False):
            report_fail_to_echocore(_NullRun(), job_id="j1", failed_checks=["x"], score=0.5, attempts=3)
            # should not crash


# ── _run_trace_to_experience_payload ─────────────────────────────────

class TestPayloadMapping:
    def test_passed_run(self):
        run = MagicMock()
        run.run_id = "r1"
        run.status = MagicMock()
        run.status.value = "completed"
        run.to_dict.return_value = {"run_id": "r1"}

        payload = _run_trace_to_experience_payload(
            run=run, job_id="j1", score=0.92, failed_checks=[], rev_count=1)
        assert "coherent_job/j1/r1" in payload["title"]
        assert "job.done" in payload["tags"]
        assert payload["metadata"]["custom_fields"]["passed"] is True
        assert payload["metadata"]["custom_fields"]["score"] == 0.92

    def test_failed_run_with_checks(self):
        run = MagicMock()
        run.run_id = "r2"
        run.status = MagicMock()
        run.status.value = "failed"
        run.to_dict.return_value = {"run_id": "r2"}

        payload = _run_trace_to_experience_payload(
            run=run, job_id="j2", score=0.4, failed_checks=["character_consistency"], rev_count=3)
        assert "job.dlq" in payload["tags"]
        assert "fail:character_consistency" in payload["tags"]
        assert payload["metadata"]["custom_fields"]["passed"] is False
        assert payload["metadata"]["custom_fields"]["rev_count"] == 3

    def test_no_echocore_status(self):
        run = MagicMock(spec=[])  # no status attribute
        run.run_id = "r3"
        run.to_dict = MagicMock(return_value={"run_id": "r3"})

        payload = _run_trace_to_experience_payload(
            run=run, job_id="j3", score=0.8, failed_checks=[], rev_count=1)
        assert payload["metadata"]["custom_fields"]["passed"] is False  # no status → not passed
