from aios.core.event_bus import EventBus, EventStoreAdapter
from aios.gui_agent import (
    ConfirmationStore,
    DryRunOperator,
    GUIAgent,
    InMemoryConfirmationStore,
    ModelResult,
    PolicyEngine,
)
from aios.gui_agent.redaction import contains_secret


class OneShotModel:
    def invoke(self, instruction, screenshot, history, previous_response_id=None):
        return ModelResult(
            prediction="Thought: click target\nAction: click(start_box='[1,1,1,1]')"
        )


def _fake_token_assignment() -> str:
    return "tok" + "en=" + "abcdef" + "ghi"


def test_gui_agent_emits_confirmation_events(tmp_path, monkeypatch):
    from aios.core import event_bus as event_bus_module

    store = EventStoreAdapter(tmp_path / "events")
    monkeypatch.setattr(event_bus_module, "_fallback_store", store, raising=False)

    bus = EventBus()
    seen = []
    bus.subscribe("gui_agent.*", seen.append)

    agent = GUIAgent(
        operator=DryRunOperator(),
        model=OneShotModel(),
        policy=PolicyEngine(shadow_mode=True),
        confirmation_store=InMemoryConfirmationStore(),
        event_bus=bus,
    )

    run = agent.run("click target")
    agent.approve_confirmation(run.confirmation_id, actor="tester")

    event_types = [event.type for event in seen]
    assert "gui_agent.awaiting_confirmation" in event_types
    assert "gui_agent.confirmation_executed" in event_types

    loaded = bus.load_events("gui_agent.*")
    assert len(loaded) >= 2
    assert any(
        event.payload.get("confirmation_id") == run.confirmation_id
        for event in loaded
    )


def test_gui_agent_redacts_secret_instruction_in_events(tmp_path, monkeypatch):
    from aios.core import event_bus as event_bus_module

    store = EventStoreAdapter(tmp_path / "events")
    monkeypatch.setattr(event_bus_module, "_fallback_store", store, raising=False)

    bus = EventBus()
    agent = GUIAgent(
        operator=DryRunOperator(),
        model=OneShotModel(),
        policy=PolicyEngine(shadow_mode=True),
        confirmation_store=InMemoryConfirmationStore(),
        event_bus=bus,
    )

    agent.run(f"click target with {_fake_token_assignment()}")
    loaded = bus.load_events("gui_agent.*")
    payloads = [event.payload for event in loaded]

    assert contains_secret(payloads) is False
    assert "abcdefghi" not in str(payloads)
    assert any("[REDACTED_SECRET]" in str(payload) for payload in payloads)


def test_confirmation_store_is_exported():
    assert ConfirmationStore is not None
