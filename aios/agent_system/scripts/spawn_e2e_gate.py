"""
Spawn E2E Gate — 最小闭环验证 spawn 链路完整性。

注入测试请求 → 执行 → 验证三处证据一致。
本地可执行，无需 OpenClaw session 或网络。

Usage:
    python aios/agent_system/scripts/spawn_e2e_gate.py
"""
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from paths import SPAWN_PENDING, SPAWN_RESULTS, ARTIFACT_LEDGER, DATA_DIR

GATE_DIR = DATA_DIR / "gate"
GATE_OUTPUT = GATE_DIR / "spawn_e2e_latest.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _last_jsonl_match(path: Path, task_id: str) -> dict | None:
    if not path.exists():
        return None
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
            if rec.get("task_id") == task_id:
                return rec
        except Exception:
            continue
    return None


def run_gate() -> dict:
    checks = {}
    ts = int(time.time())
    task_id = f"e2e_gate_{ts}"
    created_at = _utc_now()

    # ── 1. INJECT ────────────────────────────────────────────────
    # Save existing pending lines, inject our probe at the top
    try:
        req = {
            "task_id": task_id,
            "agent_id": "e2e_gate_probe",
            "message": "E2E gate probe: echo test",
            "metadata": {
                "exec": {
                    "kind": "openclaw_gateway",
                }
            },
            "model": "echo",
            "trace_id": task_id,
        }
        SPAWN_PENDING.parent.mkdir(parents=True, exist_ok=True)
        # Read existing lines, prepend our probe so it gets processed first
        existing = ""
        if SPAWN_PENDING.exists():
            existing = SPAWN_PENDING.read_text(encoding="utf-8")
        probe_line = json.dumps(req, ensure_ascii=False) + "\n"
        SPAWN_PENDING.write_text(probe_line + existing, encoding="utf-8")
        checks["INJECT"] = {"ok": True, "detail": f"task_id={task_id}"}
    except Exception as e:
        checks["INJECT"] = {"ok": False, "detail": str(e)}
        return _build_result(checks, created_at, task_id)

    # ── 2. EXECUTE ───────────────────────────────────────────────
    try:
        from spawn_pending_runner import process_spawn_pending
        processed = process_spawn_pending(max_items=1)
        checks["EXECUTE"] = {"ok": processed >= 1, "detail": f"processed={processed}"}
        if processed < 1:
            return _build_result(checks, created_at, task_id)
    except Exception as e:
        checks["EXECUTE"] = {"ok": False, "detail": str(e)}
        return _build_result(checks, created_at, task_id)

    # ── 3. RESULT_EXISTS ─────────────────────────────────────────
    sr = _last_jsonl_match(SPAWN_RESULTS, task_id)
    checks["RESULT_EXISTS"] = {
        "ok": sr is not None,
        "detail": f"status={sr.get('status')}" if sr else "not_found",
    }
    if sr is None:
        return _build_result(checks, created_at, task_id)

    # ── 4. ARTIFACT_EXISTS ───────────────────────────────────────
    ar = _last_jsonl_match(ARTIFACT_LEDGER, task_id)
    checks["ARTIFACT_EXISTS"] = {
        "ok": ar is not None,
        "detail": f"type={ar.get('artifact_type')}" if ar else "not_found",
    }

    # ── 5. STATUS_CONSISTENT ─────────────────────────────────────
    if sr and ar:
        sr_status = sr.get("status", "")
        ar_status = ar.get("status", "")
        consistent = sr_status == ar_status or (
            sr_status in ("completed", "success", "skipped") and ar_status in ("completed", "success", "skipped")
        )
        checks["STATUS_CONSISTENT"] = {
            "ok": consistent,
            "detail": f"spawn_result={sr_status} artifact={ar_status}",
        }
    else:
        checks["STATUS_CONSISTENT"] = {"ok": False, "detail": "missing_records"}

    # ── 6. EVIDENCE_WRITTEN ──────────────────────────────────────
    if ar and ar.get("artifact_path"):
        ap = Path(ar["artifact_path"])
        exists = ap.exists()
        sha = ar.get("sha256", "")
        checks["EVIDENCE_WRITTEN"] = {
            "ok": exists and bool(sha),
            "detail": f"exists={exists} sha256={'yes' if sha else 'no'} path={ap.name}",
        }
    else:
        checks["EVIDENCE_WRITTEN"] = {
            "ok": False,
            "detail": "no_artifact_path",
        }

    return _build_result(checks, created_at, task_id)


def _build_result(checks: dict, created_at: str, task_id: str) -> dict:
    all_ok = all(c["ok"] for c in checks.values())
    first_fail = next((k for k, v in checks.items() if not v["ok"]), None)

    result = {
        "gate": "spawn_e2e",
        "created_at": created_at,
        "ok": all_ok,
        "task_id": task_id,
        "checks": checks,
        "reason_code": "gate.spawn_e2e.pass" if all_ok else f"gate.spawn_e2e.{first_fail}",
        "evidence_path": str(GATE_OUTPUT),
        "next_action": "none" if all_ok else f"investigate_{first_fail}",
    }

    GATE_DIR.mkdir(parents=True, exist_ok=True)
    GATE_OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    result = run_gate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    status = "PASS" if result["ok"] else "FAIL"
    print(f"\n{'=' * 40}")
    print(f"spawn_e2e_gate: {status}")
    print(f"reason_code: {result['reason_code']}")
    print(f"evidence: {result['evidence_path']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
