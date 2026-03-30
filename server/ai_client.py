"""
Unified AI client that supports OpenAI and Anthropic (Claude) APIs.
Falls back to Anthropic when no OpenAI API key is available.
"""

import json
import os
from typing import Optional

# Model mapping: OpenAI model names → Anthropic equivalents
_ANTHROPIC_MODEL_MAP = {
    "gpt-5-mini": "claude-sonnet-4-20250514",
    "gpt-5.4": "claude-sonnet-4-20250514",
}

_provider = None  # "openai" or "anthropic" — auto-detected


def _detect_provider(api_key: str = None) -> str:
    """Determine which AI provider to use based on available keys."""
    if api_key:
        return "openai"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "none"


def chat_complete(
    system: str,
    user: str,
    api_key: str = None,
    model: str = "gpt-5-mini",
    json_mode: bool = False,
) -> str:
    """
    Send a chat completion request to whichever AI provider is available.
    Returns the raw text content of the response.

    Args:
        system: System prompt
        user: User message
        api_key: OpenAI API key (if set, forces OpenAI)
        model: Model name (OpenAI naming; auto-mapped for Anthropic)
        json_mode: If True, request JSON output format
    """
    provider = _detect_provider(api_key)

    if provider == "openai":
        return _openai_complete(system, user, api_key, model, json_mode)
    elif provider == "anthropic":
        return _anthropic_complete(system, user, model, json_mode)
    else:
        raise RuntimeError(
            "No AI API key available. Set either openai_api_key in Settings "
            "or ANTHROPIC_API_KEY environment variable."
        )


def _openai_complete(system: str, user: str, api_key: str, model: str, json_mode: bool) -> str:
    """Call OpenAI chat completions API."""
    import openai

    client_kwargs = {}
    if api_key:
        client_kwargs["api_key"] = api_key
    client = openai.OpenAI(**client_kwargs)

    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content


def _anthropic_complete(system: str, user: str, model: str, json_mode: bool) -> str:
    """Call Anthropic messages API."""
    import anthropic

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    mapped_model = _ANTHROPIC_MODEL_MAP.get(model, "claude-sonnet-4-20250514")

    # For JSON mode, append instruction to system prompt
    effective_system = system
    if json_mode:
        effective_system = system + "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no code fences, no explanation."

    response = client.messages.create(
        model=mapped_model,
        max_tokens=4096,
        system=effective_system,
        messages=[{"role": "user", "content": user}],
    )

    content = response.content[0].text

    # Strip markdown code fences if present (Claude sometimes wraps JSON)
    if json_mode and content.startswith("```"):
        lines = content.split("\n")
        # Remove first line (```json) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        elif lines[0].startswith("```"):
            lines = lines[1:]
        content = "\n".join(lines)

    return content


def get_provider_info(api_key: str = None) -> dict:
    """Return info about the active AI provider."""
    provider = _detect_provider(api_key)
    return {
        "provider": provider,
        "available": provider != "none",
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "openai_key_set": bool(api_key or os.environ.get("OPENAI_API_KEY")),
    }
