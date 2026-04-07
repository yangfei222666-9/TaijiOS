"""
GitHub Learning Pipeline — Analyze repos with the 4 总控 questions.
Uses LLM (via Gateway or direct) to produce structured analysis.
"""
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

DATA_DIR = Path(__file__).parent / "data"
TEMPLATES_DIR = Path(__file__).parent / "templates"


@dataclass
class RepoAnalysis:
    full_name: str
    q1_root_problem: str = ""
    q2_pitfalls: str = ""
    q3_mechanisms: str = ""
    q4_gate_plan: str = ""
    relevance_score: float = 0.0
    analyzed_at: str = ""
    model_used: str = ""
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _load_prompt_template() -> str:
    path = TEMPLATES_DIR / "analysis_prompt.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return _DEFAULT_PROMPT


_DEFAULT_PROMPT = """You are TaijiOS's technical analyst. Analyze this GitHub repository.

## Repository: {full_name}
## Description: {description}
## Stars: {stars} | Language: {language}
## README excerpt:
{readme_excerpt}

Answer these 4 questions as JSON:

1. root_problem: What fundamental problem does this project solve?
2. pitfalls: What pitfalls or failures has it encountered? (from issues, design choices, README warnings)
3. mechanisms: Which specific mechanisms/patterns are worth migrating into TaijiOS? List concrete items.
4. gate_plan: For each mechanism worth migrating — who gates it, how to evidence it, how to prevent loss of control?

Also provide:
- relevance_score: 0.0-1.0 (how relevant is this to an AI operating system)

Respond ONLY with valid JSON:
{
  "root_problem": "...",
  "pitfalls": "...",
  "mechanisms": "...",
  "gate_plan": "...",
  "relevance_score": 0.0
}"""


def _call_llm(prompt: str) -> str:
    """Call LLM via Gateway (preferred) or direct Ollama fallback."""
    gw_url = os.environ.get("TAIJIOS_GATEWAY_URL", "http://127.0.0.1:9200")
    gw_enabled = os.environ.get("TAIJIOS_GATEWAY_ENABLED", "").lower() in ("1", "true")

    if gw_enabled:
        try:
            resp = requests.post(
                f"{gw_url}/v1/chat/completions",
                json={
                    "model": os.environ.get("GITHUB_LEARNING_MODEL", "qwen2.5:3b"),
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 2048,
                },
                headers={"Authorization": f"Bearer {os.environ.get('TAIJIOS_API_TOKEN', '')}"},
                timeout=120,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
        except Exception:
            pass

    # Fallback: direct Ollama
    try:
        resp = requests.post(
            "http://127.0.0.1:11434/api/chat",
            json={
                "model": os.environ.get("GITHUB_LEARNING_MODEL", "qwen2.5:3b"),
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=120,
        )
        if resp.status_code == 200:
            return resp.json().get("message", {}).get("content", "")
    except Exception as e:
        return f"LLM call failed: {e}"

    return ""


def _parse_analysis(raw: str, full_name: str) -> RepoAnalysis:
    """Parse LLM JSON response into RepoAnalysis."""
    analysis = RepoAnalysis(full_name=full_name, raw_response=raw[:3000])
    try:
        # Extract JSON from response (may have markdown fences)
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        data = json.loads(text)
        analysis.q1_root_problem = data.get("root_problem", "")
        analysis.q2_pitfalls = data.get("pitfalls", "")
        analysis.q3_mechanisms = data.get("mechanisms", "")
        analysis.q4_gate_plan = data.get("gate_plan", "")
        analysis.relevance_score = float(data.get("relevance_score", 0.0))
    except (json.JSONDecodeError, ValueError, IndexError):
        analysis.q1_root_problem = raw[:500]
    return analysis


def analyze_repo(repo_data: Dict[str, Any], dry_run: bool = False) -> Optional[RepoAnalysis]:
    """Analyze a single discovered repo."""
    template = _load_prompt_template()
    prompt = template.format(
        full_name=repo_data.get("full_name", ""),
        description=repo_data.get("description", ""),
        stars=repo_data.get("stars", 0),
        language=repo_data.get("language", ""),
        readme_excerpt=repo_data.get("readme_excerpt", "")[:2000],
    )

    if dry_run:
        print(f"[dry-run] Would analyze: {repo_data.get('full_name')}")
        print(f"  Prompt length: {len(prompt)} chars")
        return None

    from datetime import datetime
    raw = _call_llm(prompt)
    analysis = _parse_analysis(raw, repo_data["full_name"])
    analysis.analyzed_at = datetime.utcnow().isoformat() + "Z"
    analysis.model_used = os.environ.get("GITHUB_LEARNING_MODEL", "qwen2.5:3b")
    return analysis


def analyze_all(limit: int = 10, dry_run: bool = False) -> List[RepoAnalysis]:
    """Analyze all un-analyzed discovered repos."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ledger = DATA_DIR / "discovered_repos.jsonl"
    analysis_file = DATA_DIR / "analyses.jsonl"

    if not ledger.exists():
        print("No discovered repos. Run 'discover' first.")
        return []

    # Load already analyzed
    analyzed = set()
    if analysis_file.exists():
        for line in analysis_file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    analyzed.add(json.loads(line).get("full_name", ""))
                except json.JSONDecodeError:
                    pass

    # Load discovered repos
    repos = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                d = json.loads(line)
                if d.get("full_name") not in analyzed:
                    repos.append(d)
            except json.JSONDecodeError:
                pass

    repos = repos[:limit]
    print(f"Analyzing {len(repos)} repos ({len(analyzed)} already done)")

    results = []
    for repo in repos:
        print(f"  Analyzing: {repo['full_name']} ({repo.get('stars', 0)} stars)...")
        analysis = analyze_repo(repo, dry_run=dry_run)
        if analysis and not dry_run:
            results.append(analysis)
            with open(analysis_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(analysis.to_dict(), ensure_ascii=False) + "\n")
            print(f"    relevance={analysis.relevance_score:.2f}")

    return results
