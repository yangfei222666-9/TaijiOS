"""
GitHub Learning Pipeline — Solidify approved mechanisms into TaijiOS.
Path 1: EchoCore experience (lessons/patterns)
Path 2: Skill scaffold (concrete implementations)
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

DATA_DIR = Path(__file__).parent / "data"
APPROVED_DIR = DATA_DIR / "approved"
SOLIDIFIED_LOG = DATA_DIR / "solidified.jsonl"


def _load_approved() -> List[Dict[str, Any]]:
    if not APPROVED_DIR.exists():
        return []
    items = []
    for f in sorted(APPROVED_DIR.glob("*.json")):
        try:
            items.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return items


def _already_solidified() -> set:
    ids = set()
    if SOLIDIFIED_LOG.exists():
        for line in SOLIDIFIED_LOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    ids.add(json.loads(line).get("mechanism_id", ""))
                except json.JSONDecodeError:
                    pass
    return ids


def solidify_as_experience(mechanism: Dict[str, Any]) -> Dict[str, Any]:
    """Convert mechanism to EchoCore experience format."""
    return {
        "title": f"github_learning/{mechanism['repo']}/{mechanism['mechanism_id']}",
        "description": mechanism.get("description", ""),
        "content": json.dumps(mechanism, ensure_ascii=False),
        "type": "external_learning",
        "tags": ["github_learning", mechanism.get("category", ""), mechanism.get("repo", "")],
        "metadata": {
            "source_system": "github_learning",
            "custom_fields": {
                "mechanism_id": mechanism.get("mechanism_id"),
                "repo": mechanism.get("repo"),
                "category": mechanism.get("category"),
                "risk_level": mechanism.get("risk_level"),
                "pitfall_avoided": mechanism.get("pitfall_avoided", "")[:500],
                "evidence_url": mechanism.get("evidence_url"),
            },
        },
    }


def solidify_all() -> List[Dict[str, Any]]:
    """Solidify all approved, un-solidified mechanisms."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    approved = _load_approved()
    already = _already_solidified()
    new_items = [m for m in approved if m.get("mechanism_id") not in already]

    if not new_items:
        print("No new approved mechanisms to solidify.")
        return []

    results = []
    now = datetime.utcnow().isoformat() + "Z"

    with open(SOLIDIFIED_LOG, "a", encoding="utf-8") as f:
        for m in new_items:
            exp = solidify_as_experience(m)
            record = {
                "mechanism_id": m["mechanism_id"],
                "repo": m.get("repo", ""),
                "path": "experience",
                "experience_payload": exp,
                "solidified_at": now,
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            results.append(record)
            print(f"  Solidified: {m['mechanism_id']} ({m.get('repo')}) -> experience")

    print(f"\nSolidified: {len(results)} mechanisms")
    return results
