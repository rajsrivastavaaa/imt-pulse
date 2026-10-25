"""Export one day's generated content from a table backup into demo/data.json for the static demo.

Only content is copied (stories, summaries, quizzes, company brief). No user data.
Usage: python3 scripts/build_demo_data.py backups/table-2026-10-22.json 2026-10-22
"""
import json
import sys

ITEM_KEYS = ("headline", "link", "source", "published", "summary", "why_it_matters")
QUIZ_KEYS = ("question", "options", "answer_index", "explanation")
COMPANY_KEYS = ("name", "what_it_does", "business_lines", "recent_news", "talking_points")


def plain(v):
    """DynamoDB JSON -> plain JSON."""
    (t, x), = v.items()
    if t == "M":
        return {k: plain(y) for k, y in x.items()}
    if t == "L":
        return [plain(y) for y in x]
    if t == "N":
        return int(x) if x.lstrip("-").isdigit() else float(x)
    if t == "NULL":
        return None
    return x


src, date = sys.argv[1], sys.argv[2]
rows = {i["SK"]["S"]: {k: plain(v) for k, v in i.items()}
        for i in json.load(open(src))["Items"] if i["PK"]["S"] == f"DAY#{date}"}
out = {"date": date, "tracks": {}, "company": None}
for sk, sec in rows.items():
    if sk.startswith("TRACK#") and not sec.get("error"):
        out["tracks"][sk.split("#")[1]] = {
            "stories": [{k: s[k] for k in ITEM_KEYS} for s in sec["stories"]],
            "quiz": [{k: q[k] for k in QUIZ_KEYS} for q in sec["quiz"]],
        }
    if sk == "COMPANY" and not sec.get("error"):
        out["company"] = {**{k: sec.get(k) for k in COMPANY_KEYS},
                          "quiz": [{k: q[k] for k in QUIZ_KEYS} for q in sec.get("quiz", [])]}
with open("demo/data.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print("wrote demo/data.json:", {t: len(v["stories"]) for t, v in out["tracks"].items()},
      "company:", out["company"] and out["company"]["name"])
