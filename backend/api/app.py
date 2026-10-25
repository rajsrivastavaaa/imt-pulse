"""HTTP API for the PWA. One Lambda, routed on `routeKey`. All routes need a Cognito ID token (JWT authorizer).

Quiz integrity: answers never leave the server before a question is answered, each question is timed
from when the server served it, and an attempt can be answered once per question, once per day.
"""
import json
import os
import random
import time
import traceback
from collections import defaultdict
from datetime import datetime, timedelta

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import (TRACKS, display_name, is_published, now_ist, plain, quiz_open, speed_bonus,
                    streak_multiplier, table, today_ist, week_dates)

EVENT_TYPES = {"app_open", "story_open", "results_shared"}
EVENT_TTL_DAYS = 180
LB_CACHE_SECS = 30
_lb_cache = {}


class HttpError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


def resp(status, body):
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(plain(body))}


# ---------- users ----------

def claims_of(event):
    return event["requestContext"]["authorizer"]["jwt"]["claims"]


def is_admin(claims):
    return "admin" in str(claims.get("cognito:groups", ""))


def get_profile(claims):
    sub = claims["sub"]
    t = table()
    item = t.get_item(Key={"PK": f"USER#{sub}", "SK": "PROFILE"}).get("Item")
    if item:
        return item
    first, last = claims.get("given_name", ""), claims.get("family_name", "")
    item = {
        "PK": f"USER#{sub}", "SK": "PROFILE", "sub": sub, "email": claims.get("email", ""),
        "first": first, "last": last, "display_name": display_name(first, last),
        "batch": claims.get("custom:batch", ""), "track": None, "onboarded": False, "hidden": False,
        "streak": 0, "best_streak": 0, "last_quiz_date": None, "total_score": 0, "quizzes": 0,
        "first_seen": today_ist(), "created_at": now_ist().isoformat(),
    }
    try:
        t.put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        item = t.get_item(Key={"PK": f"USER#{sub}", "SK": "PROFILE"})["Item"]
    return item


def public_profile(p, claims):
    keys = ["email", "first", "last", "display_name", "batch", "track", "onboarded", "hidden",
            "streak", "best_streak", "last_quiz_date", "total_score", "quizzes"]
    out = {k: p.get(k) for k in keys}
    # A streak only counts as current if the last quiz was today or yesterday.
    yesterday = (datetime.fromisoformat(today_ist()) - timedelta(days=1)).date().isoformat()
    if p.get("last_quiz_date") not in (today_ist(), yesterday):
        out["streak"] = 0
    out["is_admin"] = is_admin(claims)
    return out


def get_me(event, claims, body):
    return public_profile(get_profile(claims), claims)


def put_me(event, claims, body):
    p = get_profile(claims)
    updates = {}
    if "track" in body:
        if body["track"] not in TRACKS:
            raise HttpError(400, "Unknown track")
        updates["track"] = body["track"]
    if "display_name" in body:
        name = str(body["display_name"]).strip()
        if not 2 <= len(name) <= 30:
            raise HttpError(400, "Display name must be 2-30 characters")
        updates["display_name"] = name
    if "hidden" in body:
        updates["hidden"] = bool(body["hidden"])
    if body.get("onboarded"):
        if not (updates.get("track") or p.get("track")):
            raise HttpError(400, "Pick a track first")
        updates["onboarded"] = True
    if updates:
        expr = "SET " + ", ".join(f"#{k} = :{k}" for k in updates)
        table().update_item(Key={"PK": p["PK"], "SK": "PROFILE"}, UpdateExpression=expr,
                            ExpressionAttributeNames={f"#{k}": k for k in updates},
                            ExpressionAttributeValues={f":{k}": v for k, v in updates.items()})
        p.update(updates)
        _lb_cache.clear()
    return public_profile(p, claims)


# ---------- content ----------

def day_sections(date):
    items = table().query(KeyConditionExpression=Key("PK").eq(f"DAY#{date}"))["Items"]
    return {i["SK"]: i for i in items}


