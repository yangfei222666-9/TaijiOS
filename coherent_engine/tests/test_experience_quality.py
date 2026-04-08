"""experience_quality CLI tests — report, decay, quarantine, unquarantine, no-command."""
import json
import pytest
from unittest.mock import patch
from coherent_engine.pipeline.experience_quality import main, cmd_report, cmd_decay, cmd_quarantine, cmd_unquarantine
from coherent_engine.pipeline.experience_retrieval import _SEED_INDEX


def _setup_index(tmp_path, monkeypatch):
    idx_path = tmp_path / "experience_index.json"
    idx_path.write_text(json.dumps(_SEED_INDEX, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._INDEX_PATH", idx_path)
    rpt_path = tmp_path / "experience_quality_latest.json"
    monkeypatch.setattr("coherent_engine.pipeline.experience_retrieval._REPORT_PATH", rpt_path)
    return idx_path, rpt_path


class TestCmdReport:
    def test_report_prints_json(self, tmp_path, monkeypatch, capsys):
        _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "report", "--cycle-id", "c1"])
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "total" in out
        assert "c1" in out

    def test_report_writes_file(self, tmp_path, monkeypatch, capsys):
        _, rpt_path = _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "report"])
        main()
        assert rpt_path.exists()
        data = json.loads(rpt_path.read_text(encoding="utf-8"))
        assert data["total"] == len(_SEED_INDEX)


class TestCmdDecay:
    def test_decay_output(self, tmp_path, monkeypatch, capsys):
        _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "decay", "--max-idle-days", "30"])
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Decayed" in out

    def test_decay_custom_days(self, tmp_path, monkeypatch, capsys):
        _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "decay", "--max-idle-days", "7"])
        main()
        out = capsys.readouterr().out
        assert "7 days" in out


class TestCmdQuarantine:
    def test_quarantine_existing(self, tmp_path, monkeypatch, capsys):
        _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "quarantine", "seed_001", "--reason", "test"])
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Quarantined" in out

    def test_quarantine_unknown(self, tmp_path, monkeypatch, capsys):
        _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "quarantine", "nonexistent"])
        main()
        out = capsys.readouterr().out
        assert "Not found" in out


class TestCmdUnquarantine:
    def test_unquarantine_existing(self, tmp_path, monkeypatch, capsys):
        idx_path, _ = _setup_index(tmp_path, monkeypatch)
        # first quarantine it
        monkeypatch.setattr("sys.argv", ["eq", "quarantine", "seed_001"])
        main()
        # then restore
        monkeypatch.setattr("sys.argv", ["eq", "unquarantine", "seed_001"])
        rc = main()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Restored" in out

    def test_unquarantine_unknown(self, tmp_path, monkeypatch, capsys):
        _setup_index(tmp_path, monkeypatch)
        monkeypatch.setattr("sys.argv", ["eq", "unquarantine", "nonexistent"])
        main()
        out = capsys.readouterr().out
        assert "Not found" in out


class TestNoCommand:
    def test_no_command_returns_1(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["eq"])
        rc = main()
        assert rc == 1
