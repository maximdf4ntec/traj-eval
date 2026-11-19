"""Local TF-IDF cosine embedder — no network, no external dependencies.

Implements the same ``embed(texts) -> list[list[float]]`` interface as the
former Azure client so :class:`~trajectory_eval.generator.rules.monotonic_progress.MonotonicProgressRule`
works without modification.

TF-IDF is appropriate here because MonotonicProgressRule uses a stagnation
threshold of 0.95: it only fires when two responses are near-identical at the
token level.  Semantic paraphrasing at that similarity level is indistinguishable
from copy-paste in practice, so a bag-of-words representation is sufficient.

The vocabulary and IDF weights are built fresh from each batch, which is correct
because all comparisons for a single trajectory run share the same vocabulary.
"""

from __future__ import annotations

import math
import re
from collections import Counter


def _tokenize(text: str) -> list[str]:
    """Lowercase and split text into alphanumeric tokens.

    Args:
        text: Raw input string.

    Returns:
        List of lowercase tokens (letters, digits, underscores, dots, slashes, hyphens).
    """
    return re.findall(r"[a-z0-9_./-]+", text.lower())


def tfidf_vectors(texts: list[str]) -> list[list[float]]:
    """Compute L2-normalised TF-IDF vectors for a batch of texts.

    Vocabulary and IDF weights are derived from the batch itself (corpus IDF).
    Vectors are L2-normalised so cosine similarity is a simple dot product.

    Args:
        texts: Input strings.  Order is preserved in the output.

    Returns:
        One float vector per input text, all of the same dimensionality
        (the vocabulary size).  Empty-token texts produce a zero vector.
    """
    tokenized = [_tokenize(t) for t in texts]

    # Document frequency: how many documents contain each term.
    df: Counter[str] = Counter()
    for tokens in tokenized:
        df.update(set(tokens))

    vocab = sorted(df)
    n = len(texts)

    # Smoothed IDF: log((N+1)/(df+1)) + 1  (sklearn convention, avoids zero).
    idf = {term: math.log((n + 1) / (df[term] + 1)) + 1.0 for term in vocab}

    vectors: list[list[float]] = []
    for tokens in tokenized:
        tf = Counter(tokens)
        total = max(len(tokens), 1)
        vec = [tf[term] / total * idf[term] for term in vocab]

        # L2 normalise.
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0.0:
            vec = [x / norm for x in vec]

        vectors.append(vec)

    return vectors


class LocalEmbedder:
    """Offline TF-IDF embedder with the same async interface as LLMClient.

    Instantiation is free; no environment variables or network required.

    Example::

        embedder = LocalEmbedder()
        vecs = await embedder.embed(["hello world", "goodbye world"])
    """

    async def embed(self, texts: list[str], timeout: float = 30.0) -> list[list[float]]:
        """Return TF-IDF vectors for *texts*.

        The *timeout* parameter is accepted for interface compatibility but is
        not used (computation is synchronous and local).

        Args:
            texts: Input strings to embed.
            timeout: Ignored.

        Returns:
            L2-normalised TF-IDF float vectors, one per input text.
        """
        return tfidf_vectors(texts)
