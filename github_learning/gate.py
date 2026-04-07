"""
GitHub Learning Pipeline — Human review gate.
CLI-based: list, review, approve, reject, quality.
All decisions logged to gate_decisions.jsonl.
"""
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).parent / "data"
PENDING_DIR = DATA_DIR / "pending_review"
APPROVED_DIR = DATA_DIR / "approved"
REJECTED_DIR = DATA_DIR / "rejected"
DECISIONS_LOG = DATA_DIR / "gate_decisions.jsonl"


def _ensure_dirs():
    for d in [PENDING_DIR, APPROVED_DIR, REJECTED_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def list_pending() -> List[dict]:
    _ensure_dirs()
    items = []
    for f in sorted(PENDING_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            items.append(data)
        except (json.JSONDecodeError, OSError):
            pass
    return items


def review(mechanism_id: str) -> Optional[dict]:
    _ensure_dirs()
    path = PENDING_DIR / f"{mechanism_id}.json"
    if not path.exists():
        print(f"Not found: {mechanism_id}")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data


def _log_decision(mechanism_id: str, decision: str, note: str = ""):
    entry = {
        "mechanism_id": mechanism_id,
        "decision": decision,
        "note": note,
        "ts": datetime.utcnow().isoformat() + "Z",
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DECISIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def approve(mechanism_id: str, note: str = "") -> bool:
    _ensure_dirs()
    src = PENDING_DIR / f"{mechanism_id}.json"
    if not src.exists():
        print(f"Not found: {mechanism_id}")
        return False
    dst = APPROVED_DIR / f"{mechanism_id}.json"
    shutil.move(str(src), str(dst))
    _log_decision(mechanism_id, "approved", note)
    print(f"Approved: {mechanism_id}")
    return True


def reject(mechanism_id: str, reason: str = "") -> bool:
    _ensure_dirs()
    src = PENDING_DIR / f"{mechanism_id}.json"
    if not src.exists():
        print(f"Not found: {mechanism_id}")
        return False
    dst = REJECTED_DIR / f"{mechanism_id}.json"
    shutil.move(str(src), str(dst))
    _log_decision(mechanism_id, "rejected", reason)
    print(f"Rejected: {mechanism_id}")
    return True


def print_pending():
    items = list_pending()
    if not items:
        print("No pending mechanisms.")
        return
    print(f"\n{'ID':<18} {'Repo':<35} {'Category':<15} {'Score'}")
    print("-" * 80)
    for m in items:
        print(f"{m.get('mechanism_id','?'):<18} {m.get('repo','?'):<35} "
              f"{m.get('category','?'):<15} {m.get('relevance_score',0):.2f}")
        desc = m.get("description", "")[:80]
        print(f"  {desc}")
    print(f"\nTotal: {len(items)} pending")


def print_review(mechanism_id: str):
    data = review(mechanism_id)
    if not data:
        return
    print(f"\n{'='*60}")
    print(f"Mechanism: {data.get('mechanism_id')}")
    print(f"Repo:      {data.get('repo')}")
    print(f"Category:  {data.get('category')}")
    print(f"Score:     {data.get('relevance_score')}")
    print(f"Risk:      {data.get('risk_level')}")
    print(f"Est hours: {data.get('estimated_hours')}")
    print(f"\nDescription:\n  {data.get('description', '')}")
    print(f"\nPitfall avoided:\n  {data.get('pitfall_avoided', '')[:300]}")
    print(f"\nEvidence: {data.get('evidence_url', '')}")
    print(f"{'='*60}")


# ── Quality Gate ──────────────────────────────────────────────

QUALITY_LATEST = Path(__file__).resolve().parents[1] / "coherent_engine" / "pipeline" / "experience_quality_latest.json"
GATE_QUALITY_LATEST = DATA_DIR / "gate_quality_latest.json"


def _load_quality_report() -> Optional[Dict[str, Any]]:
    """Load the latest experience quality report."""
    if not QUALITY_LATEST.exists():
        return None
    try:
        return json.loads(QUALITY_LATEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def quality_check() -> Dict[str, Any]:
    """
    Run quality gate check against experience_quality_latest.json.
    Returns verdict: PASS / WARN / FAIL with summary line.
    """
    report = _load_quality_report()

    if report is None:
        result = {
            "verdict": "FAIL",
            "reason": "experience_quality_latest.json not found",
            "summary": "quality: MISSING",
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "report": None,
        }
        _save_gate_quality(result)
        return result

    # Validate required fields
    required = ["generated_at", "total", "active", "quarantined", "expired", "decayed", "rollback_candidates"]
    missing = [f for f in required if f not in report]
    if missing:
        result = {
            "verdict": "FAIL",
            "reason": f"missing fields: {', '.join(missing)}",
            "summary": f"quality: FAIL (missing {len(missing)} fields)",
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "report": report,
        }
        _save_gate_quality(result)
        return result

    # Extract metrics
    total = report.get("total", 0)
    active = report.get("active", 0)
    quarantined = report.get("quarantined", 0)
    expired = report.get("expired", 0)
    decayed = report.get("decayed", 0)
    rollback = report.get("rollback_candidates", [])
    rollback_count = len(rollback) if isinstance(rollback, list) else 0

    summary = (f"quality: {total}/{active}/{quarantined}/{expired}/{decayed}/{rollback_count} "
               f"(total/active/quarantined/expired/decayed/rollback)")

    # Determine verdict
    warnings = []
    if rollback_count > 0:
        warnings.append(f"{rollback_count} rollback candidates")
    if quarantined > 0:
        warnings.append(f"{quarantined} quarantined")

    if warnings:
        verdict = "WARN"
        reason = "; ".join(warnings)
    else:
        verdict = "PASS"
        reason = "all clear"

    result = {
        "verdict": verdict,
        "reason": reason,
        "summary": summary,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "report": report,
    }
    _save_gate_quality(result)
    return result


def _save_gate_quality(result: Dict[str, Any]):
    """Write gate_quality_latest.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GATE_QUALITY_LATEST.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def print_quality():
    """Print quality gate check result."""
    result = quality_check()
    v = result["verdict"]
    tag = {"PASS": "PASS", "WARN": "WARN", "FAIL": "FAIL"}[v]
    print(f"\n[{tag}] {result['summary']}")
    if result["reason"] != "all clear":
        print(f"  Reason: {result['reason']}")
    report = result.get("report")
    if report:
        top_good = report.get("top_good", [])
        if top_good:
            print(f"  Top good: {top_good[0].get('experience_id', '?')} (conf={top_good[0].get('confidence', '?')})")
        rollback = report.get("rollback_candidates", [])
        if rollback:
            for rc in rollback:
                print(f"  Rollback candidate: {rc.get('experience_id', '?')} (conf={rc.get('confidence', '?')}, hits={rc.get('hit_count', '?')})")
    print(f"  Evidence: {GATE_QUALITY_LATEST}")
    print()


# ── Worker Gate ───────────────────────────────────────────────

WORKER_STATUS = Path(__file__).resolve().parents[1] / "worker" / "worker_data" / "worker_status.json"
WORKER_CYCLES = Path(__file__).resolve().parents[1] / "worker" / "worker_data" / "worker_cycles.jsonl"
GATE_WORKER_LATEST = DATA_DIR / "gate_worker_latest.json"


def _load_worker_status() -> Optional[Dict[str, Any]]:
    if not WORKER_STATUS.exists():
        return None
    try:
        return json.loads(WORKER_STATUS.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_recent_cycles(window_hours: int = 24) -> List[Dict[str, Any]]:
    """Load cycles from worker_cycles.jsonl within the time window."""
    if not WORKER_CYCLES.exists():
        return []
    cutoff = datetime.now(timezone.utc).timestamp() - window_hours * 3600
    cycles = []
    try:
        for line in WORKER_CYCLES.read_text(encoding="utf-8").strip().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            ts_str = entry.get("ts", "")
            if ts_str:
                try:
                    dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if dt.timestamp() >= cutoff:
                        cycles.append(entry)
                except (ValueError, TypeError):
                    cycles.append(entry)
    except (OSError, json.JSONDecodeError):
        pass
    return cycles


def worker_check(window_hours: int = 2) -> Dict[str, Any]:
    """
    Run worker gate check. Verdict: PASS / WARN / FAIL.
    Checks: status file exists, recent cycles, no persistent errors, evidence paths.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    status = _load_worker_status()

    # FAIL: status file missing or unparseable
    if status is None:
        result = {
            "verdict": "FAIL",
            "reason": "worker_status.json not found or unparseable",
            "summary": "worker: MISSING",
            "checked_at": now_str,
            "window_hours": window_hours,
            "status": None,
            "recent_cycles": 0,
        }
        _save_gate_worker(result)
        return result

    cycles = _load_recent_cycles(window_hours)
    last_error = status.get("last_error", "")
    current_mode = status.get("current_mode", "unknown")
    cycles_completed = status.get("cycles_completed", 0)
    last_cycle_at = status.get("last_cycle_at", "")

    # Check how long since last cycle
    hours_since_cycle = None
    if last_cycle_at:
        try:
            dt = datetime.fromisoformat(last_cycle_at.replace("Z", "+00:00"))
            hours_since_cycle = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    # Evidence paths check
    evidence_ok = WORKER_STATUS.exists() and WORKER_CYCLES.exists()

    # Build warnings
    warnings = []
    fail_reasons = []

    if cycles_completed == 0 and not cycles:
        fail_reasons.append("no cycles ever completed")
    elif not cycles and hours_since_cycle and hours_since_cycle > window_hours:
        fail_reasons.append(f"no cycles in last {window_hours}h (last: {hours_since_cycle:.1f}h ago)")

    if last_error:
        warnings.append(f"last_error: {last_error[:100]}")

    if current_mode == "stopped":
        warnings.append("worker is stopped")

    if not evidence_ok:
        warnings.append("worker_cycles.jsonl missing")

    # Sparse cycles warning
    if cycles and len(cycles) < 2 and window_hours >= 24:
        warnings.append(f"only {len(cycles)} cycle(s) in {window_hours}h window")

    # Determine verdict and next_action
    if fail_reasons:
        verdict = "FAIL"
        reason = "; ".join(fail_reasons)
        next_action = "restart worker and verify cycle output"
    elif warnings:
        verdict = "WARN"
        reason = "; ".join(warnings)
        if current_mode == "stopped":
            next_action = "restart worker"
        elif last_error:
            next_action = "investigate last_error, clear if resolved"
        else:
            next_action = "monitor next cycle"
    else:
        verdict = "PASS"
        reason = "all clear"
        next_action = "none - worker healthy"

    summary = (f"worker: cycles={cycles_completed} recent={len(cycles)}/{window_hours}h "
               f"mode={current_mode} error={'yes' if last_error else 'no'}")

    result = {
        "verdict": verdict,
        "reason": reason,
        "summary": summary,
        "checked_at": now_str,
        "window_hours": window_hours,
        "cycles_completed": cycles_completed,
        "recent_cycles": len(cycles),
        "current_mode": current_mode,
        "last_cycle_at": last_cycle_at,
        "last_success_at": status.get("last_success_at", ""),
        "last_error": last_error[:200] if last_error else "",
        "next_action": next_action,
        "evidence_paths": {
            "worker_status": str(WORKER_STATUS),
            "worker_cycles": str(WORKER_CYCLES),
        },
        "status": status,
    }
    _save_gate_worker(result)
    return result


def _save_gate_worker(result: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GATE_WORKER_LATEST.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def print_worker(window_hours: int = 2):
    """Print worker gate check result."""
    result = worker_check(window_hours=window_hours)
    v = result["verdict"]
    print(f"\n[{v}] {result['summary']}")
    if result["reason"] != "all clear":
        print(f"  Reason: {result['reason']}")
    if result.get("last_cycle_at"):
        print(f"  Last cycle: {result['last_cycle_at']}")
    if result.get("next_action"):
        print(f"  Next action: {result['next_action']}")
    print(f"  Evidence: {GATE_WORKER_LATEST}")
    print()
