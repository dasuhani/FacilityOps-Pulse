"""
services/ai/groq_client.py
--------------------------
Thin wrapper around the Groq Python SDK.

Responsibilities:
  - Initialise the Groq client once (module-level singleton).
  - Expose a single `chat_completion()` function used by all other AI modules.
  - Handle API errors gracefully and surface clear messages to callers.
  - Respect the ENABLE_AI_FEATURES flag so the app works without a key.
"""

import logging
from typing import Optional

from core.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

_client = None  # lazy-initialised on first use


def _get_client():
    """Return the Groq client, creating it on first call."""
    global _client
    if _client is not None:
        return _client

    if not settings.GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your .env file or set "
            "ENABLE_AI_FEATURES=false to disable AI features."
        )

    try:
        from groq import Groq  # imported lazily to keep startup fast
        _client = Groq(api_key=settings.GROQ_API_KEY)
        logger.info("Groq client initialised (model: %s).", settings.GROQ_MODEL)
        return _client
    except ImportError:
        raise RuntimeError(
            "The 'groq' package is not installed. "
            "Run: pip install groq"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def chat_completion(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1024,
    model: Optional[str] = None,
) -> str:
    """
    Call the Groq chat completions API and return the assistant's reply as
    a plain string.

    Parameters
    ----------
    system_prompt : str
        Instruction context sent as the 'system' role message.
    user_prompt : str
        The actual user input / task sent as the 'user' role message.
    temperature : float
        Sampling temperature (0.0 = deterministic, 1.0 = creative).
        Keep low (0.1-0.3) for classification tasks.
    max_tokens : int
        Maximum tokens in the completion.
    model : str | None
        Override the model from settings for this call.

    Returns
    -------
    str
        The assistant's text response, stripped of leading/trailing whitespace.

    Raises
    ------
    RuntimeError
        If the API key is missing or the Groq SDK is not installed.
    Exception
        Re-raised Groq API errors (rate limit, auth, etc.) so callers can
        handle them and show user-friendly messages.
    """
    if not settings.ai_enabled:
        raise RuntimeError(
            "AI features are disabled. Set ENABLE_AI_FEATURES=true and "
            "GROQ_API_KEY in your .env file."
        )

    client = _get_client()
    chosen_model = model or settings.GROQ_MODEL

    try:
        response = client.chat.completions.create(
            model=chosen_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        logger.debug(
            "Groq completion — model=%s tokens_used=%s",
            chosen_model,
            response.usage.total_tokens if response.usage else "?",
        )
        return content.strip()

    except Exception as exc:
        logger.error("Groq API error: %s", exc)
        raise


def is_groq_available() -> bool:
    """
    Quick health-check: returns True if the Groq client can be created.
    Does NOT make a real API call — just validates config.
    """
    return bool(settings.GROQ_API_KEY and settings.ENABLE_AI_FEATURES)
