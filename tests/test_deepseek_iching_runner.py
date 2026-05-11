import json
from pathlib import Path

from aios.iching.deepseek_runner import (
    DeepSeekChatClient,
    DeepSeekIchingRunner,
    YIJING_HEXAGRAMS,
    default_output_dir,
    main,
    validate_iching_run,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeDeepSeekClient:
    def __init__(self):
        self.calls = []

    def complete(self, *, model, messages, temperature, max_tokens):
        self.calls.append({
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        user = messages[-1]["content"]
        return {
            "model": model,
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "core_meaning": "稳住节奏",
                                "modern_reading": user[:40],
                                "risks": ["急躁", "越界", "失衡"],
                                "actions": ["审势", "小试", "复盘"],
                                "taijios_agent_note": "先审计再执行。",
                                "disclaimer": "不作为占卜、投资、医疗或法律建议",
                            },
                            ensure_ascii=False,
                        )
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 43,
                "total_tokens": 123,
                "prompt_cache_hit_tokens": 20,
                "prompt_cache_miss_tokens": 60,
            },
        }


class FlakyDeepSeekClient(FakeDeepSeekClient):
    def __init__(self):
        super().__init__()
        self.failures_left = 1

    def complete(self, *, model, messages, temperature, max_tokens):
        if self.failures_left:
            self.failures_left -= 1
            raise RuntimeError("temporary failure")
        return super().complete(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )


def test_deepseek_iching_dry_run_writes_64_artifacts(tmp_path):
    result = DeepSeekIchingRunner(output_dir=tmp_path / "run").run()

    assert result.ok is True
    assert result.summary["live"] is False
    assert result.summary["hexagram_count"] == 64
    assert result.summary["completed_count"] == 64
    assert result.summary_path.exists()
    assert result.event_flow_path.exists()
    assert result.report_path.exists()

    validation = validate_iching_run(result.output_dir)
    assert validation.ok is True
    assert validation.errors == []


def test_deepseek_iching_default_output_dir_is_unique():
    first = default_output_dir()
    second = default_output_dir()

    assert first != second
    assert first.parent == second.parent
    assert first.name.startswith("deepseek_iching_64_")
    assert second.name.startswith("deepseek_iching_64_")


def test_deepseek_iching_live_uses_client_for_each_hexagram(tmp_path):
    client = FakeDeepSeekClient()
    result = DeepSeekIchingRunner(
        output_dir=tmp_path / "run",
        live=True,
        client=client,
    ).run()

    assert result.ok is True
    assert len(client.calls) == len(YIJING_HEXAGRAMS)
    assert result.summary["results"][0]["provider"] == "deepseek"
    assert result.summary["results"][0]["tokens_used"] == 123
    assert result.summary["usage"]["total_tokens"] == 64 * 123
    assert result.summary["usage"]["prompt_tokens"] == 64 * 80
    assert result.summary["api_call_count"] == 64
    assert result.summary["cache_hit_count"] == 0
    assert result.summary["usage"]["estimated_cost_usd"] > 0
    assert result.summary["completed_count"] == 64


def test_deepseek_iching_resume_uses_per_hexagram_cache(tmp_path):
    output_dir = tmp_path / "run"
    first_client = FakeDeepSeekClient()
    first = DeepSeekIchingRunner(
        output_dir=output_dir,
        live=True,
        client=first_client,
    ).run()
    second_client = FakeDeepSeekClient()
    second = DeepSeekIchingRunner(
        output_dir=output_dir,
        live=True,
        client=second_client,
    ).run()

    assert first.ok is True
    assert second.ok is True
    assert len(first_client.calls) == 64
    assert second_client.calls == []
    assert second.summary["cache_hit_count"] == 64
    assert second.summary["api_call_count"] == 0
    assert second.summary["usage"]["estimated_cost_usd"] == 0.0


def test_deepseek_iching_fresh_ignores_existing_cache(tmp_path):
    output_dir = tmp_path / "run"
    first_client = FakeDeepSeekClient()
    DeepSeekIchingRunner(
        output_dir=output_dir,
        live=True,
        client=first_client,
    ).run()
    second_client = FakeDeepSeekClient()
    result = DeepSeekIchingRunner(
        output_dir=output_dir,
        live=True,
        fresh=True,
        client=second_client,
    ).run()

    assert result.ok is True
    assert len(second_client.calls) == 64
    assert result.summary["cache_hit_count"] == 0


def test_deepseek_iching_retries_transient_failure(tmp_path):
    client = FlakyDeepSeekClient()
    result = DeepSeekIchingRunner(
        output_dir=tmp_path / "run",
        live=True,
        client=client,
        hexagrams=YIJING_HEXAGRAMS[:1],
        retry_attempts=1,
        retry_delay_s=0,
    ).run()

    assert result.ok is True
    assert len(client.calls) == 1
    assert result.summary["retry_count"] == 1
    assert result.summary["api_call_count"] == 2


def test_validate_iching_run_rejects_missing_hexagram(tmp_path):
    result = DeepSeekIchingRunner(output_dir=tmp_path / "run").run()
    summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
    summary["results"] = summary["results"][:-1]
    summary["hexagram_count"] = 63
    summary["completed_count"] = 63
    result.summary_path.write_text(json.dumps(summary), encoding="utf-8")

    validation = validate_iching_run(result.output_dir)

    assert validation.ok is False
    assert any("hexagram_count" in error for error in validation.errors)


def test_validate_iching_run_rejects_mixed_live_event_flow(tmp_path):
    result = DeepSeekIchingRunner(output_dir=tmp_path / "run").run()
    with result.event_flow_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": "stale-live-event",
            "ts": 1,
            "type": "deepseek.requested",
            "source": "deepseek_iching_64",
            "payload": {"number": 1, "live": True},
        }) + "\n")

    validation = validate_iching_run(result.output_dir)

    assert validation.ok is False
    assert any("dry-run event_flow" in error for error in validation.errors)
    assert any("summary.live" in error for error in validation.errors)


def test_deepseek_iching_cli_dry_run_returns_success(tmp_path, capsys):
    exit_code = main(["--output-dir", str(tmp_path / "run")])
    printed = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert printed["ok"] is True
    assert printed["completed_count"] == 64
    assert "results" not in printed


def test_deepseek_iching_cli_live_requires_key(monkeypatch, capsys):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

    exit_code = main(["--live"])
    printed = capsys.readouterr().out

    assert exit_code == 2
    assert "DEEPSEEK_API_KEY is not configured" in printed


def test_deepseek_chat_client_strips_api_key_whitespace(monkeypatch):
    key_one = "test" + "-key"
    key_two = "test" + "-key-2"
    monkeypatch.setenv("DEEPSEEK_API_KEY", f"  {key_one}\n")
    kwargs = {"api_key": f"\t{key_two} "}

    assert DeepSeekChatClient().api_key == key_one
    assert DeepSeekChatClient(**kwargs).api_key == key_two


def test_deepseek_live_helper_checks_native_exit_codes():
    script = (REPO_ROOT / "scripts" / "run_deepseek_iching_live.ps1").read_text(
        encoding="utf-8"
    )

    assert "function Invoke-NativeChecked" in script
    assert "$LASTEXITCODE -ne 0" in script
    assert "examples\\deepseek_iching_64.py" in script
    assert "examples\\validate_deepseek_iching_64.py" in script


def test_deepseek_key_store_writes_no_trailing_newline():
    script = (REPO_ROOT / "scripts" / "save_deepseek_key_dpapi.ps1").read_text(
        encoding="utf-8"
    )

    assert "Set-Content" in script
    assert "-NoNewline" in script