def public_company(c):
    if not c or c.get("error"):
        return None
    keys = ["name", "process_date", "what_it_does", "business_lines", "recent_news", "talking_points"]
    return {k: c.get(k) for k in keys}


def get_today(event, claims, body):
    p = get_profile(claims)
    date = today_ist()
    admin = is_admin(claims)
    qs = event.get("queryStringParameters") or {}
    track = qs.get("track") if qs.get("track") in TRACKS else (p.get("track") or "marketing")
    out = {"date": date, "track": track, "published": is_published(date), "preview": False}
    if not out["published"] and not admin:
        out["opens_at"] = "08:00 IST"
        return out
    out["preview"] = not out["published"]
    secs = day_sections(date)
    sec = secs.get(f"TRACK#{track}") or {}
    out["stories"] = [{k: s[k] for k in ("id", "headline", "link", "source", "published", "summary", "why_it_matters")}
                      for s in sec.get("stories", [])]
    out["company"] = public_company(secs.get("COMPANY"))
    out["quiz"] = quiz_status(p, date, secs)
    return out


def build_questions(track, secs):
    """[(qid, question_with_answer)] for a user's daily quiz: their track's 5 + company 2-3."""
    qs = []
    tsec = secs.get(f"TRACK#{track}") or {}
    if not tsec.get("error"):
        qs += [(f"t{n}", q) for n, q in enumerate(tsec.get("quiz", []))]
    c = secs.get("COMPANY") or {}
    if not c.get("error"):
        qs += [(f"c{n}", q) for n, q in enumerate(c.get("quiz", []))]
    return qs


def attempt_key(sub, date):
    return {"PK": f"USER#{sub}", "SK": f"ATTEMPT#{date}"}


def get_attempt(sub, date):
    return table().get_item(Key=attempt_key(sub, date), ConsistentRead=True).get("Item")


def quiz_status(p, date, secs):
    a = get_attempt(p["sub"], date)
    if a and a.get("finished_at"):
        return {"state": "done", "score": a["score"], "correct": a["correct_count"], "total": len(a["qids"])}
    if not quiz_open(date):
        return {"state": "closed"}
    n = len(build_questions(a["track"] if a else (p.get("track") or "marketing"), secs))
    if n == 0:
        return {"state": "unavailable"}
    if a:
        return {"state": "in_progress", "answered": len(a.get("answers", {})), "total": len(a["qids"])}
    return {"state": "not_started", "total": n}


def question_payload(a, qmap, qid):
    q = qmap[qid]
    return {"qid": qid, "index": a["qids"].index(qid), "total": len(a["qids"]),
            "kind": "company" if qid.startswith("c") else "track",
            "question": q["question"], "options": q["options"]}


def next_qid(a):
    done = a.get("answers", {})
    return next((q for q in a["qids"] if q not in done), None)


def serve(a, qid):
    """Record when a question was first shown (timer starts on the server)."""
    if qid in a.get("served", {}):
        return
    stamp = str(time.time())
    try:
        table().update_item(Key=attempt_key(a["sub"], a["date"]), UpdateExpression="SET served.#q = :t",
                            ConditionExpression="attribute_not_exists(served.#q)",
                            ExpressionAttributeNames={"#q": qid}, ExpressionAttributeValues={":t": stamp})
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        stamp = get_attempt(a["sub"], a["date"])["served"][qid]   # served by a parallel request
    a.setdefault("served", {})[qid] = stamp


def log_event(sub, kind, meta=None):
    now = now_ist()
    table().put_item(Item={
        "PK": f"EVENT#{now.date().isoformat()}", "SK": f"{now.isoformat()}#{sub}#{random.randint(0, 99999)}",
        "type": kind, "sub": sub, "meta": json.dumps(meta or {})[:500],
        "ttl": int(time.time()) + EVENT_TTL_DAYS * 86400})


