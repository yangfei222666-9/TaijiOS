"""
Reviewed Baseline Manifest — the single gate for experience admission.

No experience enters experience_index.json without passing through this manifest.
Every entry has: baseline_version, source_trace, admission status.

Usage:
    from github_learning.manifest import admit, list_manifest, sync_to_index
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).parent / "data"
MANIFEST_PATH = DATA_DIR / "reviewed_baseline_manifest.json"
EXPERIENCE_INDEX = Path(__file__).resolve().parents[1] / "coherent_engine" / "pipeline" / "experience_index.json"


def _load_manifest() -> Dict[str, Any]:
    if MANIFEST_PATH.exists():
        try:
            return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"baseline_version": 0, "entries": [], "updated_at": ""}


def _save_manifest(manifest: Dict[str, Any]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    manifest["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def admit(
    mechanism_id: str,
    experience_key: str,
    content: str,
    inject_to: str = "planner_system",
    confidence: float = 0.5,
    source_repo: str = "",
    gate_decision_id: str = "",
    category: str = "",
) -> Dict[str, Any]:
    """
    Admit a new experience into the manifest. Bumps baseline_version.
    New entries start with admission_status='probation' (L3 will use this).
    """
    manifest = _load_manifest()
    manifest["baseline_version"] += 1

    entry = {
        "mechanism_id": mechanism_id,
        "experience_id": f"github_{mechanism_id}",
        "experience_key": experience_key,
        "content": content,
        "inject_to": inject_to,
        "confidence": confidence,
        "admission_status": "probation",
        "admitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "baseline_version": manifest["baseline_version"],
        "source_trace": {
            "source_repo": source_repo,
            "gate_decision_id": gate_decision_id,
            "category": category,
            "pipeline": "github_learning",
        },
    }

    # Dedup by mechanism_id
    existing_ids = {e["mechanism_id"] for e in manifest["entries"]}
    if mechanism_id in existing_ids:
        manifest["entries"] = [
            e if e["mechanism_id"] != mechanism_id else entry
            for e in manifest["entries"]
        ]
    else:
        manifest["entries"].append(entry)

    _save_manifest(manifest)
    return entry


def promote(mechanism_id: str) -> bool:
    """Promote an entry from probation to active."""
    manifest = _load_manifest()
    for e in manifest["entries"]:
        if e["mechanism_id"] == mechanism_id:
            e["admission_status"] = "active"
            e["promoted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _save_manifest(manifest)
            return True
    return False


def revoke(mechanism_id: str, reason: str = "") -> bool:
    """Revoke an entry (soft delete, keeps trace)."""
    manifest = _load_manifest()
    for e in manifest["entries"]:
        if e["mechanism_id"] == mechanism_id:
            e["admission_status"] = "revoked"
            e["revoked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            e["revoke_reason"] = reason
            _save_manifest(manifest)
            return True
    return False


def auto_promote(min_hits: int = 3, min_success_rate: float = 0.6) -> List[str]:
    """
    Auto-promote probation entries that have proven themselves.
    Reads stats from experience_index, promotes if hit_count >= min_hits
    and success_rate >= min_success_rate.
    Returns list of promoted mechanism_ids.
    """
    manifest = _load_manifest()
    probation = [e for e in manifest["entries"] if e.get("admission_status") == "probation"]
    if not probation:
        return []

    # Load experience index for stats
    idx = []
    if EXPERIENCE_INDEX.exists():
        try:
            idx = json.loads(EXPERIENCE_INDEX.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Build stats lookup by experience_id
    stats_by_id = {}
    for entry in idx:
        eid = entry.get("source_experience_id", "")
        if eid:
            stats_by_id[eid] = entry.get("stats", {})

    promoted = []
    for e in probation:
        eid = e.get("experience_id", "")
        stats = stats_by_id.get(eid, {})
        hits = stats.get("hit_count", 0)
        success = stats.get("success", 0)
        fail = stats.get("fail", 0)
        total = success + fail

        if hits >= min_hits and total >= min_hits:
            rate = success / total if total > 0 else 0
            if rate >= min_success_rate:
                e["admission_status"] = "active"
                e["promoted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                e["promotion_reason"] = f"auto: {hits} hits, {rate:.0%} success rate"
                promoted.append(e["mechanism_id"])

    if promoted:
        _save_manifest(manifest)

    return promoted


def revoke(mechanism_id: str, reason: str = "") -> bool:
    """Revoke an entry (soft delete, keeps trace)."""
    manifest = _load_manifest()
    for e in manifest["entries"]:
        if e["mechanism_id"] == mechanism_id:
            e["admission_status"] = "revoked"
            e["revoked_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            e["revoke_reason"] = reason
            _save_manifest(manifest)
            return True
    return False


def sync_to_index() -> int:
    """
    Sync manifest entries to experience_index.json.
    Only entries with admission_status in ('probation', 'active') are synced.
    Revoked entries are removed from the index.
    This is the ONLY path into experience_index from github_learning.
    Returns count of entries synced.
    """
    manifest = _load_manifest()

    # Load current index
    idx = []
    if EXPERIENCE_INDEX.exists():
        try:
            idx = json.loads(EXPERIENCE_INDEX.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            idx = []

    # Separate non-github entries (seed, internal) from github entries
    non_github = [e for e in idx if "github_learning" not in (e.get("key") or e.get("matched_key") or "")]

    # Build new github entries from manifest
    synced = 0
    github_entries = []
    for entry in manifest["entries"]:
        if entry["admission_status"] in ("probation", "active"):
            exp = {
                "key": entry["experience_key"],
                "inject_to": entry["inject_to"],
                "content": entry["content"],
                "confidence": entry["confidence"],
                "source_experience_id": entry["experience_id"],
                "source_reason_code": entry["experience_key"].split("+")[-1] if "+" in entry["experience_key"] else entry["experience_key"],
                "baseline_version": entry["baseline_version"],
                "admission_status": entry["admission_status"],
                "stats": {"success": 0, "fail": 0, "hit_count": 0, "last_seen": ""},
                "created_at": time.time(),
                "ttl_days": 0,
                "quarantined": entry["admission_status"] == "probation",
            }
            # Preserve existing stats if already in index
            for old in idx:
                if old.get("source_experience_id") == entry["experience_id"]:
                    exp["stats"] = old.get("stats", exp["stats"])
                    exp["created_at"] = old.get("created_at", exp["created_at"])
                    exp["confidence"] = old.get("confidence", exp["confidence"])
                    if entry["admission_status"] == "active":
                        exp["quarantined"] = False
                    break
            github_entries.append(exp)
            synced += 1

    # Merge: non-github + manifest-controlled github
    new_idx = non_github + github_entries
    EXPERIENCE_INDEX.parent.mkdir(parents=True, exist_ok=True)
    EXPERIENCE_INDEX.write_text(
        json.dumps(new_idx, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return synced


def list_manifest() -> List[Dict[str, Any]]:
    """Return all manifest entries."""
    return _load_manifest()["entries"]


def get_manifest_summary() -> Dict[str, Any]:
    """Summary for gate/report consumption."""
    manifest = _load_manifest()
    entries = manifest["entries"]
    return {
        "baseline_version": manifest["baseline_version"],
        "total": len(entries),
        "probation": sum(1 for e in entries if e.get("admission_status") == "probation"),
        "active": sum(1 for e in entries if e.get("admission_status") == "active"),
        "revoked": sum(1 for e in entries if e.get("admission_status") == "revoked"),
        "updated_at": manifest.get("updated_at", ""),
    }


def print_manifest():
    """Print manifest summary for CLI."""
    summary = get_manifest_summary()
    entries = list_manifest()
    print(f"\nBaseline v{summary['baseline_version']}  "
          f"total={summary['total']} active={summary['active']} "
          f"probation={summary['probation']} revoked={summary['revoked']}")
    print(f"Updated: {summary['updated_at']}")
    if entries:
        print(f"\n{'ID':<20} {'Status':<12} {'Key':<40} {'Repo'}")
        print("-" * 90)
        for e in entries:
            print(f"{e['mechanism_id']:<20} {e['admission_status']:<12} "
                  f"{e['experience_key'][:40]:<40} {e.get('source_trace',{}).get('source_repo','')}")
    print()
