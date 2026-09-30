"""Run available offline analyses in an isolated output directory."""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AUDIT = ROOT / "experiments/results/audits"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("reproduction"))
    parser.add_argument("--figures", action="store_true")
    args = parser.parse_args()
    out = args.output_dir.resolve()
    if out == ROOT or out in AUDIT.parents or AUDIT == out or AUDIT in out.parents:
        parser.error("Choose a separate output directory outside the supplied evidence tree")
    if out.exists() and any(out.iterdir()):
        parser.error("Output directory must be new or empty")
    out.mkdir(parents=True, exist_ok=True)
    target = out / "audits"
    shutil.copytree(AUDIT, target)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MPLCONFIGDIR=str(out / "matplotlib-cache"))
    commands = [("frozen_counts", ROOT / "scripts/verify_frozen_counts.py"),
                ("coverage_matched_null", target / "null_gate_control.py"),
                ("task_clustered_sensitivity", target / "task_clustered_sensitivity.py"),
                ("archived_outcome_reaggregation", target / "replay_aggregate_tables.py")]
    if args.figures:
        commands.append(("analysis_figure_redraw", target / "make_figures.py"))
    results = []
    for label, script in commands:
        run = subprocess.run([sys.executable, str(script)], cwd=script.parent, env=env,
                             text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out / (label + ".txt")).write_text(run.stdout)
        print(label + ": " + ("passed" if run.returncode == 0 else "FAILED"), flush=True)
        results.append({"analysis": label, "exit_code": run.returncode})
        if run.returncode:
            print(run.stdout)
            raise SystemExit(run.returncode)
    produced = target / "analysis_tables/paired_deltas_mimo_task_clustered.csv"
    original = AUDIT / "analysis_tables/paired_deltas_mimo_task_clustered.csv"
    if produced.read_bytes() != original.read_bytes():
        raise ValueError("Regenerated task-clustered CSV differs from supplied reference")
    report = {"status": "available offline analyses passed", "checks": results,
              "clustered_csv_matches": True,
              "limits": "No independent legal-label validation or end-to-end provider reconstruction."}
    (out / "reproduction_report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
