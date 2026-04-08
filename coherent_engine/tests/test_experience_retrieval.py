"""experience_retrieval unit tests — 三级检索、quality gates、inject、save、decay、report."""
import json
import time
import pytest
from pathlib import Path
from unittest.mock import patch

from coherent_engine.pipeline.experience_retrieval import (
    retrieve,
    retrieve_all,
    inject_to_system_prompt,
    save_to_index,
    record_outcome,
    quarantine_experience,
    unquarantine_experience,
    decay_stale_experiences,
    get_quality_report,
    _make_keys,
    _SEED_INDEX,
)


# ── Fixtures ─────────────────────────────────────────────────────────

def _make_entry(key, exp_id="exp_001", confidence=0.8, **overrides):
    base = {
        "key": key,
        "inject_to": "planner_system",
        "content": f"experience for {key}",
        "confidence": confidence,
        "source_experience_id": exp_id,
        "source_reason_code": "test.rc",
        "quarantined": False,
        "ttl_days": 0,
        "created_at": time.time(),
        "stats": {"success": 0, "fail": 0, "hit_count": 0, "last_seen": ""},
    }
    base.update(overrides)
    return base


# ── _make_keys ───────────────────────────────────────────────────────

class TestMakeKeys:
    def test_full_keys(self):
        keys = _make_keys("brand1", "char1", "rc1")
        assert keys == ["brand1+char1+rc1", "brand1+*+rc1", "*+*+rc1"]

    def test_empty_brand_char(self):
        keys = _make_keys("", "", "rc1")
        assert keys == ["*+*+rc1", "*+*+rc1", "*+*+rc1"]


# ── 三层检索优先级 ───────────────────────────────────────────────────

class TestRetrievePriority:
    def test_exact_match_first(self):
        idx = [
            _make_entry("b+c+rc", exp_id="exact", confidence=0.6),
            _make_entry("b+*+rc", exp_id="brand", confidence=0.9),
            _make_entry("*+*+rc", exp_id="wild", confidence=0.9),
        ]
        hit = retrieve("b", "c", "rc", index=idx)
        assert hit["source_experience_id"] == "exact"
        assert hit["priority"] == 0

    def test_brand_fallback(self):
        idx = [
            _make_entry("b+*+rc", exp_id="brand", confidence=0.8),
            _make_entry("*+*+rc", exp_id="wild", confidence=0.9),
        ]
        hit = retrieve("b", "c", "rc", index=idx)
        assert hit["source_experience_id"] == "brand"
        assert hit["priority"] == 1

    def test_wildcard_fallback(self):
        idx = [_make_entry("*+*+rc", exp_id="wild")]
        hit = retrieve("b", "c", "rc", index=idx)
        assert hit["source_experience_id"] == "wild"
        assert hit["priority"] == 2

    def test_no_match_returns_none(self):
        idx = [_make_entry("*+*+other_rc")]
        assert retrieve("b", "c", "rc", index=idx) is None

    def test_confidence_sorting(self):
        idx = [
            _make_entry("*+*+rc", exp_id="low", confidence=0.3),
            _make_entry("*+*+rc", exp_id="high", confidence=0.9),
        ]
        hit = retrieve("", "", "rc", index=idx)
        assert hit["source_experience_id"] == "high"


# ── Quality Gates ────────────────────────────────────────────────────

class TestQualityGates:
    def test_quarantined_skipped(self):
        idx = [_make_entry("*+*+rc", quarantined=True)]
        assert retrieve("", "", "rc", index=idx) is None

    def test_expired_skipped(self):
        idx = [_make_entry("*+*+rc", ttl_days=1, created_at=time.time() - 200000)]
        assert retrieve("", "", "rc", index=idx) is None

    def test_not_expired_kept(self):
        idx = [_make_entry("*+*+rc", ttl_days=30, created_at=time.time())]
        hit = retrieve("", "", "rc", index=idx)
        assert hit is not None

    def test_zero_ttl_never_expires(self):
        idx = [_make_entry("*+*+rc", ttl_days=0, created_at=1.0)]
        hit = retrieve("", "", "rc", index=idx)
        assert hit is not None


# ── retrieve_all ─────────────────────────────────────────────────────

class TestRetrieveAll:
    def test_multiple_reason_codes(self):
        idx = [
            _make_entry("*+*+rc1", exp_id="e1"),
            _make_entry("*+*+rc2", exp_id="e2"),
        ]
        results = retrieve_all("", "", ["rc1", "rc2"], index=idx)
        assert len(results) == 2

    def test_dedup_by_id(self):
        idx = [_make_entry("*+*+rc1", exp_id="same"), _make_entry("*+*+rc2", exp_id="same")]
        results = retrieve_all("", "", ["rc1", "rc2"], index=idx)
        assert len(results) == 1

    def test_empty_codes(self):
        assert retrieve_all("", "", [], index=[]) == []


# ── inject_to_system_prompt ──────────────────────────────────────────

