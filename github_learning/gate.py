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
