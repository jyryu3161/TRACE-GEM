"""Shared utilities for LLM API clients (Gemini, Perplexity)."""

from __future__ import annotations

import json
import re


def extract_json_from_response(text: str) -> dict | None:
    """Extract a JSON object from an LLM response text.

    Tries three strategies in order:
    1. Direct JSON parse of the full text
    2. JSON inside a markdown code block (```json ... ```)
    3. First JSON object found anywhere in the text
    """
    # Try direct parse
    try:
        result = json.loads(text.strip())
        return result if isinstance(result, dict) else None
    except json.JSONDecodeError:
        pass

    # Try to find JSON in markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            return result if isinstance(result, dict) else None
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object (supports nested braces)
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    result = json.loads(text[start : i + 1])
                    if isinstance(result, dict):
                        return result
                except json.JSONDecodeError:
                    pass
                start = -1

    return None