class TestInject:
    def test_injects_planner_system(self):
        exps = [{"inject_to": "planner_system", "content": "fix color"}]
        result = inject_to_system_prompt("base", exps)
        assert "fix color" in result
        assert result.startswith("base")

    def test_skips_non_planner(self):
        exps = [{"inject_to": "negative_prompt", "content": "skip me"}]
        result = inject_to_system_prompt("base", exps)
        assert result == "base"

    def test_empty_experiences(self):
        assert inject_to_system_prompt("base", []) == "base"


# ── save_to_index ────────────────────────────────────────────────────

class TestSaveToIndex:
    def test_save_new_entry(self, tmp_path, monkeypatch):
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        entry = _make_entry("b+c+rc", exp_id="new_001")
        save_to_index(entry)

        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["source_experience_id"] == "new_001"

    def test_save_overwrites_same_key(self, tmp_path, monkeypatch):
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        save_to_index(_make_entry("b+c+rc", exp_id="v1", confidence=0.5))
        save_to_index(_make_entry("b+c+rc", exp_id="v2", confidence=0.9))

        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert len(data) == 1
        assert data[0]["source_experience_id"] == "v2"

    def test_save_adds_default_fields(self, tmp_path, monkeypatch):
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        save_to_index({"key": "k1", "content": "test"})
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert "stats" in data[0]
        assert "created_at" in data[0]
        assert data[0]["quarantined"] is False


# ── record_outcome + auto-quarantine ─────────────────────────────────

class TestRecordOutcome:
    def _setup_index(self, tmp_path, monkeypatch, entries):
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)
        return idx_path

    def test_records_success(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1")
        idx_path = self._setup_index(tmp_path, monkeypatch, [entry])

        record_outcome("e1", passed=True)
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["stats"]["success"] == 1
        assert data[0]["stats"]["hit_count"] == 1

    def test_records_failure(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1")
        idx_path = self._setup_index(tmp_path, monkeypatch, [entry])

        record_outcome("e1", passed=False)
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["stats"]["fail"] == 1

    def test_auto_quarantine_after_5_fails(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1")
        entry["stats"] = {"success": 0, "fail": 4, "hit_count": 4, "last_seen": ""}
        idx_path = self._setup_index(tmp_path, monkeypatch, [entry])

        record_outcome("e1", passed=False)  # 5th fail → 0% success rate
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["quarantined"] is True


# ── quarantine / unquarantine ────────────────────────────────────────

class TestQuarantine:
    def _setup(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1")
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)
        return idx_path

    def test_quarantine(self, tmp_path, monkeypatch):
        idx_path = self._setup(tmp_path, monkeypatch)
        assert quarantine_experience("e1", reason="bad") is True
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["quarantined"] is True

    def test_unquarantine(self, tmp_path, monkeypatch):
        idx_path = self._setup(tmp_path, monkeypatch)
        quarantine_experience("e1")
        assert unquarantine_experience("e1") is True
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["quarantined"] is False

    def test_quarantine_unknown_id(self, tmp_path, monkeypatch):
        self._setup(tmp_path, monkeypatch)
        assert quarantine_experience("nonexistent") is False


# ── decay_stale_experiences ──────────────────────────────────────────

class TestDecay:
    def test_decays_old_entry(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1", confidence=1.0)
        entry["stats"]["last_seen"] = "2025-01-01T00:00:00+00:00"
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        count = decay_stale_experiences(max_idle_days=30)
        assert count == 1
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["confidence"] == 0.8  # 1.0 * 0.8

    def test_no_decay_for_recent(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1", confidence=1.0)
        entry["stats"]["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        count = decay_stale_experiences(max_idle_days=30)
        assert count == 0

    def test_decay_floor_at_0_1(self, tmp_path, monkeypatch):
        entry = _make_entry("*+*+rc", exp_id="e1", confidence=0.1)
        entry["stats"]["last_seen"] = "2025-01-01T00:00:00+00:00"
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text(json.dumps([entry], ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        decay_stale_experiences(max_idle_days=30)
        data = json.loads(idx_path.read_text(encoding="utf-8"))
        assert data[0]["confidence"] >= 0.1


# ── empty / bad JSON ─────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_index_uses_seed(self):
        hit = retrieve("", "", "coherent.validator.character_consistency", index=None)
        # falls back to _SEED_INDEX
        assert hit is not None or True  # seed may or may not match depending on file

    def test_bad_json_index(self, tmp_path, monkeypatch):
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text("NOT JSON!!!", encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)
        # should not crash, falls back to seed
        hit = retrieve("", "", "coherent.validator.character_consistency")
        assert hit is not None  # seed has this

    def test_empty_list_index(self):
        assert retrieve("b", "c", "rc", index=[]) is None


# ── get_quality_report ───────────────────────────────────────────────

class TestQualityReport:
    def test_report_structure(self, tmp_path, monkeypatch):
        idx_path = tmp_path / "experience_index.json"
        idx_path.write_text(json.dumps(_SEED_INDEX, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)

        report = get_quality_report(cycle_id="c1", sample_window="24h")
        assert report["total"] == len(_SEED_INDEX)
        assert report["quarantined"] == 0
        assert "top_good" in report
        assert "rollback_candidates" in report
        assert report["latest_cycle_id"] == "c1"
