#!/usr/bin/env python3
"""Project health verifier for TaijiOS.

This script is intentionally conservative: it checks importability, syntax,
tracked data files, high-signal static-analysis findings, key entrypoints, and
handoff artifacts without requiring external services.
"""

from __future__ import annotations

import argparse
import json
import os
import py_compile
import re
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PACKAGE_ROOTS = ("aios", "coherent_engine", "github_learning", "self_improving_loop", "worker")
SECRET_SCAN_ROOTS = (
    ".github",
    "aios",
    "coherent_engine",
    "docs",
    "examples",
    "github_learning",
    "scripts",
    "self_improving_loop",
    "tests",
    "worker",
)
SECRET_SCAN_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", "taijios.egg-info"}
HIGH_SIGNAL = re.compile(r"undefined name|redefinition|dictionary key|global _SHUTDOWN|traceback")
SECRET_LITERAL_PATTERNS = [
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),
    re.compile(r"xox[baprs]-"),
    re.compile("s" "k-" + r"[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token)\s*=\s*['\"][^'\"]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token)=[A-Za-z0-9_.-]{8,}"),
]
RUNTIME_TMP = ROOT / "data" / "test_tmp"


def run_command(name: str, command: list[str], *, high_signal_only: bool = False) -> bool:
    print(f"\n== {name} ==")
    print("$ " + " ".join(command))
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) if not existing_path else f"{ROOT}{os.pathsep}{existing_path}"
    RUNTIME_TMP.mkdir(parents=True, exist_ok=True)
    for name in ("TMP", "TEMP", "TMPDIR"):
        env[name] = str(RUNTIME_TMP)
    proc = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
    combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)

    if high_signal_only:
        if "No module named pyflakes" in combined:
            if combined.strip():
                print(combined.rstrip())
            print("FAIL: pyflakes is not installed")
            return False
        lines = [line for line in combined.splitlines() if line.strip()]
        matches = [line for line in lines if HIGH_SIGNAL.search(line)]
        print(f"pyflakes_findings_total={len(lines)}")
        print(f"pyflakes_high_signal_findings={len(matches)}")
        if matches:
            print("FAIL: high-signal pyflakes findings:")
            for line in matches:
                print(line)
            return False
        return True

    if combined.strip():
        print(combined.rstrip())

    if proc.returncode != 0:
        print(f"FAIL: {name} exited with {proc.returncode}")
        return False
    return True


def check_imports() -> bool:
    print("\n== full import scan ==")
    import importlib

    failures: list[tuple[str, str, str]] = []
    count = 0
    for root in PACKAGE_ROOTS:
        base = ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            module = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            if module.endswith(".__init__"):
                module = module[: -len(".__init__")]
            if module.endswith(".__main__"):
                continue
            count += 1
            try:
                importlib.import_module(module)
            except BaseException as exc:
                failures.append((module, type(exc).__name__, str(exc)))

    print(f"imported_candidates_all={count}")
    print(f"import_failures={len(failures)}")
    for module, typ, message in failures:
        print(f"IMPORT_FAIL {module} {typ}: {message}")
    return not failures


def check_compile() -> bool:
    print("\n== py_compile all local Python ==")
    files = [
        path
        for path in ROOT.rglob("*.py")
        if not any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)
    ]
    compile_root = ROOT / "runs" / "test_tmp" / "py_compile"
    errors: list[tuple[str, str]] = []
    for path in files:
        try:
            cfile = compile_root / path.relative_to(ROOT).with_suffix(".pyc")
            cfile.parent.mkdir(parents=True, exist_ok=True)
            py_compile.compile(str(path), cfile=str(cfile), doraise=True)
        except PermissionError as exc:
            errors.append((str(path.relative_to(ROOT)), str(exc)))
        except py_compile.PyCompileError as exc:
            errors.append((str(path.relative_to(ROOT)), exc.msg))

    print(f"python_files_all={len(files)}")
    print(f"compile_errors={len(errors)}")
    for path, message in errors:
        print(f"COMPILE_FAIL {path}: {message}")
    return not errors


def check_tracked_json() -> bool:
    print("\n== tracked JSON/JSONL parse ==")
    proc = subprocess.run(["git", "ls-files"], cwd=ROOT, text=True, capture_output=True)
    if proc.returncode != 0:
        print(proc.stderr.rstrip())
        return False

    failures: list[tuple[str, str, str]] = []
    checked = 0
    for raw in proc.stdout.splitlines():
        if not (raw.endswith(".json") or raw.endswith(".jsonl")):
            continue
        checked += 1
        path = ROOT / raw
        try:
            if raw.endswith(".json"):
                json.loads(path.read_text(encoding="utf-8"))
            else:
                for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                    if line.strip():
                        json.loads(line)
        except Exception as exc:
            failures.append((raw, type(exc).__name__, str(exc)))

    print(f"tracked_json_files_checked={checked}")
    print(f"json_parse_failures={len(failures)}")
    for path, typ, message in failures:
        print(f"JSON_FAIL {path} {typ}: {message}")
    return not failures


