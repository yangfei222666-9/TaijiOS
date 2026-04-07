"""
GitHub Learning Pipeline — CLI orchestrator.
Usage:
    python -m github_learning discover [--limit N] [--dry-run]
    python -m github_learning analyze [--limit N] [--dry-run]
    python -m github_learning digest
    python -m github_learning gate list|review|approve|reject <id> [--note/--reason]
    python -m github_learning solidify
    python -m github_learning auto [--limit N]
"""
import argparse
import sys


def main():
    p = argparse.ArgumentParser(prog="github_learning")
    sub = p.add_subparsers(dest="command")

    # discover
    d = sub.add_parser("discover", help="Search GitHub for relevant repos")
    d.add_argument("--limit", type=int, default=30)
    d.add_argument("--dry-run", action="store_true")

    # analyze
    a = sub.add_parser("analyze", help="Analyze discovered repos with LLM")
    a.add_argument("--limit", type=int, default=10)
    a.add_argument("--repo", type=str, default="")
    a.add_argument("--dry-run", action="store_true")

    # digest
    sub.add_parser("digest", help="Extract mechanisms from analyses")

    # gate
    g = sub.add_parser("gate", help="Human review gate")
    g.add_argument("action", choices=["list", "review", "approve", "reject", "quality", "worker"])
    g.add_argument("id", nargs="?", default="")
    g.add_argument("--note", type=str, default="")
    g.add_argument("--reason", type=str, default="")
    g.add_argument("--window", type=int, default=24, help="Worker check window in hours")

    # solidify
    sub.add_parser("solidify", help="Solidify approved mechanisms")

    # auto
    au = sub.add_parser("auto", help="Run discover+analyze+digest")
    au.add_argument("--limit", type=int, default=10)

    args = p.parse_args()
    if not args.command:
        p.print_help()
        return 1

    if args.command == "discover":
        from .discoverer import discover
        discover(limit=args.limit, dry_run=args.dry_run)

    elif args.command == "analyze":
        from .analyzer import analyze_all, analyze_repo
        if args.repo:
            import json
            repo_data = {"full_name": args.repo, "description": "", "stars": 0,
                         "language": "", "readme_excerpt": ""}
            result = analyze_repo(repo_data, dry_run=args.dry_run)
            if result:
                print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        else:
            analyze_all(limit=args.limit, dry_run=args.dry_run)

    elif args.command == "digest":
        from .digester import digest_all
        digest_all()

    elif args.command == "gate":
        from . import gate as g_mod
        if args.action == "list":
            g_mod.print_pending()
        elif args.action == "review":
            if not args.id:
                print("Usage: gate review <mechanism_id>")
                return 1
            g_mod.print_review(args.id)
        elif args.action == "approve":
            if not args.id:
                print("Usage: gate approve <mechanism_id>")
                return 1
            g_mod.approve(args.id, note=args.note)
        elif args.action == "reject":
            if not args.id:
                print("Usage: gate reject <mechanism_id>")
                return 1
            g_mod.reject(args.id, reason=args.reason)
        elif args.action == "quality":
            g_mod.print_quality()
        elif args.action == "worker":
            g_mod.print_worker(window_hours=args.window)

    elif args.command == "solidify":
        from .solidifier import solidify_all
        solidify_all()

    elif args.command == "auto":
        from .discoverer import discover
        from .analyzer import analyze_all
        from .digester import digest_all
        print("=== Step 1: Discover ===")
        discover(limit=args.limit)
        print("\n=== Step 2: Analyze ===")
        analyze_all(limit=args.limit)
        print("\n=== Step 3: Digest ===")
        digest_all()
        print("\nAuto pipeline complete. Run 'gate list' to review pending mechanisms.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