def quiz_start(event, claims, body):
    p = get_profile(claims)
    date = today_ist()
    if not (quiz_open(date) or (is_admin(claims) and date == today_ist())):
        raise HttpError(409, "The quiz is open from 08:00 to 23:59 IST.")
    a = get_attempt(p["sub"], date)
    if a and a.get("finished_at"):
        return {"finished": True, "result": result_payload(a, p)}
    secs = day_sections(date)
    if not a:
        track = p.get("track") or "marketing"
        qs = build_questions(track, secs)
        if not qs:
            raise HttpError(409, "Today's quiz isn't available.")
        # Freeze the questions in the attempt, so a content regeneration mid-quiz can't change them.
        a = {**attempt_key(p["sub"], date), "sub": p["sub"], "date": date, "track": track,
             "qids": [q for q, _ in qs], "questions": dict(qs), "served": {}, "answers": {},
             "opened_at": now_ist().isoformat()}
        try:
            table().put_item(Item=a, ConditionExpression="attribute_not_exists(PK)")
            log_event(p["sub"], "quiz_started", {"track": track})
        except ClientError as e:
            if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            a = get_attempt(p["sub"], date)
    qmap = a.get("questions") or dict(build_questions(a["track"], secs))
    qid = next_qid(a)
    if qid is None:   # every question answered but finishing was interrupted
        return {"finished": True, "result": finish(a, p)}
    serve(a, qid)
    return {"finished": False, "question": question_payload(a, qmap, qid),
            "answered": len(a.get("answers", {})), "score_so_far": sum(int(x["points"]) for x in a.get("answers", {}).values())}


def quiz_answer(event, claims, body):
    p = get_profile(claims)
    date = today_ist()
    if not (quiz_open(date) or is_admin(claims)):
        raise HttpError(409, "The quiz has closed for today.")
    a = get_attempt(p["sub"], date)
    if not a or a.get("finished_at"):
        raise HttpError(409, "No quiz in progress.")
    qid, choice = body.get("qid"), body.get("choice")
    if qid != next_qid(a) or qid not in a.get("served", {}):
        raise HttpError(409, "That question isn't the current one. Please reload.")
    if choice not in (0, 1, 2, 3):
        raise HttpError(400, "Pick an option")
    qmap = a.get("questions") or dict(build_questions(a["track"], day_sections(date)))
    q = qmap[qid]
    taken = max(0.0, time.time() - float(a["served"][qid]))
    correct = choice == int(q["answer_index"])
    points = (10 + speed_bonus(taken)) if correct else 0
    ans = {"choice": choice, "correct": correct, "secs": str(round(taken, 1)), "points": points}
    try:
        table().update_item(Key=attempt_key(p["sub"], date), UpdateExpression="SET answers.#q = :a",
                            ConditionExpression="attribute_not_exists(answers.#q)",
                            ExpressionAttributeNames={"#q": qid}, ExpressionAttributeValues={":a": ans})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise HttpError(409, "Already answered.")
        raise
    a["answers"][qid] = ans
    out = {"correct": correct, "answer_index": int(q["answer_index"]), "explanation": q["explanation"],
           "points": points, "secs": round(taken, 1)}
    # The next question is served (and its timer started) only when the client asks for it via
    # /quiz/start, so time spent reading this explanation doesn't count against the student.
    if next_qid(a):
        out["has_next"] = True
    else:
        out["result"] = finish(a, p)
    return out


