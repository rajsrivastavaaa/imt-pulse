"""Bedrock calls that must return strict JSON.

Uses the Converse API with a forced tool call, so the model has to answer with
arguments matching a JSON schema. We then validate again ourselves and retry once.
"""
import json
import os
import threading
import time

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# Cheap model for bulk tagging; stronger model for the text students read and the quiz.
FAST_MODEL = os.environ.get("BEDROCK_FAST_MODEL", "au.anthropic.claude-haiku-4-5-20251001-v1:0")
WRITE_MODEL = os.environ.get("BEDROCK_WRITE_MODEL", "au.anthropic.claude-sonnet-4-6")
_client = boto3.client(
    "bedrock-runtime",
    region_name=os.environ.get("BEDROCK_REGION", "ap-southeast-2"),
    config=Config(read_timeout=120, retries={"max_attempts": 4, "mode": "adaptive"}),
)
USAGE = {}  # model id -> {"input", "output", "calls"}
_lock = threading.Lock()


class LLMError(Exception):
    pass


def _fallbacks(model):
    """Models to try in order when Bedrock is out of capacity: regional, global, then the write model."""
    chain = [model]
    if model.startswith("au."):
        chain.append("global." + model[3:])
    if WRITE_MODEL not in chain:
        chain.append(WRITE_MODEL)
    return chain


def _converse(model, system, text, schema, max_tokens):
    return _client.converse(
        modelId=model,
        system=[{"text": system}],
        messages=[{"role": "user", "content": [{"text": text}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0.3},
        toolConfig={
            "tools": [{"toolSpec": {"name": "submit", "description": "Submit the answer.",
                                    "inputSchema": {"json": schema}}}],
            "toolChoice": {"tool": {"name": "submit"}},
        },
    )


def call_json(system, prompt, schema, validate, max_tokens=4000, model=None):
    """Return validated JSON. `validate(obj)` returns a list of problems (empty = ok).

    Problems prefixed "SOFT:" are quality nudges: they trigger the retry, but are
    accepted on the final attempt instead of failing the section.
    """
    models = _fallbacks(model or WRITE_MODEL)
    last_problems = []
    for attempt in range(2):
        text = prompt
        if last_problems:
            text += "\n\nYour previous answer had these problems, fix them:\n- " + "\n- ".join(last_problems[:10])
        resp = None
        while models:
            try:
                resp = _converse(models[0], system, text, schema, max_tokens)
                break
            except (ClientError, BotoCoreError) as e:   # capacity/throttling after botocore's own retries
                print(f"Bedrock error on {models[0]}: {e}")
                models.pop(0)
                if not models:
                    raise LLMError(f"Bedrock unavailable: {e}")
                time.sleep(3)
        with _lock:
            u = USAGE.setdefault(models[0], {"input": 0, "output": 0, "calls": 0})
            u["calls"] += 1
            u["input"] += resp["usage"]["inputTokens"]
            u["output"] += resp["usage"]["outputTokens"]
        obj = None
        for block in resp["output"]["message"]["content"]:
            if "toolUse" in block:
                obj = block["toolUse"]["input"]
        if isinstance(obj, str):  # occasionally nested as a string
            try:
                obj = json.loads(obj)
            except ValueError:
                obj = None
        if obj is None:
            last_problems = ["No tool call / JSON returned."]
            continue
        last_problems = validate(obj)
        hard = [x for x in last_problems if not x.startswith("SOFT:")]
        if not last_problems or (attempt == 1 and not hard):
            return obj
    raise LLMError("; ".join(last_problems[:5]))
