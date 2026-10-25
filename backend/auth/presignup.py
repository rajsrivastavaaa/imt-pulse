"""Cognito pre-sign-up trigger: only @imt.ac.in addresses, and the batch attribute must match the email.

The email still has to be verified with the emailed code before the account works.
"""
import re

DOMAIN = "@imt.ac.in"
BATCH_RE = re.compile(r"^([a-z]+\d{2})")   # e.g. pgp25rajsrivastava@imt.ac.in -> pgp25


def batch_from_email(email):
    m = BATCH_RE.match(email.split("@")[0].lower())
    return m.group(1) if m else ""


def handler(event, context):
    attrs = event["request"]["userAttributes"]
    email = attrs.get("email", "").strip().lower()
    if not email.endswith(DOMAIN):
        raise Exception("Please sign up with your IMT email address (ending in @imt.ac.in).")
    if attrs.get("custom:batch", "") != batch_from_email(email):
        raise Exception("Batch does not match your email address.")
    if not attrs.get("given_name", "").strip():
        raise Exception("Please enter your first name.")
    return event
