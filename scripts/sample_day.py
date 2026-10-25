"""Generate one day's content locally (no database) and save it to samples/ for review.

Usage (from the project folder):
  .venv/bin/python scripts/sample_day.py 2026-10-22 --company "Hindustan Unilever" --process-date 2026-10-28
  .venv/bin/python scripts/sample_day.py 2026-10-21 --min-age 24 --max-age 60   # an older news window
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from content import llm  # noqa: E402
from content.feeds import fetch_recent  # noqa: E402
from content.generate import build_day  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("date")
ap.add_argument("--company")
ap.add_argument("--process-date", default="")
ap.add_argument("--aliases", default="", help="comma-separated, e.g. HUL")
ap.add_argument("--notes", default="")
ap.add_argument("--min-age", type=float, default=0)
ap.add_argument("--max-age", type=float, default=36)
a = ap.parse_args()

t0 = time.time()
items = fetch_recent(max_age_hours=a.max_age, min_age_hours=a.min_age)
print(f"{len(items)} feed items")
company = {"name": a.company, "process_date": a.process_date, "aliases": a.aliases.split(","), "notes": a.notes} if a.company else None
day = build_day(a.date, items, company)
day["date"] = a.date
# Approximate on-demand list prices, USD per million tokens (input, output); check the Bedrock pricing page.
PRICES = {"haiku": (1, 5), "sonnet": (3, 15)}
cost = 0
for model, u in llm.USAGE.items():
    pin, pout = next(v for k, v in PRICES.items() if k in model)
    u["approx_usd"] = round(u["input"] / 1e6 * pin + u["output"] / 1e6 * pout, 4)
    cost += u["approx_usd"]
day["_run"] = {"models": llm.USAGE, "items": len(items), "seconds": round(time.time() - t0),
               "calls": sum(u["calls"] for u in llm.USAGE.values()), "approx_usd": round(cost, 4)}
os.makedirs("samples", exist_ok=True)
path = f"samples/{a.date}.json"
with open(path, "w") as f:
    json.dump(day, f, indent=1, ensure_ascii=False)
print(json.dumps(day["_run"]), "->", path)
for t, s in day["tracks"].items():
    print(t, "ERROR " + s["error"] if s.get("error") else f'{len(s["stories"])} stories, {len(s["quiz"])} q')
if day["company"]:
    print("company", day["company"].get("error") or "ok")
