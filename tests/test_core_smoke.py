import pytest
import json
import sys
import types


def test_event_bus_fallback_store_round_trip(tmp_path, monkeypatch):
    from aios.core import event_bus as event_bus_module
    from aios.core.event import Event

    store = event_bus_module.EventStoreAdapter(tmp_path / "events")
    monkeypatch.setattr(event_bus_module, "_fallback_store", store, raising=False)

    bus = event_bus_module.EventBus()
    seen = []
    bus.subscribe("smoke.*", seen.append)

    event = Event.create("smoke.created", "test", {"ok": True})
    bus.emit(event)

    assert seen == [event]
    loaded = bus.load_events("smoke.*")
    assert len(loaded) == 1
    assert loaded[0].type == "smoke.created"
    assert loaded[0].payload == {"ok": True}


def test_agent_system_package_imports_without_legacy_dependencies():
    import aios.agent_system as agent_system

    assert agent_system.TaskType.CODING.value == "coding"
    with pytest.raises(RuntimeError, match="legacy dependencies"):
        agent_system.AgentSystem()


def test_agent_system_tail_lines_helper(tmp_path):
    import aios.agent_system as agent_system

    path = tmp_path / "events.jsonl"
    path.write_text("one\ntwo\nthree\n", encoding="utf-8")

    assert agent_system._tail_lines(path, 2) == ["two\n", "three\n"]
    assert agent_system._tail_lines(path, 0) == []


def test_task_executor_memory_defaults_are_defined():
    from aios.agent_system import task_executor

    assert task_executor.MEMORY_TIMEOUT_MS > 0
    assert task_executor.MEMORY_MAX_HINTS > 0
    assert task_executor.MEMORY_MAX_CHARS > 0

    context = task_executor.build_memory_context("missing memory backend", "")
    assert context["degraded"] is True
    assert context["memory_hints"] == []


def test_task_executor_tracks_skill_memory_when_adapter_exists(tmp_path, monkeypatch):
    from aios.agent_system import task_executor

    calls = []

    class FakeSkillMemory:
        def track_execution(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setitem(sys.modules, "skill_memory", types.SimpleNamespace(skill_memory=FakeSkillMemory()))
    monkeypatch.setattr(task_executor, "EXEC_LOG", tmp_path / "executions.jsonl")

    task_executor.write_execution_record(
        task_id="task-1",
        agent_id="demo-skill-dispatcher",
        status="completed",
        start_time="2026-05-11T00:00:00Z",
        end_time="2026-05-11T00:00:01Z",
        duration_ms=12,
        result={"command": "run-demo"},
        metadata={"input_params": {"x": 1}},
    )

    assert calls[0]["skill_id"] == "demo-skill"
    assert calls[0]["skill_name"] == "Demo Skill"


def test_coherent_aligner_imports():
    from coherent_engine.core.aligner import FirstLastAligner

    assert FirstLastAligner is not None


def test_reactor_imports_with_decision_log_fallback():
    from aios.core import reactor

    assert reactor.PYTHON
    decision_id = reactor.log_decision(
        context="test",
        options=["skip"],
        chosen="skip",
        reason="fallback smoke",
        confidence=1.0,
    )
    assert isinstance(decision_id, str)


def test_coherent_orchestrator_imports_without_optional_modules():
    from coherent_engine.core.orchestrator import BaseModule, ModuleOrchestrator
    from coherent_engine.core.executor import PipelineExecutor

    assert BaseModule is not None
    assert ModuleOrchestrator is not None
    assert PipelineExecutor is not None


def test_agent_system_auxiliary_modules_import_without_legacy_adapters(tmp_path, monkeypatch):
    from aios.agent_system import health_check, task_router, unified_registry

    assert task_router.get_agent_status({"status": "standby"}) == "standby"
    router = task_router.TaskRouter.__new__(task_router.TaskRouter)
    assert router._identify_task_type("请修复这个发布问题")[0] == "fix"

    monkeypatch.setenv("TAIJIOS_AGENT_SYSTEM_DIR", str(tmp_path))
    assert health_check._agent_system_base_path() == tmp_path
    assert health_check.main() == 100

    monkeypatch.setattr(unified_registry, "SKILLS_DIR", tmp_path / "missing")
    assert unified_registry.scan_skills() == {}


def test_gateway_cli_parses_args_without_starting_default_server(monkeypatch):
    from aios.gateway import __main__ as gateway_main

    captured = {}

    def fake_run(app, **kwargs):
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(gateway_main.uvicorn, "run", fake_run)

    gateway_main.main(["--host", "0.0.0.0", "--port", "9300", "--log-level", "warning"])

    assert captured == {
        "app": "aios.gateway.app:app",
        "host": "0.0.0.0",
        "port": 9300,
        "log_level": "warning",
    }


def test_quickstart_output_defaults_to_ignored_runtime_dir():
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "examples" / "quickstart_minimal.py"
    spec = importlib.util.spec_from_file_location("quickstart_minimal_smoke", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.OUTPUT_DIR == Path.cwd() / "data" / "quickstart_output"


def test_adaptive_threshold_persists_to_instance_config_file(tmp_path):
    from self_improving_loop.self_improving_loop.threshold import AdaptiveThreshold

    threshold = AdaptiveThreshold(data_dir=str(tmp_path))
    threshold.set_manual_threshold("agent-custom", failure_threshold=7)

    reloaded = AdaptiveThreshold(data_dir=str(tmp_path))
    assert reloaded.get_threshold("agent-custom", [])[0] == 7


def test_worker_max_cycles_exits_without_sleeping_or_touching_package_data(tmp_path, monkeypatch):
    from worker import __main__ as worker_main

    sleep_calls = []
    monkeypatch.setattr(worker_main.time, "sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr(worker_main, "_SHUTDOWN", True)

    worker_main.main([
        "--max-cycles", "1",
        "--interval", "999",
        "--dry-run",
        "--skip-learning",
        "--skip-jobs",
        "--data-dir", str(tmp_path),
    ])

    status = json.loads((tmp_path / "worker_status.json").read_text(encoding="utf-8"))
    assert status["current_mode"] == "stopped"
    assert status["cycles_completed"] == 1
    assert sleep_calls == []
