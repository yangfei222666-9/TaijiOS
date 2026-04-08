"""core/ unit tests — cache, aligner, tweener, orchestrator, executor."""
import asyncio
import numpy as np
import pytest
from typing import Any, Dict

from coherent_engine.core.cache import LockPointCache
from coherent_engine.core.aligner import FirstLastAligner
from coherent_engine.core.tweener import AsyncTweener
from coherent_engine.core.orchestrator import ModuleOrchestrator
from coherent_engine.core.executor import PipelineExecutor
from coherent_engine.modules.base import BaseModule


# ── Cache ────────────────────────────────────────────────────────────

class TestLockPointCache:
    @pytest.mark.asyncio
    async def test_local_fallback_set_get(self, local_cache):
        await local_cache.set("k1", {"a": 1})
        assert await local_cache.get("k1") == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_missing_key(self, local_cache):
        assert await local_cache.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_overwrite(self, local_cache):
        await local_cache.set("k", {"v": 1})
        await local_cache.set("k", {"v": 2})
        assert (await local_cache.get("k"))["v"] == 2


# ── Aligner ──────────────────────────────────────────────────────────

class TestFirstLastAligner:
    @pytest.mark.asyncio
    async def test_returns_lock_points(self, local_cache):
        aligner = FirstLastAligner(local_cache)
        lp = await aligner.align("frame_a", "frame_b")
        assert "left_eye" in lp
        assert "start" in lp["left_eye"] and "end" in lp["left_eye"]

    @pytest.mark.asyncio
    async def test_cache_hit(self, local_cache):
        aligner = FirstLastAligner(local_cache)
        lp1 = await aligner.align("fa", "fb")
        lp2 = await aligner.align("fa", "fb")
        assert lp1 == lp2

    @pytest.mark.asyncio
    async def test_numpy_input(self, local_cache, black_frame, white_frame):
        aligner = FirstLastAligner(local_cache)
        lp = await aligner.align(black_frame, white_frame)
        assert len(lp) == 5

    def test_post_align_passthrough(self, local_cache):
        aligner = FirstLastAligner(local_cache)
        data = [1, 2, 3]
        assert aligner.post_align(data, {}) == data


# ── Tweener ──────────────────────────────────────────────────────────

class TestAsyncTweener:
    @pytest.mark.asyncio
    async def test_scalar_linear(self):
        tw = AsyncTweener()
        seq = await tw.tween(0.0, 10.0, 5)
        assert len(seq) == 5
        assert seq[0] == pytest.approx(0.0)
        assert seq[-1] == pytest.approx(10.0)
        assert seq[2] == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_single_frame(self):
        tw = AsyncTweener()
        seq = await tw.tween(5, 100, 1)
        assert seq == [5]

    @pytest.mark.asyncio
    async def test_list_interpolation(self):
        tw = AsyncTweener()
        seq = await tw.tween([0, 0], [10, 20], 3)
        assert len(seq) == 3
        assert seq[1] == [pytest.approx(5.0), pytest.approx(10.0)]

    @pytest.mark.asyncio
    async def test_dict_interpolation(self):
        tw = AsyncTweener()
        seq = await tw.tween({"x": 0}, {"x": 10}, 3)
        assert seq[1]["x"] == pytest.approx(5.0)

    @pytest.mark.asyncio
    async def test_unsupported_type_returns_start(self):
        tw = AsyncTweener()
        seq = await tw.tween("hello", "world", 3)
        assert all(s == "hello" for s in seq)

    @pytest.mark.asyncio
    async def test_custom_interpolator(self):
        tw = AsyncTweener()
        # always return end value
        seq = await tw.tween(0, 10, 3, interpolator=lambda a, b, t: b)
        assert all(s == 10 for s in seq)


# ── Orchestrator ─────────────────────────────────────────────────────

class _StubModule(BaseModule):
    def __init__(self, name, mtype="stub"):
        self._name = name
        self._mtype = mtype
        self.called_with_context = None

    @property
    def name(self):
        return self._name

    @property
    def module_type(self):
        return self._mtype

    async def process(self, input_data, config=None, context=None):
        self.called_with_context = context
        return {f"{self._name}_ok": True}


class TestModuleOrchestrator:
    @pytest.mark.asyncio
    async def test_single_module(self):
        orch = ModuleOrchestrator()
        m = _StubModule("mod_a")
        orch.register_module(m)
        res = await orch.execute_workflow("input", {})
        assert res["mod_a"] == {"mod_a_ok": True}

    @pytest.mark.asyncio
    async def test_dependency_order(self):
        orch = ModuleOrchestrator()
        a = _StubModule("a")
        b = _StubModule("b")
        orch.register_module(a)
        orch.register_module(b, depends_on=["a"])
        res = await orch.execute_workflow("input", {})
        # b should see a's output in context
        assert "a_output" in b.called_with_context

    @pytest.mark.asyncio
    async def test_circular_dependency_raises(self):
        orch = ModuleOrchestrator()
        a = _StubModule("a")
        b = _StubModule("b")
        orch.register_module(a, depends_on=["b"])
        orch.register_module(b, depends_on=["a"])
        with pytest.raises(ValueError, match="Circular"):
            await orch.execute_workflow("input", {})

    @pytest.mark.asyncio
    async def test_missing_dep_skipped(self):
        orch = ModuleOrchestrator()
        a = _StubModule("a")
        orch.register_module(a, depends_on=["nonexistent"])
        # nonexistent is in deps but not registered — visit() will be called
        # but it won't be in _modules so it gets skipped in execute_workflow
        res = await orch.execute_workflow("input", {})
        assert "a" in res


# ── Executor ─────────────────────────────────────────────────────────

class TestPipelineExecutor:
    @pytest.mark.asyncio
    async def test_full_pipeline(self, local_cache):
        aligner = FirstLastAligner(local_cache)
        orch = ModuleOrchestrator()
        orch.register_module(_StubModule("stub"))
        tw = AsyncTweener()
        executor = PipelineExecutor(aligner, orch, tw)

        result = await executor.run("start", "end", {"frames": 3})
        assert "lock_points" in result
        assert "module_results" in result
        assert "render_sequence" in result
        assert "stub" in result["module_results"]

    @pytest.mark.asyncio
    async def test_default_frame_count(self, local_cache):
        aligner = FirstLastAligner(local_cache)
        orch = ModuleOrchestrator()
        orch.register_module(_StubModule("s"))
        tw = AsyncTweener()
        executor = PipelineExecutor(aligner, orch, tw)

        result = await executor.run("a", "b", {})
        seq = result["render_sequence"].get("s_sequence", [])
        assert len(seq) == 30  # default
