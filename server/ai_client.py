"""
Unified AI client that supports OpenAI and Anthropic (Claude) APIs.
Falls back to Anthropic when no OpenAI API key is available.
"""

import importlib.util
import json
import os
import re
from typing import Optional

DEFAULT_MODEL = "gpt-5-mini"

# The one list of models the Settings page offers and the server accepts.
MODEL_OPTIONS = [
    {"id": "gpt-5-mini", "label": "GPT-5 Mini", "note": "Fast and low cost."},
    {"id": "gpt-5.4", "label": "GPT-5.4", "note": "Strong accuracy for complex quotes."},
    {"id": "gpt-6-luna", "label": "GPT-6 Luna", "note": "Newest model. Best accuracy."},
]

# Model mapping: OpenAI model names → Anthropic equivalents
_ANTHROPIC_MODEL_MAP = {
    "gpt-5-mini": "claude-sonnet-4-20250514",
    "gpt-5.4": "claude-sonnet-4-20250514",
    "gpt-6-luna": "claude-sonnet-4-20250514",
}

# Seconds to wait for one AI answer, and how many extra tries after a failure.
OPENAI_TIMEOUT_SECONDS = 150
OPENAI_MAX_RETRIES = 1

_provider = None  # "openai" or "anthropic" — auto-detected


class AIError(RuntimeError):
    """An AI call that did not produce a usable answer, with a plain-English message."""

    def __init__(self, user_message: str, reason: str = "error"):
        super().__init__(user_message)
        self.user_message = user_message
        self.reason = reason


def _anthropic_installed() -> bool:
    return importlib.util.find_spec("anthropic") is not None


def _detect_provider(api_key: str = None) -> str:
    """Determine which AI provider to use based on available keys."""
    if api_key:
        return "openai"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if os.environ.get("ANTHROPIC_API_KEY") and _anthropic_installed():
        return "anthropic"
    return "none"


def chat_complete(
    system: str,
    user: str,
    api_key: str = None,
    model: str = None,
    json_mode: bool = False,
    image_data_urls: list[str] | None = None,
    response_schema: dict | None = None,
) -> str:
    """
    Send a chat completion request to whichever AI provider is available.
    Returns the raw text content of the response.

    Raises AIError (with a plain-English user_message) when no AI is set up,
    the call fails, or the answer is empty or cut off.

    Args:
        system: System prompt
        user: User message
        api_key: OpenAI API key (if set, forces OpenAI)
        model: Model name (OpenAI naming; auto-mapped for Anthropic)
        json_mode: If True, request JSON output format
        image_data_urls: Optional base64 data URLs for visual input
        response_schema: Optional {"name": str, "schema": dict}; OpenAI returns
            JSON that strictly matches the schema
    """
    if model is None:
        from models import get_settings
        settings = get_settings()
        model = settings.get("openai_model", DEFAULT_MODEL)
    provider = _detect_provider(api_key)

    if provider == "openai":
        return _openai_complete(system, user, api_key, model, json_mode, image_data_urls, response_schema)
    elif provider == "anthropic":
        return _anthropic_complete(system, user, model, json_mode or bool(response_schema), image_data_urls)
    else:
        raise AIError(
            "AI is not set up. An admin needs to add an OpenAI key in Settings.",
            "no_provider",
        )


def _openai_complete(
    system: str,
    user: str,
    api_key: str,
    model: str,
    json_mode: bool,
    image_data_urls: list[str] | None = None,
    response_schema: dict | None = None,
) -> str:
    """Call OpenAI chat completions API."""
    import openai

    client_kwargs = {
        "timeout": openai.Timeout(OPENAI_TIMEOUT_SECONDS, connect=10),
        "max_retries": OPENAI_MAX_RETRIES,
    }
    if api_key:
        client_kwargs["api_key"] = api_key
    client = openai.OpenAI(**client_kwargs)

    user_content = user
    if image_data_urls:
        user_content = [{"type": "text", "text": user}]
        user_content.extend(
            {
                "type": "image_url",
                "image_url": {"url": image_data_url, "detail": "high"},
            }
            for image_data_url in image_data_urls
        )

    kwargs = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    if response_schema:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema["name"],
                "strict": True,
                "schema": response_schema["schema"],
            },
        }
    elif json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    try:
        response = client.chat.completions.create(**kwargs)
    except openai.AuthenticationError as exc:
        raise AIError("The AI key was rejected. An admin needs to check the OpenAI key in Settings.", "auth") from exc
    except openai.NotFoundError as exc:
        raise AIError(f"The AI model \"{model}\" isn't available. Pick another model in Settings.", "model_not_found") from exc
    except openai.RateLimitError as exc:
        raise AIError("The AI is busy or out of credit right now. Try again in a minute.", "rate_limited") from exc
    except (openai.APITimeoutError, openai.APIConnectionError) as exc:
        raise AIError("The AI didn't answer in time. Try again.", "timeout") from exc
    except openai.APIError as exc:
        raise AIError("The AI request failed. Try again.", "api_error") from exc

    choice = response.choices[0]
    content = choice.message.content
    if choice.finish_reason == "length":
        raise AIError("The AI answer was cut off before it finished. Try again with a smaller file.", "truncated")
    if getattr(choice.message, "refusal", None) or not (content or "").strip():
        raise AIError("The AI gave no answer. Try again.", "empty")
    return content


def _anthropic_complete(
    system: str,
    user: str,
    model: str,
    json_mode: bool,
    image_data_urls: list[str] | None = None,
) -> str:
    """Call Anthropic messages API."""
    import anthropic

    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    mapped_model = _ANTHROPIC_MODEL_MAP.get(model, "claude-sonnet-4-20250514")

    # For JSON mode, append instruction to system prompt
    effective_system = system
    if json_mode:
        effective_system = system + "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no code fences, no explanation."

    user_content = user
    if image_data_urls:
        content_blocks = []
        for image_data_url in image_data_urls:
            match = re.fullmatch(
                r"data:(image/(?:jpeg|png|gif|webp));base64,([A-Za-z0-9+/=]+)",
                image_data_url,
            )
            if not match:
                raise ValueError("Unsupported image data URL for Anthropic")
            content_blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": match.group(1),
                    "data": match.group(2),
                },
            })
        content_blocks.append({"type": "text", "text": user})
        user_content = content_blocks

    response = client.messages.create(
        model=mapped_model,
        max_tokens=16000,
        system=effective_system,
        messages=[{"role": "user", "content": user_content}],
    )

    if response.stop_reason == "max_tokens":
        raise AIError("The AI answer was cut off before it finished. Try again with a smaller file.", "truncated")
    content = response.content[0].text if response.content else ""
    if not content.strip():
        raise AIError("The AI gave no answer. Try again.", "empty")

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
