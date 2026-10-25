"""Build one day's content: per-track stories + quiz, and Company of the Day.

Content is generated once per track per day (never per user). Each section is
independent: if one fails after a retry it is saved with an `error` so the admin
page can flag it, and the rest of the day still goes out.
"""
import random
import re
from concurrent.futures import ThreadPoolExecutor

from . import llm
from .schemas import (COMPANY_SCHEMA, TAG_SCHEMA, TRACK_SCHEMA, TRACKS, event_key,
                      validate_company, validate_tags, validate_track)

SYSTEM = (
    "You write a short daily business-news brief for MBA students at IMT Ghaziabad (India) "
    "who are preparing for campus placement interviews. Write clear, plain Indian English. "
    "Always write ORIGINAL sentences in your own words; never copy phrases from the headlines or teasers. "
    "Use only facts present in the material you are given; never invent numbers, names or dates."
)


def _line(item, teaser_chars):
    t = item["teaser"][:teaser_chars]
    return f'{item["id"]} | {item["source"]} | {item["headline"]}' + (f" — {t}" if t else "")


STOP = set("the and for with from into after over amid says said will its has have are was were this that than more "
           "new india indian india's crore lakh rs per cent year yoy q1 q2 q3 q4 fy27 fy26 how why what who should "
           "shares share stock stocks profit net rises jumps falls bank banks finance bond bonds market markets "
           "growth demand plan plans business company firm group sales revenue results".split())


def _tokens(headline):
    return {w for w in re.findall(r"[a-z0-9&]+", headline.lower().replace("'s", "")) if len(w) >= 3 and w not in STOP}


def _same_event(a, b, df, n):
    """Two headlines likely cover the same event if they share two or more uncommon words."""
    shared = _tokens(a) & _tokens(b)
    return len([w for w in shared if df.get(w, 0) <= max(3, n * 0.08)]) >= 2


JUNK = re.compile(r"stocks? to buy|should you buy|buy, sell or hold|share price today|live updates|\bgmp\b|"
                  r"stock market today|trade setup|technical picks|horoscope|lottery|\bsensex\b|\bnifty\b|"
                  r"stocks on fire|share price (slides|jumps|falls|rises|today)|stocks? (rally|crash|surge)", re.I)


def _tag_batch(batch):
    ids = {i["id"] for i in batch}
    track_desc = "\n".join(f"- {k}: {v}" for k, v in TRACKS.items())
    prompt = (
        f"Tracks:\n{track_desc}\n\nNews items (id | source | headline — teaser):\n"
        + "\n".join(_line(i, 120) for i in batch)
        + "\n\nTag EVERY item:\n"
        "- tracks: the 0-2 tracks whose students would genuinely discuss it in a placement interview "
        "(empty list if it is not business news: crime, celebrity, sport, pure politics, personal finance tips).\n"
        "- importance 1-5 for an MBA student in India: 5 = major national business story everyone will talk about "
        "(big IPO, RBI decision, major policy, landmark deal); 4 = significant company or sector development; "
        "3 = useful but routine (normal quarterly results); 2 = minor; 1 = trivial, promotional or a share-price-only move. "
        "Foreign company news (e.g. SpaceX, Tesla, OpenAI) is at most 3 unless it directly affects Indian business.\n"
        "- event: a 2-5 word label for the underlying event (e.g. 'Jio Platforms IPO'). "
        "Use the SAME label for items about the same event.\n"
    )
    return llm.call_json(SYSTEM, prompt, TAG_SCHEMA, lambda o: validate_tags(o, ids),
                         max_tokens=12000, model=llm.FAST_MODEL)["items"]


def tag_items(items, batch_size=70):
    """Tag items in parallel batches. A failed batch is skipped; only fails if every batch fails."""
    batches = [items[k:k + batch_size] for k in range(0, len(items), batch_size)]

    def safe(batch):
        try:
            return _tag_batch(batch)
        except llm.LLMError as e:
            print(f"tag batch failed ({len(batch)} items): {e}")
            return None

    with ThreadPoolExecutor(3) as pool:   # gentle on Bedrock capacity
        results = list(pool.map(safe, batches))
    if all(r is None for r in results):
        raise llm.LLMError("every tagging batch failed")
    return {r["id"]: r for rows in results if rows for r in rows}


