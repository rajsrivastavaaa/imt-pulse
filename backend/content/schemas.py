"""JSON schemas for LLM output plus hand-written validators (no extra dependencies)."""
import re


TRACKS = {
    "marketing": "Marketing (brands, FMCG, retail, D2C, advertising, consumer demand and behaviour, media, pricing, distribution, product launches; NOT infrastructure contracts, ports or property deals)",
    "finance": "Finance (markets, banking, NBFCs, RBI and monetary policy, IPOs, M&A, earnings, fundraising, insurance)",
    "consulting": "Consulting/Strategy (corporate strategy, policy and regulation, deals, competition, industry shifts, macro economy)",
    "ops": "Ops/Analytics (supply chain, manufacturing capacity, logistics, quick commerce and e-commerce operations, technology, AI and data adoption in business)",
}

MCQ = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "options": {"type": "array", "items": {"type": "string"}, "minItems": 4, "maxItems": 4},
        "answer_index": {"type": "integer", "minimum": 0, "maximum": 3},
        "explanation": {"type": "string"},
    },
    "required": ["question", "options", "answer_index", "explanation"],
}

TAG_SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "tracks": {"type": "array", "items": {"type": "string", "enum": list(TRACKS)}},
            "importance": {"type": "integer", "minimum": 1, "maximum": 5},
            "event": {"type": "string"},
        },
        "required": ["id", "tracks", "importance", "event"],
    }}},
    "required": ["items"],
}

TRACK_SCHEMA = {
    "type": "object",
    "properties": {
        "stories": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "summary": {"type": "string"},
                "why_it_matters": {"type": "string"},
                "fit": {"type": "string", "enum": ["strong", "weak", "off-track"]},
            },
            "required": ["id", "summary", "why_it_matters", "fit"],
        }},
        "quiz": {"type": "array", "items": MCQ},
    },
    "required": ["stories", "quiz"],
}

COMPANY_SCHEMA = {
    "type": "object",
    "properties": {
        "what_it_does": {"type": "string"},
        "business_lines": {"type": "array", "items": {"type": "string"}},
        "recent_news": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "point": {"type": "string"}},
            "required": ["id", "point"],
        }},
        "talking_points": {"type": "array", "items": {"type": "string"}},
        "quiz": {"type": "array", "items": MCQ},
    },
    "required": ["what_it_does", "business_lines", "recent_news", "talking_points", "quiz"],
}


def _check_mcqs(quiz, n_min, n_max):
    p = []
    if not isinstance(quiz, list) or not (n_min <= len(quiz) <= n_max):
        return [f"quiz must have {n_min}-{n_max} questions"]
    for i, q in enumerate(quiz):
        if not isinstance(q, dict):
            p.append(f"quiz[{i}] not an object"); continue
        opts = q.get("options")
        if not str(q.get("question", "")).strip():
            p.append(f"quiz[{i}] empty question")
        if not isinstance(opts, list) or len(opts) != 4 or not all(str(o).strip() for o in opts):
            p.append(f"quiz[{i}] needs exactly 4 non-empty options")
        elif len({str(o).strip().lower() for o in opts}) != 4:
            p.append(f"quiz[{i}] options must be distinct")
        elif max(len(str(o).split()) for o in opts) > 12:
            p.append(f"SOFT: quiz[{i}] options must be at most 8 words each")
        if q.get("answer_index") not in (0, 1, 2, 3):
            p.append(f"quiz[{i}] answer_index must be 0-3")
        if not str(q.get("explanation", "")).strip():
            p.append(f"quiz[{i}] empty explanation")
    return p


def event_key(event):
    return re.sub(r"[^a-z0-9]", "", str(event).lower())


def validate_tags(obj, valid_ids):
    rows = obj.get("items")
    if not isinstance(rows, list):
        return ["items missing"]
    got = {r.get("id") for r in rows if isinstance(r, dict)}
    p = []
    missing = valid_ids - got
    if len(missing) > len(valid_ids) * 0.25:
        p.append(f"{len(missing)} ids were not tagged, tag every item (e.g. {sorted(missing)[:5]})")
    elif missing:
        p.append(f"SOFT: {len(missing)} ids were not tagged, tag every item (e.g. {sorted(missing)[:5]})")
    for r in rows:
        if not isinstance(r, dict) or r.get("importance") not in (1, 2, 3, 4, 5) or \
                not isinstance(r.get("tracks"), list) or any(t not in TRACKS for t in r["tracks"]):
            p.append("every item needs tracks (subset of the track keys) and importance 1-5")
            break
    return p


def validate_track(obj, expected_ids):
    p = []
    stories = obj.get("stories")
    if not isinstance(stories, list):
        return ["stories missing"]
    got = [s.get("id") for s in stories if isinstance(s, dict)]
    if set(got) != set(expected_ids):
        p.append(f"stories must cover exactly these ids: {expected_ids}")
    for s in stories:
        if not isinstance(s, dict) or not str(s.get("summary", "")).strip() or not str(s.get("why_it_matters", "")).strip():
            p.append("every story needs summary and why_it_matters")
            break
    return p + _check_mcqs(obj.get("quiz"), 5, 5)


def validate_company(obj, valid_ids):
    p = []
    if not str(obj.get("what_it_does", "")).strip():
        p.append("what_it_does empty")
    if not isinstance(obj.get("business_lines"), list) or not obj["business_lines"]:
        p.append("business_lines empty")
    tp = obj.get("talking_points")
    if not isinstance(tp, list) or len(tp) != 3:
        p.append("talking_points must have exactly 3 items")
    for n in obj.get("recent_news") or []:
        if not isinstance(n, dict) or n.get("id") not in valid_ids:
            p.append("recent_news ids must come from the provided list")
            break
    return p + _check_mcqs(obj.get("quiz"), 2, 3)
