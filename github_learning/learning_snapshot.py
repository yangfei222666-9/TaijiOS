"""
Learning Latest — snapshot of the entire learning pipeline state.

Generates learning_latest.json for worker/gate/daily-report consumption.
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

DATA_DIR = Path(__file__).parent / "data"
LEARNING_LATEST = DATA_DIR / "learning_latest.json"
DISCOVERED = DATA_DIR / "discovered_repos.jsonl"
ANALYSES = DATA_DIR / "analyses.jsonl"
DIGESTED = DATA_DIR / "digested_mechanisms.jsonl"
SOLIDIFIED = DATA_DIR / "solidified.jsonl"


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def _count_dir(path: Path) -> int:
    if not path.exists():
        return 0
    return len(list(path.glob("*.json")))


def generate_learning_snapshot(cycle_id: str = "") -> Dict[str, Any]:
    """Generate a full snapshot of the learning pipeline and write to learning_latest.json."""
    from .manifest import get_manifest_summary

    pending = _count_dir(DATA_DIR / "pending_review")
    approved = _count_dir(DATA_DIR / "approved")
    rejected = _count_dir(DATA_DIR / "rejected")
    manifest = get_manifest_summary()

    snapshot = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest_cycle_id": cycle_id,
        "pipeline": {
            "discovered": _count_jsonl(DISCOVERED),
            "analyzed": _count_jsonl(ANALYSES),
            "digested": _count_jsonl(DIGESTED),
            "solidified": _count_jsonl(SOLIDIFIED),
        },
        "gate": {
            "pending": pending,
            "approved": approved,
            "rejected": rejected,
        },
        "manifest": manifest,
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LEARNING_LATEST.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return snapshot


def print_learning_snapshot(cycle_id: str = ""):
    """Print learning snapshot for CLI."""
    snap = generate_learning_snapshot(cycle_id=cycle_id)
    p = snap["pipeline"]
    g = snap["gate"]
    m = snap["manifest"]
    print(f"\n=== Learning Pipeline Snapshot ===")
    print(f"  Generated: {snap['generated_at']}")
    print(f"  Pipeline: discovered={p['discovered']} analyzed={p['analyzed']} "
          f"digested={p['digested']} solidified={p['solidified']}")
    print(f"  Gate: pending={g['pending']} approved={g['approved']} rejected={g['rejected']}")
    print(f"  Manifest: v{m['baseline_version']} total={m['total']} "
          f"active={m['active']} probation={m['probation']} revoked={m['revoked']}")
    print(f"  Evidence: {LEARNING_LATEST}")
    print()