def pick_for_track(track, items, tags, df):
    """Top 7 distinct events for a track, by importance then recency (5 are shown)."""
    cands = [i for i in items if i["id"] in tags and track in tags[i["id"]]["tracks"] and tags[i["id"]]["importance"] >= 2]
    cands.sort(key=lambda i: i["published"], reverse=True)          # newest first...
    cands.sort(key=lambda i: -tags[i["id"]]["importance"])          # ...within each importance level
    picked, seen, dropped = [], set(), []
    for i in cands:
        key = event_key(tags[i["id"]]["event"])
        if key in seen or any(_same_event(i["headline"], p["headline"], df, len(items)) for p in picked):
            dropped.append({"headline": i["headline"], "reason": "same event as another pick"})
            continue
        seen.add(key)
        picked.append(i)
        if len(picked) == 7:
            break
    return picked, dropped[:10]


def _shuffle_options(quiz, rng):
    out = []
    for q in quiz:
        correct = q["options"][q["answer_index"]]
        opts = list(q["options"])
        rng.shuffle(opts)
        out.append({"question": q["question"].strip(), "options": [o.strip() for o in opts], "story_id": q.get("story_id"),
                    "answer_index": opts.index(correct), "explanation": q["explanation"].strip()})
    return out


def write_track(track, picked, rng):
    if not picked:
        raise llm.LLMError("no stories for this track in today's feeds")
    ids = [i["id"] for i in picked]
    n_q = min(5, len(picked))
    prompt = (
        f"Track: {TRACKS[track]}\n\nStories (id | source | headline — teaser):\n"
        + "\n".join(_line(i, 300) for i in picked)
        + "\n\nFor every story write:\n"
        "- summary: 2-3 short sentences (max 55 words) explaining what happened, in your own words.\n"
        "- why_it_matters: ONE line (max 25 words) on why this matters for a placement interview in this track "
        "(e.g. a talking point, a concept it illustrates, or what it means for companies hiring).\n"
        "- fit: 'strong' if people in this track would clearly discuss it, 'weak' if only loosely related, "
        "'off-track' if it belongs to a different track or is not business news.\n\n"
        f"Then write exactly {n_q} multiple-choice questions, each about a DIFFERENT story (give its id as story_id), "
        f"answerable from your summary of that story alone. Choose the {n_q} most useful stories, preferring fit 'strong'; "
        f"only those {n_q} stories will be shown to students. "
        "Each has 4 plausible, distinct options of at most 8 words each, one correct answer (answer_index 0-3) "
        "and a one-sentence explanation. Test understanding of the business point, not trivia like exact share prices. "
        "MCQ rules: all 4 options must be similar in length, style and level of detail, and the correct one must NOT be the longest "
        "or the only specific one. Wrong options must be plausible to someone who skimmed the news. "
        "Do not repeat words from the question in only the correct option. "
    )
    obj = llm.call_json(SYSTEM, prompt, TRACK_SCHEMA, lambda o: validate_track(o, ids, n_q))
    by_id = {s["id"]: s for s in obj["stories"]}
    # The 5 stories shown are exactly the ones the 5 questions are about, so every question is answerable.
    keep_ids = {q["story_id"] for q in obj["quiz"]}
    stories = [{
        "id": i["id"], "headline": i["headline"], "link": i["link"], "source": i["source"],
        "published": i["published"], "summary": by_id[i["id"]]["summary"].strip(),
        "why_it_matters": by_id[i["id"]]["why_it_matters"].strip(),
    } for i in picked if i["id"] in keep_ids]  # keep the editor's original order
    dropped = [{"headline": i["headline"], "reason": f'not in the top 5 (fit: {by_id[i["id"]].get("fit")})'}
               for i in picked if i["id"] not in keep_ids]
    return {"stories": stories, "quiz": _shuffle_options(obj["quiz"], rng), "_dropped": dropped}


def _mentions(name, aliases, items):
    keys = [name.lower()] + [a.strip().lower() for a in aliases if a.strip()]
    pats = [re.compile(r"\b" + re.escape(k) + r"\b") for k in keys]
    return [i for i in items if any(p.search((i["headline"] + " " + i["teaser"]).lower()) for p in pats)][:8]


