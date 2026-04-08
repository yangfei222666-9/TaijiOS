"""job_runner unit tests — helpers, frame generation, load_frames, guidance, run_job state machine."""
import json
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from coherent_engine.pipeline.job_runner import (
    _sha1_text,
    _sha256_file,
    _write_json,
    _append_jsonl,
    _generate_frames_4shot,
    _load_frames,
    _build_frames_manifest,
    _guidance_from_failed_checks,
    load_frames_from_dir,
    run_job,
)
from coherent_engine.pipeline.reason_codes import RC


_JOB_REQ = {
    "job_id": "test_job_001",
    "brand_rules_id": "brand.example.v1",
    "character_id": "char.xiaojiu.v1",
    "shot_template_id": "tpl.default",
    "script": ["line1", "line2", "line3", "line4"],
}


# ── Pure helpers ─────────────────────────────────────────────────────

class TestHelpers:
    def test_sha1_text(self):
        h = _sha1_text("hello")
        assert len(h) == 40
        assert _sha1_text("hello") == _sha1_text("hello")
        assert _sha1_text("hello") != _sha1_text("world")

    def test_sha256_file(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"data")
        h = _sha256_file(f)
        assert len(h) == 64
        assert _sha256_file(f) == _sha256_file(f)

    def test_write_json(self, tmp_path):
        p = tmp_path / "sub" / "out.json"
        _write_json(p, {"k": "v"})
        assert p.exists()
        assert json.loads(p.read_text(encoding="utf-8")) == {"k": "v"}

    def test_append_jsonl(self, tmp_path):
        p = tmp_path / "log.jsonl"
        _append_jsonl(p, {"a": 1})
        _append_jsonl(p, {"b": 2})
        lines = p.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["a"] == 1


# ── Frame generation ─────────────────────────────────────────────────

class TestFrameGeneration:
    def test_generate_4_frames(self, tmp_path):
        files = _generate_frames_4shot(req=_JOB_REQ, revision=1, out_dir=tmp_path / "frames")
        assert len(files) == 4
        for f in files:
            assert f.exists()
            arr = np.load(str(f))
            assert arr.shape == (64, 64, 3)

    def test_deterministic_with_same_seed(self, tmp_path):
        f1 = _generate_frames_4shot(req=_JOB_REQ, revision=1, out_dir=tmp_path / "a")
        f2 = _generate_frames_4shot(req=_JOB_REQ, revision=1, out_dir=tmp_path / "b")
        for a, b in zip(f1, f2):
            assert np.array_equal(np.load(str(a)), np.load(str(b)))

    def test_guidance_stable_style(self, tmp_path):
        files = _generate_frames_4shot(
            req=_JOB_REQ, revision=1, out_dir=tmp_path / "frames",
            guidance={"stable_style": True})
        frames = [np.load(str(f)) for f in files]
        # stable_style → all frames share same base color
        # check corners (away from white circle)
        colors = [tuple(f[0, 0].tolist()) for f in frames]
        assert len(set(colors)) == 1

    def test_guidance_stable_motion(self, tmp_path):
        files = _generate_frames_4shot(
            req=_JOB_REQ, revision=1, out_dir=tmp_path / "frames",
            guidance={"stable_motion": True})
        frames = [np.load(str(f)) for f in files]
        # stable_motion → white circle at center (32,32) in all frames
        for f in frames:
            assert f[32, 32].tolist() == [255, 255, 255]

    def test_load_frames(self, tmp_path):
        files = _generate_frames_4shot(req=_JOB_REQ, revision=1, out_dir=tmp_path / "frames")
        frames = _load_frames(files)
        assert len(frames) == 4
        assert all(isinstance(f, np.ndarray) for f in frames)


# ── Frames manifest ──────────────────────────────────────────────────

class TestFramesManifest:
    def test_manifest_structure(self, tmp_path):
        files = _generate_frames_4shot(req=_JOB_REQ, revision=1, out_dir=tmp_path / "frames")
        manifest = _build_frames_manifest(files)
        assert manifest["count"] == 4
        assert len(manifest["frames"]) == 4
        assert all("sha256" in e for e in manifest["frames"])


# ── load_frames_from_dir ─────────────────────────────────────────────