def finish(a, p):
    date = a["date"]
    yesterday = (datetime.fromisoformat(date) - timedelta(days=1)).date().isoformat()
    streak = int(p.get("streak") or 0) + 1 if p.get("last_quiz_date") == yesterday else 1
    mult = streak_multiplier(streak)
    answers = a["answers"].values()
    base = sum(int(x["points"]) for x in answers)
    score = round(base * mult)
    total_secs = round(sum(float(x["secs"]) for x in answers), 1)
    finished = {"finished_at": now_ist().isoformat(), "base": base, "score": score, "multiplier": str(mult),
                "streak": streak, "correct_count": sum(1 for x in answers if x["correct"]),
                "total_secs": str(total_secs), "display_name": p.get("display_name"), "batch": p.get("batch", ""),
                "hidden": bool(p.get("hidden")), "GSI1PK": f"ATTEMPTS#{date}", "GSI1SK": p["sub"]}
    try:
        table().update_item(
            Key=attempt_key(p["sub"], date), ConditionExpression="attribute_not_exists(finished_at)",
            UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in finished),
            ExpressionAttributeNames={f"#{k}": k for k in finished},
            ExpressionAttributeValues={f":{k}": v for k, v in finished.items()})
    except ClientError as e:
        if e.response["Error"]["Code"] != "ConditionalCheckFailedException":
            raise
        return result_payload(get_attempt(p["sub"], date), p)
    table().update_item(
        Key={"PK": p["PK"], "SK": "PROFILE"},
        UpdateExpression="SET streak = :s, best_streak = :b, last_quiz_date = :d ADD total_score :sc, quizzes :one",
        ExpressionAttributeValues={":s": streak, ":b": max(streak, int(p.get("best_streak") or 0)), ":d": date,
                                   ":sc": score, ":one": 1})
    log_event(p["sub"], "quiz_submitted", {"score": score})
    _lb_cache.clear()
    a.update(finished)
    return result_payload(a, p)


def result_payload(a, p):
    board = leaderboard_rows("today", a["date"], p["sub"])
    return {"date": a["date"], "track": a["track"], "score": int(a["score"]), "base": int(a["base"]),
            "multiplier": float(a["multiplier"]), "streak": int(a["streak"]), "correct": int(a["correct_count"]),
            "total": len(a["qids"]), "total_secs": float(a["total_secs"]), "display_name": p.get("display_name"),
            "rank": board["me"]["rank"] if board["me"] else None, "players": board["players"]}


def get_result(event, claims, body):
    p = get_profile(claims)
    date = (event.get("queryStringParameters") or {}).get("date") or today_ist()
    a = get_attempt(p["sub"], date)
    if not a or not a.get("finished_at"):
        raise HttpError(404, "No finished quiz for that day.")
    return result_payload(a, p)


# ---------- leaderboard ----------

def finished_attempts(date):
    out, kwargs = [], {"IndexName": "GSI1", "KeyConditionExpression": Key("GSI1PK").eq(f"ATTEMPTS#{date}")}
    while True:
        r = table().query(**kwargs)
        out += r["Items"]
        if "LastEvaluatedKey" not in r:
            return out
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]


def leaderboard_all(period, date):
    key = (period, date)
    hit = _lb_cache.get(key)
    if hit and time.time() - hit[0] < LB_CACHE_SECS:
        return hit[1]
    dates = [date] if period == "today" else [d for d in week_dates(date) if d <= date]
    agg = defaultdict(lambda: {"score": 0, "secs": 0.0, "quizzes": 0})
    for d in dates:
        for a in finished_attempts(d):
            r = agg[a["sub"]]
            r["score"] += int(a["score"])
            r["secs"] += float(a["total_secs"])
            r["quizzes"] += 1
            if d >= r.get("last", ""):
                r.update(last=d, name=a.get("display_name"), batch=a.get("batch", ""), hidden=bool(a.get("hidden")))
    rows = sorted(({"sub": s, **r} for s, r in agg.items()), key=lambda r: (-r["score"], r["secs"]))
    _lb_cache[key] = (time.time(), rows)
    return rows


def leaderboard_rows(period, date, me_sub):
    rows = leaderboard_all(period, date)
    me = next((r for r in rows if r["sub"] == me_sub), None)
    visible = [r for r in rows if not r["hidden"] or r["sub"] == me_sub]   # hidden users still see themselves
    out, rank = [], 0
    for r in visible:
        rank += 1
        out.append({"rank": rank, "name": r["name"], "batch": r["batch"], "score": r["score"],
                    "quizzes": r["quizzes"], "you": r["sub"] == me_sub, "hidden": r["hidden"]})
    me_row = next((x for x in out if x["you"]), None) if me else None
    return {"rows": out[:100], "me": me_row, "players": len(rows)}


