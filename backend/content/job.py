"""Daily content job (EventBridge Scheduler, 05:30 IST). Also invoked by the admin "Generate now" button.

Event: {"date": "YYYY-MM-DD"} (optional, defaults to today IST), {"force": true} to also replace
sections the admin already edited/approved.
"""
from common import TRACKS, now_ist, table, to_ddb, today_ist

from . import llm
from .feeds import fetch_recent
from .generate import build_day


def handler(event, context):
    event = event or {}
    llm.USAGE.clear()   # warm Lambda containers keep module state between runs
    date = event.get("date") or today_ist()
    t = table()
    sched = t.get_item(Key={"PK": "SCHEDULE", "SK": date}).get("Item")
    company = None
    if sched:
        company = {"name": sched["name"], "process_date": sched.get("process_date", ""),
                   "aliases": [a for a in sched.get("aliases", "").split(",") if a.strip()],
                   "notes": sched.get("notes", "")}

    items = fetch_recent(max_age_hours=36)
    day = build_day(date, items, company)

    existing = {i["SK"]: i for i in t.query(
        KeyConditionExpression="PK = :p", ExpressionAttributeValues={":p": f"DAY#{date}"})["Items"]}
    stamp = now_ist().isoformat()
    written, kept = [], []

    def save(sk, section):
        old = existing.get(sk)
        if old and (old.get("edited") or old.get("status") == "approved") and not event.get("force"):
            kept.append(sk)
            return
        t.put_item(Item=to_ddb({"PK": f"DAY#{date}", "SK": sk, "date": date, "status": "draft",
                                "edited": False, "generated_at": stamp, **section}))
        written.append(sk)

    for track in TRACKS:
        save(f"TRACK#{track}", day["tracks"].get(track) or {"error": "not generated", "stories": [], "quiz": []})
    if day["company"]:
        save("COMPANY", day["company"])

    usage = {m.split(".")[2] if m.count(".") >= 2 else m: u for m, u in llm.USAGE.items()}
    t.put_item(Item=to_ddb({"PK": f"DAY#{date}", "SK": "META", "generated_at": stamp, "feed_items": len(items),
                            "usage": usage, "written": written, "kept": kept}))
    result = {"date": date, "items": len(items), "written": written, "kept": kept, "usage": usage}
    print(result)
    return result
