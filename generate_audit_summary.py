#!/usr/bin/env python3
"""Generate audit summary outputs from existing audit-report.json files.

Reads all *-audit-report.json files and produces (per agency directory):
  - audit-batch-results.json  (same format as run_audit_multi_project.py)
  - AUDITOR-REPORT.md         (same format as run_audit_multi_project.py)

Also produces overall files in the root directory.

Usage:
    python generate_audit_summary.py /path/to/auditor-run
    python generate_audit_summary.py .
"""

import argparse
import json
import sys
import time
from pathlib import Path


def read_audit_report(path: Path) -> dict:
    """Read an audit report JSON and return a result dict matching
    the format from run_audit_multi_project.py."""
    slug = path.parent.name
    try:
        with open(path, encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {
            "slug": slug,
            "status": "fail",
            "error": str(e),
            "elapsed": 0,
        }

    return {
        "slug": slug,
        "score": report.get("quality_score"),
        "routing": report.get("routing", "unknown"),
        "method": report.get("decision_method", "unknown"),
        "concerns": len(report.get("concerns", [])),
        "status": "ok",
        "elapsed": 0,
        # Extra fields not in the original but useful
        "quality_grade": report.get("quality_grade"),
        "fidelity_composite": report.get("fidelity_composite"),
        "total_defects": report.get("total_defects", 0),
        "total_critical": report.get("total_critical", 0),
        "total_major": report.get("total_major", 0),
        "total_minor": report.get("total_minor", 0),
        "exclusion_reason": report.get("exclusion_reason"),
        "routing_changed": report.get("routing_changed", False),
    }


def generate_report(results: list[dict], input_dir: Path) -> str:
    """Generate AUDITOR-REPORT.md content.
    Matches the format from run_audit_multi_project.py exactly."""
    ok_results = [r for r in results if r["status"] == "ok"]
    fail_results = [r for r in results if r["status"] != "ok"]

    # Routing distribution
    routing_counts = {}
    for r in ok_results:
        routing = r["routing"]
        routing_counts[routing] = routing_counts.get(routing, 0) + 1

    # Score distribution
    scores = [r["score"] for r in ok_results if isinstance(r["score"], (int, float))]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Grade distribution
    grade_counts = {"Good": 0, "Fair": 0, "Poor": 0, "Critical": 0}
    for s in scores:
        if s >= 90:
            grade_counts["Good"] += 1
        elif s >= 70:
            grade_counts["Fair"] += 1
        elif s >= 50:
            grade_counts["Poor"] += 1
        else:
            grade_counts["Critical"] += 1

    # Concern statistics
    total_concerns = sum(r.get("concerns", 0) for r in ok_results)

    lines = []
    lines.append("# Auditor Report")
    lines.append("")
    lines.append(f"**Batch**: `{input_dir.name}`")
    lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Total documents**: {len(results)}")
    lines.append(f"**Successful**: {len(ok_results)}")
    lines.append(f"**Failed/Timeout**: {len(fail_results)}")
    lines.append("")

    lines.append("## Summary Statistics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|--------|-------|")
    lines.append(f"| Average Score | {avg_score:.1f} |")
    lines.append(f"| Total Concerns | {total_concerns} |")
    if ok_results:
        lines.append(f"| Avg Concerns/Doc | {total_concerns/len(ok_results):.1f} |")
    lines.append("")

    lines.append("## Grade Distribution")
    lines.append("")
    lines.append("| Grade | Score Range | Count | % |")
    lines.append("|-------|-----------|-------|---|")
    for grade, range_str in [("Good", "90-100"), ("Fair", "70-89"), ("Poor", "50-69"), ("Critical", "0-49")]:
        count = grade_counts[grade]
        pct = (count / len(ok_results) * 100) if ok_results else 0
        lines.append(f"| {grade} | {range_str} | {count} | {pct:.0f}% |")
    lines.append("")

    lines.append("## Routing Distribution")
    lines.append("")
    lines.append("| Routing | Count | % |")
    lines.append("|---------|-------|---|")
    for routing in ["auto_approve", "human_review", "reject", "excluded"]:
        count = routing_counts.get(routing, 0)
        pct = (count / len(ok_results) * 100) if ok_results else 0
        lines.append(f"| {routing} | {count} | {pct:.0f}% |")
    lines.append("")

    # Problem documents (reject + low scores)
    problem_docs = sorted(
        [r for r in ok_results if r["routing"] == "reject" or (isinstance(r["score"], (int, float)) and r["score"] < 70)],
        key=lambda r: r.get("score", 0)
    )
    if problem_docs:
        lines.append("## Problem Documents (Reject or Score < 70)")
        lines.append("")
        lines.append("| Document | Score | Routing | Concerns |")
        lines.append("|----------|-------|---------|----------|")
        for r in problem_docs:
            lines.append(f"| {r['slug']} | {r['score']} | {r['routing']} | {r['concerns']} |")
        lines.append("")

    # All results table
    lines.append("## All Results")
    lines.append("")
    lines.append("| # | Document | Score | Routing | Method | Concerns |")
    lines.append("|---|----------|-------|---------|--------|----------|")
    for i, r in enumerate(sorted(ok_results, key=lambda x: x["slug"]), 1):
        lines.append(
            f"| {i} | {r['slug']} | {r['score']} | {r['routing']} | "
            f"{r['method']} | {r['concerns']} |"
        )
    lines.append("")

    if fail_results:
        lines.append("## Failed Documents")
        lines.append("")
        lines.append("| Document | Status | Error |")
        lines.append("|----------|--------|-------|")
        for r in fail_results:
            error = r.get("error", "")[:100]
            lines.append(f"| {r['slug']} | {r['status']} | {error} |")
        lines.append("")

    return "\n".join(lines)


def find_agency_dirs(root: Path) -> list[Path]:
    """Find agency directories (immediate subdirectories with audit reports)."""
    agencies = []
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        reports = list(d.rglob("*-audit-report.json"))
        if reports:
            agencies.append(d)
    return agencies


def collect_reports(directory: Path) -> list[dict]:
    """Recursively find and read all audit reports under a directory."""
    report_paths = sorted(directory.rglob("*-audit-report.json"))
    results = []
    for rp in report_paths:
        result = read_audit_report(rp)
        results.append(result)
    return results


def write_outputs(directory: Path, results: list[dict]) -> None:
    """Write audit-batch-results.json and AUDITOR-REPORT.md to the directory."""
    ok = [r for r in results if r["status"] == "ok"]
    fail = [r for r in results if r["status"] != "ok"]

    # audit-batch-results.json
    batch_json = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "input_dir": str(directory),
        "total_docs": len(results),
        "ok": len(ok),
        "failed": len(fail),
        "results": results,
    }
    json_path = directory / "audit-batch-results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(batch_json, f, indent=2)

    # AUDITOR-REPORT.md
    report_content = generate_report(results, directory)
    md_path = directory / "AUDITOR-REPORT.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate audit-batch-results.json and AUDITOR-REPORT.md "
                    "from existing audit-report.json files.",
    )
    parser.add_argument(
        "input_dir", type=Path, nargs="?", default=Path("."),
        help="Root directory containing agency subdirectories (default: .)",
    )
    args = parser.parse_args()

    root = args.input_dir.resolve()
    if not root.exists():
        print(f"Error: {root} not found", file=sys.stderr)
        sys.exit(1)

    agency_dirs = find_agency_dirs(root)
    if not agency_dirs:
        reports = collect_reports(root)
        if reports:
            agency_dirs = [root]
        else:
            print(f"No audit reports found under {root}", file=sys.stderr)
            sys.exit(1)

    print(f"Found {len(agency_dirs)} agencies under {root}\n")

    all_results = []

    for agency_dir in agency_dirs:
        agency_name = agency_dir.name
        results = collect_reports(agency_dir)
        write_outputs(agency_dir, results)

        ok = [r for r in results if r["status"] == "ok"]
        scores = [r["score"] for r in ok if isinstance(r["score"], (int, float))]
        avg = sum(scores) / len(scores) if scores else 0

        routing_counts = {}
        for r in ok:
            routing_counts[r["routing"]] = routing_counts.get(r["routing"], 0) + 1

        print(
            f"  {agency_name:15s}  {len(results):4d} docs  "
            f"avg={avg:5.1f}  "
            f"approve={routing_counts.get('auto_approve', 0)}  "
            f"review={routing_counts.get('human_review', 0)}  "
            f"reject={routing_counts.get('reject', 0)}  "
            f"excluded={routing_counts.get('excluded', 0)}"
        )

        all_results.extend(results)

    # Overall outputs at root
    if len(agency_dirs) > 1:
        write_outputs(root, all_results)

        ok = [r for r in all_results if r["status"] == "ok"]
        scores = [r["score"] for r in ok if isinstance(r["score"], (int, float))]
        avg = sum(scores) / len(scores) if scores else 0

        routing_counts = {}
        for r in ok:
            routing_counts[r["routing"]] = routing_counts.get(r["routing"], 0) + 1

        print(f"\n{'='*70}")
        print(f"Overall: {len(all_results)} documents, avg score={avg:.1f}")
        print(f"  Routing: {routing_counts}")
        print(f"\nOutputs written per directory:")
        for agency_dir in agency_dirs:
            print(f"  {agency_dir}/audit-batch-results.json")
            print(f"  {agency_dir}/AUDITOR-REPORT.md")
        print(f"  {root}/audit-batch-results.json")
        print(f"  {root}/AUDITOR-REPORT.md")


if __name__ == "__main__":
    main()
