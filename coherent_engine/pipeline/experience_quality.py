#!/usr/bin/env python3
"""
Experience Quality CLI — makes the quality control layer runnable and auditable.

Usage:
    python -m coherent_engine.pipeline.experience_quality report
    python -m coherent_engine.pipeline.experience_quality report --cycle-id worker-42
    python -m coherent_engine.pipeline.experience_quality decay
    python -m coherent_engine.pipeline.experience_quality decay --max-idle-days 14
"""
import argparse
import json
import sys


def cmd_report(args):
    from coherent_engine.pipeline.experience_retrieval import generate_report
    report = generate_report(cycle_id=args.cycle_id, sample_window=args.sample_window)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nWritten to: experience_quality_latest.json")
    print(f"  total={report['total']}  active={report['active']}  quarantined={report['quarantined']}  "
          f"expired={report['expired']}  decayed={report['decayed']}  rollback_candidates={len(report['rollback_candidates'])}")


def cmd_decay(args):
    from coherent_engine.pipeline.experience_retrieval import decay_stale_experiences
    n = decay_stale_experiences(max_idle_days=args.max_idle_days)
    print(f"Decayed {n} stale experiences (idle > {args.max_idle_days} days)")


def cmd_quarantine(args):
    from coherent_engine.pipeline.experience_retrieval import quarantine_experience
    ok = quarantine_experience(args.experience_id, reason=args.reason)
    print(f"{'Quarantined' if ok else 'Not found'}: {args.experience_id}")


def cmd_unquarantine(args):
    from coherent_engine.pipeline.experience_retrieval import unquarantine_experience
    ok = unquarantine_experience(args.experience_id)
    print(f"{'Restored' if ok else 'Not found'}: {args.experience_id}")


def main():
    p = argparse.ArgumentParser(prog="experience_quality", description="Experience Quality Control CLI")
    sub = p.add_subparsers(dest="command")

    # report
    rp = sub.add_parser("report", help="Generate quality report and write experience_quality_latest.json")
    rp.add_argument("--cycle-id", default="", help="Cycle ID from worker/job_runner")
    rp.add_argument("--sample-window", default="", help="Sample window description")

    # decay
    dp = sub.add_parser("decay", help="Decay stale experiences")
    dp.add_argument("--max-idle-days", type=int, default=30, help="Days before decay (default: 30)")

    # quarantine
    qp = sub.add_parser("quarantine", help="Quarantine an experience")
    qp.add_argument("experience_id", help="Experience ID to quarantine")
    qp.add_argument("--reason", default="", help="Reason for quarantine")

    # unquarantine
    uq = sub.add_parser("unquarantine", help="Restore a quarantined experience")
    uq.add_argument("experience_id", help="Experience ID to restore")

    args = p.parse_args()
    if not args.command:
        p.print_help()
        return 1

    {"report": cmd_report, "decay": cmd_decay, "quarantine": cmd_quarantine, "unquarantine": cmd_unquarantine}[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
