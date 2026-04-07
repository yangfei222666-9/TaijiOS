"""
GitHub Learning Pipeline — Human review gate.
CLI-based: list, review, approve, reject.
All decisions logged to gate_decisions.jsonl.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

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