def check_handoff_artifacts() -> bool:
    print("\n== handoff artifact parse ==")
    base = ROOT / "runs" / "cross_machine_handoff"
    failures: list[str] = []
    checked = 0
    if not base.exists():
        print("handoff_dir_missing=true")
        return True

    for event_flow in base.glob("*/event_flow.jsonl"):
        checked += 1
        for line_number, line in enumerate(event_flow.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                failures.append(f"{event_flow.relative_to(ROOT)}:{line_number}: {exc}")

    for summary in base.glob("*/verification_summary.json"):
        checked += 1
        try:
            json.loads(summary.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{summary.relative_to(ROOT)}: {exc}")

    print(f"handoff_files_checked={checked}")
    print(f"handoff_parse_failures={len(failures)}")
    for failure in failures:
        print(f"HANDOFF_FAIL {failure}")
    return not failures


def check_secret_literals() -> bool:
    print("\n== secret literal scan ==")
    failures: list[str] = []
    checked = 0
    for root_name in SECRET_SCAN_ROOTS:
        base = ROOT / root_name
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(ROOT)
            if any(part in SKIP_PARTS for part in rel.parts):
                continue
            if path.suffix.lower() not in SECRET_SCAN_SUFFIXES:
                continue
            checked += 1
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_number, line in enumerate(text.splitlines(), 1):
                if any(pattern.search(line) for pattern in SECRET_LITERAL_PATTERNS):
                    failures.append(f"{rel}:{line_number}: {line.strip()}")

    print(f"secret_literal_files_checked={checked}")
    print(f"secret_literal_findings={len(failures)}")
    for failure in failures:
        print(f"SECRET_LITERAL_FAIL {failure}")
    return not failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run TaijiOS project health checks.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--skip-entrypoints", action="store_true")
    args = parser.parse_args(argv)

    checks: list[tuple[str, bool]] = []
    if not args.skip_tests:
        pytest_basetemp = RUNTIME_TMP / f"pytest-{os.getpid()}-{time.time_ns()}"
        checks.append((
            "pytest",
            run_command(
                "pytest",
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/",
                    "-q",
                    "--tb=short",
                    "--basetemp",
                    str(pytest_basetemp),
                ],
            ),
        ))
    checks.append(("imports", check_imports()))
    checks.append(("compile", check_compile()))
    checks.append(("tracked_json", check_tracked_json()))
    checks.append(("handoff", check_handoff_artifacts()))
    checks.append(("secret_literals", check_secret_literals()))
    checks.append((
        "pyflakes_high_signal",
        run_command(
            "pyflakes high-signal scan",
            [
                sys.executable,
                "-m",
                "pyflakes",
                "aios",
                "coherent_engine",
                "github_learning",
                "self_improving_loop",
                "worker",
                "examples",
                "tests",
            ],
            high_signal_only=True,
        ),
    ))

    if not args.skip_entrypoints:
        checks.extend([
            (
                "gateway_help",
                run_command("gateway help", [sys.executable, "-m", "aios.gateway", "--help"]),
            ),
            (
                "quickstart",
                run_command("quickstart", [sys.executable, "examples/quickstart_minimal.py"]),
            ),
            (
                "gui_agent_ops_check_gate",
                run_command(
                    "GUI agent ops-check gate",
                    [sys.executable, "-m", "aios.gui_agent.ops_check_gate"],
                ),
            ),
            (
                "gui_agent_ops_check_validate",
                run_command(
                    "GUI agent ops-check validator",
                    [sys.executable, "examples/validate_gui_agent_ops_check.py"],
                ),
            ),
            (
                "deepseek_iching_dry_run",
                run_command(
                    "DeepSeek I Ching dry-run",
                    [sys.executable, "examples/deepseek_iching_64.py"],
                ),
            ),
            (
                "deepseek_iching_validate",
                run_command(
                    "DeepSeek I Ching validator",
                    [sys.executable, "examples/validate_deepseek_iching_64.py"],
                ),
            ),
            (
                "worker_dry_run",
                run_command(
                    "worker dry-run",
                    [
                        sys.executable,
                        "-m",
                        "worker",
                        "--max-cycles",
                        "1",
                        "--interval",
                        "999",
                        "--dry-run",
                        "--skip-learning",
                        "--skip-jobs",
                        "--data-dir",
                        "data/worker_smoke",
                    ],
                ),
            ),
        ])

    failed = [name for name, ok in checks if not ok]
    print("\n== summary ==")
    print(f"checks_run={len(checks)}")
    print(f"checks_failed={len(failed)}")
    for name in failed:
        print(f"FAILED {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
