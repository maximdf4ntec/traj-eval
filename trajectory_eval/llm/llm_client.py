"""LLM client — local embedding via TF-IDF, no network required.

The ``embed`` method delegates to :class:`~trajectory_eval.llm.local_embedder.LocalEmbedder`
(TF-IDF, pure Python + stdlib).  The ``complete`` method is not used by any
active code path and raises ``NotImplementedError`` if called.

``_extract_json_from_text`` is kept for backward compatibility in case any
test or script imports it directly.
"""

from __future__ import annotations

import json
import re
from typing import Any

from trajectory_eval.llm.local_embedder import LocalEmbedder

_local_embedder = LocalEmbedder()


class LLMClient:
    """Local embedding client.  embed() uses TF-IDF; complete() is disabled."""

    async def embed(self, texts: list[str], timeout: float = 30.0) -> list[list[float]]:
        """Return TF-IDF vectors via :class:`~trajectory_eval.llm.local_embedder.LocalEmbedder`.

        Args:
            texts: Input strings to embed.
            timeout: Ignored (local computation).

        Returns:
            L2-normalised TF-IDF float vectors.
        """
        return await _local_embedder.embed(texts, timeout=timeout)

    async def complete(self, prompt: str, timeout: float = 30.0) -> str:
        """Not implemented — LLM completion is not supported.

        Args:
            prompt: Unused.
            timeout: Unused.

        Raises:
            NotImplementedError: Always.
        """
        raise NotImplementedError(
            "LLMClient.complete() is not implemented. "
            "LLM-based soft rule generation is not supported."
        )


def _extract_json_from_text(text: str) -> dict[str, Any]:
    """Try to extract the first JSON object from *text*.

    Args:
        text: Raw text that may contain a JSON object.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON object is found.
    """
    try:
        return json.loads(text)  # type: ignore[return-value]
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())  # type: ignore[return-value]
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON object found in text: {text!r}")
