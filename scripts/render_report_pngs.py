"""Regenerate committed report PNG(s) from the current DB (used by the daily cron).

Kept separate from the notebooks so the at-a-glance images refresh even headlessly.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import report  # noqa: E402

out = ROOT / "reports" / "01_group_breakdown.png"
report.render_group_breakdown().savefig(out, dpi=110, bbox_inches="tight")
print(f"regenerated {out.relative_to(ROOT)}")
