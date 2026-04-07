"""
GitHub Learning Pipeline — Digest analyses into concrete mechanisms.
Extracts structured lessons with idempotent keys.
"""
import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

DATA_DIR = Path(__file__).parent / "data"


def _idem_key(repo: str, desc: str) -> str:
    raw = f"{repo}:{desc}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class DigestedMechanism:
    mechanism_id: str
    repo: str
    category: str  # architecture|communication|lifecycle|observability|testing
    description: str
    implementation_sketch: str
    pitfall_avoided: str
    evidence_url: str
    risk_level: str  # low|medium|high
    estimated_hours: float
    relevance_score: float
    digested_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def digest_analysis(analysis: Dict[str, Any]) -> List[DigestedMechanism]:
    """Extract mechanisms from a single repo analysis."""
    full_name = analysis.get("full_name", "")
    mechanisms_text = analysis.get("q3_mechanisms", "")
    pitfalls_text = analysis.get("q2_pitfalls", "")
    gate_text = analysis.get("q4_gate_plan", "")
    relevance = float(analysis.get("relevance_score", 0.0))

    # Split mechanisms text into individual items
    items = []
    if isinstance(mechanisms_text, list):
        items = [str(m).strip() for m in mechanisms_text if str(m).strip()]
    elif isinstance(mechanisms_text, str) and mechanisms_text:
        for line in mechanisms_text.replace("\\n", "\n").split("\n"):
            line = line.strip().lstrip("-•*0123456789.) ")
            if len(line) > 10:
                items.append(line)
        if not items:
            items = [mechanisms_text[:500]]

    results = []
    now = datetime.utcnow().isoformat() + "Z"
    for item in items:
        mid = _idem_key(full_name, item)
        cat = _infer_category(item)
        results.append(DigestedMechanism(
            mechanism_id=mid,
            repo=full_name,
            category=cat,
            description=item,
            implementation_sketch="",
            pitfall_avoided=pitfalls_text[:300] if pitfalls_text else "",
            evidence_url=f"https://github.com/{full_name}",
            risk_level="medium",
            estimated_hours=4.0,
            relevance_score=relevance,
            digested_at=now,
        ))
    return results


def _infer_category(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["architect", "event", "plugin", "modular", "layer"]):
        return "architecture"
    if any(w in t for w in ["message", "queue", "pubsub", "rpc", "protocol"]):
        return "communication"
    if any(w in t for w in ["lifecycle", "state", "circuit", "heal", "retry", "recover"]):
        return "lifecycle"
    if any(w in t for w in ["log", "metric", "trace", "monitor", "observ", "alert"]):
        return "observability"
    if any(w in t for w in ["test", "bench", "coverage", "regression"]):
        return "testing"
    return "architecture"


def digest_all() -> List[DigestedMechanism]:
    """Digest all un-digested analyses."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    analysis_file = DATA_DIR / "analyses.jsonl"
    digest_file = DATA_DIR / "digested_mechanisms.jsonl"
    pending_dir = DATA_DIR / "pending_review"
    pending_dir.mkdir(parents=True, exist_ok=True)

    if not analysis_file.exists():
        print("No analyses found. Run 'analyze' first.")
        return []

    # Load already digested
    seen_ids = set()
    if digest_file.exists():
        for line in digest_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    seen_ids.add(json.loads(line).get("mechanism_id", ""))
                except json.JSONDecodeError:
                    pass

    # Process analyses
    all_mechanisms = []
    for line in analysis_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            analysis = json.loads(line)
        except json.JSONDecodeError:
            continue
        mechanisms = digest_analysis(analysis)
        for m in mechanisms:
            if m.mechanism_id not in seen_ids:
                all_mechanisms.append(m)
                seen_ids.add(m.mechanism_id)

    # Write to digest ledger + pending review
    with open(digest_file, "a", encoding="utf-8") as f:
        for m in all_mechanisms:
            f.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
            # Also write to pending_review as individual file
            pending_path = pending_dir / f"{m.mechanism_id}.json"
            pending_path.write_text(
                json.dumps(m.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    print(f"Digested: {len(all_mechanisms)} new mechanisms -> pending_review/")
    return all_mechanisms