def write_company(name, process_date, items, rng, aliases=(), notes=""):
    related = _mentions(name, aliases, items)
    ids = {i["id"] for i in related}
    news = "\n".join(_line(i, 300) for i in related) or "(no news about this company in the last day)"
    prompt = (
        f"Company of the Day: {name}. It recruits on campus on {process_date}.\n\n"
        f"Recent news items that mention it (id | source | headline — teaser):\n{news}\n\n"
        + (f"Verified notes from the placement team (treat as correct and prefer them over your own knowledge):\n{notes}\n\n" if notes else "")
        +
        "Write a specific, useful interview-prep brief (generic statements that fit any company are useless):\n"
        "- what_it_does: 2 sentences: what it sells or does, to whom, and its position in India (e.g. market leader, key rivals).\n"
        "- business_lines: 3-5 main segments or business lines as the company itself reports them, each with 1-3 flagship brands, "
        "products or service lines in brackets where well known.\n"
        "- recent_news: one line per relevant news item above (use its id). Empty list if none are relevant.\n"
        "- talking_points: exactly 3 sharp interview talking points, one line each, each naming a concrete strategy, "
        "challenge, competitor move or recent development (not 'it focuses on innovation').\n"
        "- quiz: 2-3 multiple-choice questions on specific facts in your brief (brands, segments, rivals, news), not obvious ones "
        "like 'what industry is it in'. Each with 4 distinct options of at most 8 words, answer_index 0-3, one-sentence explanation. "
        + "MCQ rules: all 4 options must be similar in length, style and level of detail, and the correct one must NOT be the longest "
        "or the only specific one. Wrong options must be plausible to someone who skimmed the news. "
        "Do not repeat words from the question in only the correct option. " + "\n"
        "Use only well-established public knowledge for company facts, and double-check which segment each brand belongs to. "
        "Do NOT include any numbers (counts, revenues, market shares, years) unless they appear in the news items above. "
        "Never invent recent events.\n"
    )
    obj = llm.call_json(SYSTEM, prompt, COMPANY_SCHEMA, lambda o: validate_company(o, ids))
    by_id = {i["id"]: i for i in related}
    return {
        "name": name, "process_date": process_date,
        "what_it_does": obj["what_it_does"].strip(),
        "business_lines": [b.strip() for b in obj["business_lines"]],
        "recent_news": [{"point": n["point"].strip(), "headline": by_id[n["id"]]["headline"],
                         "link": by_id[n["id"]]["link"], "source": by_id[n["id"]]["source"]}
                        for n in obj["recent_news"] if n["id"] in by_id],
        "talking_points": [t.strip() for t in obj["talking_points"]],
        "quiz": _shuffle_options(obj["quiz"], rng),
    }


def build_day(date, items, company=None):
    """Return {"tracks": {track: section}, "company": section|None}. Sections may carry "error"."""
    rng = random.Random(date)
    result = {"tracks": {}, "company": None}
    items = [i for i in items if not JUNK.search(i["headline"])]
    df = {}
    for i in items:
        for w in _tokens(i["headline"]):
            df[w] = df.get(w, 0) + 1
    try:
        tags = tag_items(items)
    except llm.LLMError as e:
        for t in TRACKS:
            result["tracks"][t] = {"error": f"story tagging failed: {e}", "stories": [], "quiz": []}
        tags = None

    def one_track(t):
        picked, dropped = pick_for_track(t, items, tags, df)
        try:
            sec = write_track(t, picked, random.Random(f"{date}-{t}"))
            sec["dropped"] = dropped + sec.pop("_dropped")
            return t, sec
        except llm.LLMError as e:
            return t, {"error": str(e), "stories": [], "quiz": []}

    if tags is not None:
        with ThreadPoolExecutor(4) as pool:
            result["tracks"] = dict(pool.map(one_track, TRACKS))
    if company:
        try:
            result["company"] = write_company(company["name"], company["process_date"], items, rng,
                                              company.get("aliases") or (), company.get("notes") or "")
        except llm.LLMError as e:
            result["company"] = {"name": company["name"], "process_date": company["process_date"], "error": str(e)}
    sections = list(result["tracks"].values()) + ([result["company"]] if result["company"] else [])
    for sec in sections:
        if not sec.get("error") and "stories" in sec and len(sec["stories"]) < 5:
            sec["warning"] = f"only {len(sec['stories'])} on-track stories today"
    return result