def get_leaderboard(event, claims, body):
    qs = event.get("queryStringParameters") or {}
    period = "week" if qs.get("period") == "week" else "today"
    date = today_ist()
    out = leaderboard_rows(period, date, claims["sub"])
    out.update(period=period, date=date, week=[week_dates(date)[0], week_dates(date)[-1]])
    return out


# ---------- events ----------

def post_event(event, claims, body):
    kind = body.get("type")
    if kind not in EVENT_TYPES:
        raise HttpError(400, "Unknown event type")
    log_event(claims["sub"], kind, body.get("meta"))
    return {"ok": True}


# ---------- admin ----------

def require_admin(claims):
    if not is_admin(claims):
        raise HttpError(403, "Admins only")


def admin_day(event, claims, body):
    require_admin(claims)
    date = (event.get("queryStringParameters") or {}).get("date") or today_ist()
    secs = day_sections(date)
    sched = table().get_item(Key={"PK": "SCHEDULE", "SK": date}).get("Item")
    return {"date": date, "published": is_published(date), "sections": secs, "schedule": sched}


def _check_quiz(quiz):
    for q in quiz:
        if len(q.get("options", [])) != 4 or int(q.get("answer_index", -1)) not in (0, 1, 2, 3) \
                or not str(q.get("question", "")).strip():
            raise HttpError(400, "Each question needs text, 4 options and a correct answer")


def admin_save_section(event, claims, body):
    require_admin(claims)
    date, sk = body.get("date"), body.get("sk")
    if not date or not (sk == "COMPANY" or sk in {f"TRACK#{t}" for t in TRACKS}):
        raise HttpError(400, "date and sk required")
    item = table().get_item(Key={"PK": f"DAY#{date}", "SK": sk}).get("Item")
    if not item:
        raise HttpError(404, "Section not found")
    editable = ["stories", "quiz", "what_it_does", "business_lines", "talking_points", "recent_news"]
    changes = {k: body[k] for k in editable if k in body}
    if "quiz" in changes:
        _check_quiz(changes["quiz"])
        for q in changes["quiz"]:
            q["answer_index"] = int(q["answer_index"])
    if changes:
        item.update(changes)
        item["edited"] = True
    if body.get("approve"):
        item["status"] = "approved"
    item["updated_at"] = now_ist().isoformat()
    item["updated_by"] = claims.get("email")
    table().put_item(Item=item)
    return {"ok": True, "section": item}


def admin_generate(event, claims, body):
    require_admin(claims)
    payload = {"date": body.get("date") or today_ist(), "force": bool(body.get("force"))}
    boto3.client("lambda").invoke(FunctionName=os.environ["GENERATE_FN"], InvocationType="Event",
                                  Payload=json.dumps(payload).encode())
    return {"ok": True, "started": payload, "note": "Takes about 2 minutes. Refresh to see the drafts."}


def admin_schedule_list(event, claims, body):
    require_admin(claims)
    items = table().query(KeyConditionExpression=Key("PK").eq("SCHEDULE"))["Items"]
    return {"items": [{"feature_date": i["SK"], **{k: i.get(k, "") for k in ("name", "process_date", "aliases", "notes")}}
                      for i in items]}


def admin_schedule_put(event, claims, body):
    require_admin(claims)
    fd, name = str(body.get("feature_date", "")), str(body.get("name", "")).strip()
    try:
        datetime.fromisoformat(fd)
    except ValueError:
        raise HttpError(400, "feature_date must be YYYY-MM-DD")
    if not name:
        raise HttpError(400, "Company name required")
    table().put_item(Item={"PK": "SCHEDULE", "SK": fd, "name": name,
                           "process_date": str(body.get("process_date", "")),
                           "aliases": str(body.get("aliases", "")), "notes": str(body.get("notes", ""))[:2000]})
    return {"ok": True}


