"""
LLM client wrapper — OpenAI-compatible interface for DeepSeek.

Provides a thin wrapper around the OpenAI Python client configured to talk to
DeepSeek's API. Supports both synchronous simple prompts and async streaming
for the agent loop.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openai import AsyncOpenAI, OpenAI

from config import config

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Lightweight wrapper around DeepSeek's OpenAI-compatible API.

    Handles retries with exponential backoff and basic error classification.
    """

    def __init__(self) -> None:
        self._sync_client = OpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._async_client = AsyncOpenAI(
            api_key=config.llm_api_key,
            base_url=config.llm_base_url,
        )
        self._model = config.llm_model
        self._max_retries = 3
        self._base_delay = 1.0  # seconds

    # ── Public API ──────────────────────────────────────────────────────────

    def ask(self, prompt: str, system: str | None = None, **kwargs: Any) -> str:
        """
        Synchronous LLM call.  Returns the text content of the response.

        Parameters
        ----------
        prompt : str
            The user message.
        system : str, optional
            Optional system-prompt override.  If omitted a default assistant
            persona is used.
        """
        messages = self._build_messages(prompt, system)
        response = self._retry_sync(messages, **kwargs)
        return response

    async def ask_async(self, prompt: str, system: str | None = None, **kwargs: Any) -> str:
        """Async variant of :meth:`ask`."""
        messages = self._build_messages(prompt, system)
        response = await self._retry_async(messages, **kwargs)
        return response

    # ── Internals ───────────────────────────────────────────────────────────

    def _build_messages(self, prompt: str, system: str | None) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        else:
            messages.append({
                "role": "system",
                "content": "You are a helpful assistant that extracts structured "
                           "information from web content and provides precise answers.",
            })
        messages.append({"role": "user", "content": prompt})
        return messages

    def _retry_sync(self, messages: list[dict], **kwargs: Any) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = self._sync_client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.0),
                    max_tokens=kwargs.get("max_tokens", 1024),
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt, self._max_retries, exc,
                )
                if attempt < self._max_retries:
                    delay = self._base_delay * (2 ** (attempt - 1))
                    time.sleep(delay)
        raise RuntimeError(f"LLM call failed after {self._max_retries} retries") from last_exc

    async def _retry_async(self, messages: list[dict], **kwargs: Any) -> str:
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                resp = await self._async_client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.0),
                    max_tokens=kwargs.get("max_tokens", 1024),
                )
                return resp.choices[0].message.content or ""
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "LLM call attempt %d/%d failed: %s",
                    attempt, self._max_retries, exc,
                )
                if attempt < self._max_retries:
                    delay = self._base_delay * (2 ** (attempt - 1))
                    import asyncio
                    await asyncio.sleep(delay)
        raise RuntimeError(f"LLM call failed after {self._max_retries} retries") from last_exc


# Module-level singleton.
llm = LLMClient()
