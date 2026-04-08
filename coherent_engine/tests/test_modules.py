"""modules/ unit tests — pose, camera, expression, background, validator."""
import numpy as np
import pytest

from coherent_engine.modules.pose import PoseModule
from coherent_engine.modules.camera import CameraModule
from coherent_engine.modules.expression import ExpressionModule
from coherent_engine.modules.background import BackgroundModule
from coherent_engine.modules.validator import VisualValidatorModule


# ── Pose ─────────────────────────────────────────────────────────────

class TestPoseModule:
    @pytest.mark.asyncio
    async def test_numpy_with_circle(self):
        """White circle on black → should detect something."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        import cv2
        cv2.circle(frame, (320, 240), 40, (255, 255, 255), -1)
        mod = PoseModule()
        res = await mod.process(frame)
        assert "root_position" in res
        assert "confidence" in res
        assert res["confidence"] > 0

    @pytest.mark.asyncio
    async def test_empty_frame_fallback(self):
        """All-black frame → fallback centroid or none."""
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        mod = PoseModule()
        res = await mod.process(frame)
        assert "confidence" in res

    @pytest.mark.asyncio
    async def test_dict_input(self, black_frame):
        mod = PoseModule()
        res = await mod.process({"start": black_frame})
        assert "skeleton" in res

    @pytest.mark.asyncio
    async def test_invalid_input(self):
        mod = PoseModule()
        res = await mod.process(None)
        assert res["confidence"] == 0.0 or res.get("detected") is False


# ── Camera ───────────────────────────────────────────────────────────

class TestCameraModule:
    @pytest.mark.asyncio
    async def test_default_focus(self):
        mod = CameraModule()
        res = await mod.process(None, config={}, context={})
        assert res["focus_point"] == {"x": 0, "y": 0, "z": 0}

    @pytest.mark.asyncio
    async def test_follows_pose(self):
        root = {"x": 100, "y": 200, "z": 0}
        ctx = {"pose_module_output": {"root_position": root}}
        mod = CameraModule()
        res = await mod.process(None, config={}, context=ctx)
        assert res["focus_point"] == root

    @pytest.mark.asyncio
    async def test_no_context(self):
        mod = CameraModule()
        res = await mod.process(None)
        assert "camera_matrix" in res


# ── Expression ───────────────────────────────────────────────────────

class TestExpressionModule:
    @pytest.mark.asyncio
    async def test_with_voice_and_pose(self):
        ctx = {
            "voice_module_output": {"duration": 1.0, "status": "success"},
            "pose_module_output": {"confidence": 0.9},
        }
        mod = ExpressionModule()
        res = await mod.process(None, config={}, context=ctx)
        assert res["sync_status"] == "aligned"
        assert len(res["expression_sequence"]) == 30  # 1.0s * 30fps
        assert res["base_intensity"] == pytest.approx(0.9)

    @pytest.mark.asyncio
    async def test_fallback_no_voice(self):
        mod = ExpressionModule()
        res = await mod.process(None, config={}, context={})
        assert res["sync_status"] == "fallback"
        assert len(res["expression_sequence"]) == 30

    @pytest.mark.asyncio
    async def test_zero_duration(self):
        ctx = {
            "voice_module_output": {"duration": 0, "status": "success"},
            "pose_module_output": {"confidence": 1.0},
        }
        mod = ExpressionModule()
        res = await mod.process(None, config={}, context=ctx)
        # zero duration → aligned but empty sequence
        assert "sync_status" in res


# ── Background ───────────────────────────────────────────────────────

class TestBackgroundModule:
    @pytest.mark.asyncio
    async def test_blur(self, black_frame, tmp_path):
        out = str(tmp_path / "bg.jpg")
        mod = BackgroundModule()
        res = await mod.process(black_frame, config={"type": "blur", "output_path": out}, context={})
        assert res["style_applied"] == "blur"
        assert res["status"] == "success"

    @pytest.mark.asyncio
    async def test_cyberpunk(self, black_frame, tmp_path):
        out = str(tmp_path / "bg.jpg")
        mod = BackgroundModule()
        res = await mod.process(black_frame, config={"type": "cyberpunk", "output_path": out}, context={})
        assert res["style_applied"] == "cyberpunk"

    @pytest.mark.asyncio
    async def test_invalid_input_creates_black(self, tmp_path):
        out = str(tmp_path / "bg.jpg")
        mod = BackgroundModule()
        res = await mod.process(None, config={"type": "blur", "output_path": out}, context={})
        assert res["status"] == "success"


# ── Validator ────────────────────────────────────────────────────────

class TestVisualValidator:
    @pytest.mark.asyncio
    async def test_identical_frames_pass(self):
        frame = np.ones((100, 100, 3), dtype=np.uint8) * 128
        mod = VisualValidatorModule()
        res = await mod.process({"frames": [frame, frame, frame]})
        assert res["passed"] is True
        assert res["score"] >= 0.85

    @pytest.mark.asyncio
    async def test_empty_frames_pass(self):
        mod = VisualValidatorModule()
        res = await mod.process({"frames": []})
        assert res["passed"] is True

    @pytest.mark.asyncio
    async def test_single_frame(self):
        frame = np.ones((100, 100, 3), dtype=np.uint8) * 100
        mod = VisualValidatorModule()
        res = await mod.process({"frames": [frame]})
        assert res["passed"] is True

    @pytest.mark.asyncio
    async def test_wildly_different_frames_may_fail(self):
        f1 = np.zeros((100, 100, 3), dtype=np.uint8)
        f2 = np.ones((100, 100, 3), dtype=np.uint8) * 255
        mod = VisualValidatorModule()
        res = await mod.process({"frames": [f1, f2], "reference_frame": f1})
        # at least some checks should flag differences
        assert "checks" in res
        assert "score" in res