def admin_schedule_delete(event, claims, body):
    require_admin(claims)
    fd = (event.get("queryStringParameters") or {}).get("feature_date")
    if not fd:
        raise HttpError(400, "feature_date required")
    table().delete_item(Key={"PK": "SCHEDULE", "SK": fd})
    return {"ok": True}


def admin_stats(event, claims, body):
    require_admin(claims)
    days = min(int((event.get("queryStringParameters") or {}).get("days", 14)), 30)
    today = datetime.fromisoformat(today_ist()).date()
    span = [(today - timedelta(days=k)).isoformat() for k in range(days + 7 - 1, -1, -1)]
    active = {}   # date -> set(sub)
    counts = {}   # date -> {type: n}
    for d in span:
        subs, c = set(), defaultdict(int)
        kwargs = {"KeyConditionExpression": Key("PK").eq(f"EVENT#{d}"), "ProjectionExpression": "#s, #t",
                  "ExpressionAttributeNames": {"#s": "sub", "#t": "type"}}
        while True:
            r = table().query(**kwargs)
            for e in r["Items"]:
                subs.add(e["sub"])
                c[e["type"]] += 1
            if "LastEvaluatedKey" not in r:
                break
            kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
        active[d], counts[d] = subs, dict(c)
    profiles, kwargs = [], {"FilterExpression": "SK = :p", "ExpressionAttributeValues": {":p": "PROFILE"},
                            "ProjectionExpression": "#s, first_seen", "ExpressionAttributeNames": {"#s": "sub"}}
    while True:
        r = table().scan(**kwargs)
        profiles += r["Items"]
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    cohort, returned = 0, 0
    for prof in profiles:
        fs = prof.get("first_seen")
        if not fs:
            continue
        d7 = (datetime.fromisoformat(fs).date() + timedelta(days=7)).isoformat()
        if d7 <= today_ist() and d7 in active:
            cohort += 1
            returned += prof["sub"] in active[d7]
    rows = [{"date": d, "dau": len(active[d]), "app_opens": counts[d].get("app_open", 0),
             "stories_opened": counts[d].get("story_open", 0), "quizzes_started": counts[d].get("quiz_started", 0),
             "quizzes_completed": counts[d].get("quiz_submitted", 0), "shares": counts[d].get("results_shared", 0),
             "signups": sum(1 for prof in profiles if prof.get("first_seen") == d)} for d in span[-days:]]
    return {"days": rows, "users": len(profiles),
            "day7_return": {"cohort": cohort, "returned": returned,
                            "rate": round(100 * returned / cohort, 1) if cohort else None}}


ROUTES = {
    "GET /me": get_me, "PUT /me": put_me, "GET /today": get_today,
    "POST /quiz/start": quiz_start, "POST /quiz/answer": quiz_answer, "GET /quiz/result": get_result,
    "GET /leaderboard": get_leaderboard, "POST /events": post_event,
    "GET /admin/day": admin_day, "PUT /admin/section": admin_save_section, "POST /admin/generate": admin_generate,
    "GET /admin/schedule": admin_schedule_list, "PUT /admin/schedule": admin_schedule_put,
    "DELETE /admin/schedule": admin_schedule_delete, "GET /admin/stats": admin_stats,
}


def handler(event, context):
    fn = ROUTES.get(event.get("routeKey"))
    if not fn:
        return resp(404, {"error": "Not found"})
    try:
        body = json.loads(event.get("body") or "{}") if event.get("body") else {}
        return resp(200, fn(event, claims_of(event), body))
    except HttpError as e:
        return resp(e.status, {"error": e.message})
    except Exception:
        traceback.print_exc()
        return resp(500, {"error": "Something went wrong. Please try again."})