class TestLoadFramesFromDir:
    def test_empty_dir_raises(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        with pytest.raises(ValueError, match=RC.SYS_FRAMES_EMPTY):
            load_frames_from_dir(d)

    def test_too_few_raises(self, tmp_path):
        import cv2
        d = tmp_path / "one"
        d.mkdir()
        img = np.zeros((64, 64, 3), dtype=np.uint8)
        cv2.imwrite(str(d / "frame.jpg"), img)
        with pytest.raises(ValueError, match=RC.SYS_FRAMES_TOOFEW):
            load_frames_from_dir(d)

    def test_valid_dir(self, tmp_path):
        import cv2
        d = tmp_path / "ok"
        d.mkdir()
        for i in range(3):
            img = np.ones((64, 64, 3), dtype=np.uint8) * (i * 50)
            cv2.imwrite(str(d / f"frame_{i:02d}.jpg"), img)
        frames = load_frames_from_dir(d)
        assert len(frames) == 3


# ── Guidance from failed checks ──────────────────────────────────────

class TestGuidance:
    def test_character_fail(self):
        g = _guidance_from_failed_checks(["character_consistency"])
        assert g["stable_character"] is True

    def test_style_fail(self):
        g = _guidance_from_failed_checks(["style_consistency"])
        assert g["stable_style"] is True

    def test_motion_fail(self):
        g = _guidance_from_failed_checks(["shot_continuity"])
        assert g["stable_motion"] is True

    def test_multiple_fails(self):
        g = _guidance_from_failed_checks(["character_consistency", "shot_continuity"])
        assert g["stable_character"] is True
        assert g["stable_motion"] is True

    def test_empty(self):
        assert _guidance_from_failed_checks([]) == {}


# ── run_job state machine (mocked externals) ─────────────────────────

def _mock_echocore():
    """Mock all echocore bridge functions."""
    step_mock = MagicMock()
    step_mock.evidence = []
    run_mock = MagicMock()
    run_mock.add_step.return_value = step_mock
    return {
        "coherent_engine.pipeline.job_runner.create_run": MagicMock(return_value=run_mock),
        "coherent_engine.pipeline.job_runner.save_run": MagicMock(),
        "coherent_engine.pipeline.job_runner.emit_webhook": MagicMock(),
        "coherent_engine.pipeline.job_runner._start_step": MagicMock(),
        "coherent_engine.pipeline.job_runner._complete_step": MagicMock(),
        "coherent_engine.pipeline.job_runner._fail_step": MagicMock(),
        "coherent_engine.pipeline.job_runner.submit_run_as_experience": MagicMock(),
        "coherent_engine.pipeline.job_runner.report_fail_to_echocore": MagicMock(),
    }


def _mock_artifact_and_dlq():
    return {
        "coherent_engine.pipeline.job_runner._artifact_ledger_append": MagicMock(return_value={}),
        "coherent_engine.pipeline.job_runner._enqueue_dlq": MagicMock(),
    }


class TestRunJob:
    def _run(self, tmp_path, monkeypatch, validator_pass=True, max_retries=0):
        monkeypatch.setenv("TAIJI_JOBS_DIR", str(tmp_path / "jobs"))
        monkeypatch.setenv("COHERENT_PLANNER_MODE", "mock")
        monkeypatch.delenv("COHERENT_REASON_CODE_HINT", raising=False)
        monkeypatch.delenv("COHERENT_EXPERIENCE_ID", raising=False)

        mocks = {**_mock_echocore(), **_mock_artifact_and_dlq()}

        def fake_validate(frames, safe_area=None):
            if validator_pass:
                return {"passed": True, "score": 0.95, "failed_checks": [], "checks": {}, "fix_suggestions": []}
            return {"passed": False, "score": 0.5, "failed_checks": ["character_consistency"], "checks": {}, "fix_suggestions": ["fix color"]}

        mocks["coherent_engine.pipeline.job_runner.validate"] = fake_validate

        with patch.dict("os.environ", {}, clear=False):
            with patch.multiple("coherent_engine.pipeline.job_runner", **{k.split(".")[-1]: v for k, v in mocks.items() if k.startswith("coherent_engine.pipeline.job_runner.")}):
                return run_job(task_id="t001", job_request=_JOB_REQ, max_retries=max_retries)

    def test_pass_first_attempt(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, validator_pass=True)
        assert result["passed"] is True
        assert result["revision"] == 1
        deliverable = Path(result["deliverable_dir"])
        assert (deliverable / "provenance.json").exists()

    def test_fail_goes_to_dlq(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, validator_pass=False, max_retries=0)
        assert result["passed"] is False

    def test_retry_then_fail(self, tmp_path, monkeypatch):
        result = self._run(tmp_path, monkeypatch, validator_pass=False, max_retries=2)
        assert result["passed"] is False
        assert result["revision"] == 3  # 3 attempts (0,1,2)

    def test_state_files_written(self, tmp_path, monkeypatch):
        self._run(tmp_path, monkeypatch, validator_pass=True)
        jobs_dir = tmp_path / "jobs" / "test_job_001"
        assert (jobs_dir / "plan.json").exists()
        assert (jobs_dir / "rev_1" / "scores.json").exists()
        assert (jobs_dir / "rev_1" / "state.json").exists()
