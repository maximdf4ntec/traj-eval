"""Azure AI Foundry client wrapping the OpenAI-compatible endpoint.

Configuration is read from environment variables at instantiation time:

  AZURE_FOUNDRY_ENDPOINT  — Resource base URL, e.g.
                             https://<resource>.services.ai.azure.com
                             (the /api/projects/... suffix is stripped automatically)
  AZURE_FOUNDRY_KEY       — API key / Bearer token.
  AZURE_FOUNDRY_MODEL     — Model deployment name (default: DeepSeek-V4-0).

Azure AI Foundry uses the inference path  /models/chat/completions
with api-version as a query parameter — distinct from Azure OpenAI
Service which uses /openai/deployments/{model}/chat/completions.

Usage::

    client = AzureFoundryClient()
    text = await client.complete("Return JSON: {}", timeout=30.0)
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from openai import AsyncOpenAI


class AzureFoundryClient:
    """Async LLM client targeting Azure AI Foundry (OpenAI-compatible API).

    Attributes:
        endpoint: Base URL for the Azure AI Foundry models endpoint.
        model: Deployment model name used in every completion request.
    """

    def __init__(self) -> None:
        self.endpoint: str = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "")
        self._api_key: str = os.environ.get("AZURE_FOUNDRY_KEY", "")
        self.model: str = os.environ.get("AZURE_FOUNDRY_MODEL", "DeepSeek-V4-0")

        # Initialise lazily — avoids hard crash on missing env vars at import.
        self._client: AsyncOpenAI | None = None

    def _get_client(self) -> AsyncOpenAI:
        """Return (and lazily create) the underlying AsyncOpenAI client."""
        if self._client is None:
            if not self.endpoint:
                raise RuntimeError(
                    "AZURE_FOUNDRY_ENDPOINT is not set. "
                    "Export it before running eval_traj.py."
                )
            if not self._api_key:
                raise RuntimeError(
                    "AZURE_FOUNDRY_KEY is not set. "
                    "Export it before running eval_traj.py."
                )
            base_url = self._build_base_url(self.endpoint)
            self._client = AsyncOpenAI(
                base_url=base_url,
                api_key=self._api_key,
                # Azure AI Foundry accepts both 'Authorization: Bearer' (OpenAI SDK default)
                # and 'api-key' header. Supply both to maximise compatibility.
                default_headers={"api-key": self._api_key},
                # api-version must be a query parameter, not a header.
                default_query={"api-version": "2024-05-01-preview"},
                # Increase default timeout so asyncio.wait_for controls it.
                timeout=60.0,
            )
        return self._client

    @staticmethod
    def _build_base_url(endpoint: str) -> str:
        """Normalise any Azure AI Foundry endpoint variant to the inference base URL.

        Azure AI Foundry inference endpoint:
            https://<resource>.services.ai.azure.com/models/

        The user may provide the raw resource URL, a project-scoped URL
        (``/api/projects/…``), or the ``/models`` suffix already appended.
        All are normalised to the resource-level ``/models/`` path which the
        OpenAI-compatible SDK appends ``chat/completions`` to.
        """
        raw = endpoint.rstrip("/")

        # Strip project/management path segments so we reach the resource root.
        for marker in ("/api/projects", "/openai", "/models"):
            if marker in raw:
                raw = raw[: raw.index(marker)]

        raw = raw.rstrip("/")
        return f"{raw}/models/"

    async def complete(self, prompt: str, timeout: float = 30.0) -> str:
        """Send a single-turn chat message and return the response text.

        The method requests JSON output from the model by stating it
        explicitly in the system prompt.  If the model does not support
        the ``response_format`` parameter, it falls back to raw text.

        Args:
            prompt: The user message to send.
            timeout: Maximum seconds to wait before raising ``asyncio.TimeoutError``.

        Returns:
            The raw text content of the first choice message.

        Raises:
            asyncio.TimeoutError: If the call exceeds *timeout* seconds.
            RuntimeError: If required environment variables are missing.
        """
        client = self._get_client()

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a precise evaluation assistant. Always respond with valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
        }

        # Try with response_format first; some deployments may not support it.
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    **kwargs, response_format={"type": "json_object"}
                ),
                timeout=timeout,
            )
        except Exception:
            # Fall back without response_format.
            response = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=timeout,
            )

        return response.choices[0].message.content or ""

    async def embed(self, texts: list[str], timeout: float = 30.0) -> list[list[float]]:
        """Get embedding vectors for a list of texts.

        Uses the Azure AI Foundry OpenAI-compatible ``/embeddings`` endpoint.
        The embedding model is controlled by the ``AZURE_FOUNDRY_EMBED_MODEL``
        environment variable (default: ``text-embedding-3-small``).

        Args:
            texts: Input strings to embed.  The returned list preserves order.
            timeout: Maximum seconds to wait before raising
                ``asyncio.TimeoutError``.

        Returns:
            A list of float vectors in the same order as *texts*.

        Raises:
            asyncio.TimeoutError: If the call exceeds *timeout* seconds.
            RuntimeError: If required environment variables are missing.
        """
        client = self._get_client()
        embed_model = os.environ.get(
            "AZURE_FOUNDRY_EMBED_MODEL", "text-embedding-3-small"
        )
        response = await asyncio.wait_for(
            client.embeddings.create(input=texts, model=embed_model),
            timeout=timeout,
        )
        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Try to extract the first JSON object from *text*.

    Args:
        text: Raw LLM output that may contain surrounding prose.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON object is found.
    """
    # Direct parse first.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find the outermost {...} block.
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON object found in LLM response: {text!r}")
