"""Shared helpers: IST time, DynamoDB access, scoring rules.

Single-table design (table name in env TABLE):
  DAY#<date>      TRACK#<track>      one track's stories + quiz for the day
  DAY#<date>      COMPANY            Company of the Day brief + quiz
  DAY#<date>      META               generation run info
  SCHEDULE        <feature date>     company scheduled for that date
  USER#<sub>      PROFILE            user profile, streak, totals
  USER#<sub>      ATTEMPT#<date>     that day's quiz attempt   (GSI1: ATTEMPTS#<date> / <sub>)
  EVENT#<date>    <iso ts>#<sub>#<n> analytics event (expires after 180 days)
"""
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

IST = timezone(timedelta(hours=5, minutes=30))
TRACKS = ["marketing", "finance", "consulting", "ops"]
PUBLISH_HOUR = 8          # content and quiz go live at 08:00 IST
SPEED_FULL_SECS = 10      # answer within 10s -> full 3-point bonus
SPEED_ZERO_SECS = 40      # bonus falls linearly to 0 at 40s

_table = None


def table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(os.environ["TABLE"])
    return _table


def now_ist():
    return datetime.now(IST)


def today_ist():
    return now_ist().date().isoformat()


def is_published(date):
    """Content for `date` is visible to students from 08:00 IST that day (and stays visible after)."""
    return now_ist() >= datetime.fromisoformat(date).replace(hour=PUBLISH_HOUR, tzinfo=IST)


def quiz_open(date):
    """The quiz for `date` can be started/answered from 08:00 to 23:59:59 IST that day only."""
    return date == today_ist() and now_ist().hour >= PUBLISH_HOUR


def week_dates(date):
    d = datetime.fromisoformat(date).date()
    monday = d - timedelta(days=d.weekday())
    return [(monday + timedelta(days=k)).isoformat() for k in range(7)]


def speed_bonus(secs):
    if secs <= SPEED_FULL_SECS:
        return 3
    if secs >= SPEED_ZERO_SECS:
        return 0
    return round(3 * (SPEED_ZERO_SECS - secs) / (SPEED_ZERO_SECS - SPEED_FULL_SECS))


def streak_multiplier(streak):
    return 1.25 if streak >= 7 else 1.1 if streak >= 3 else 1.0


def display_name(first, last):
    first = (first or "").strip().title()
    last = (last or "").strip()
    return f"{first} {last[:1].upper()}." if last else first


def plain(obj):
    """Convert DynamoDB Decimals to int/float for JSON."""
    return json.loads(json.dumps(obj, default=lambda d: int(d) if d == int(d) else float(d)))


def to_ddb(obj):
    """Convert floats to Decimal for DynamoDB."""
    return json.loads(json.dumps(obj), parse_float=Decimal)
