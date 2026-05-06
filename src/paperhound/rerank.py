"""Optional embedding-based reranking for search results.

Requires the ``rerank`` extra:  pip install 'paperhound[rerank]'
"""

from __future__ import annotations

import math
from collections.abc import Callable

from paperhound.errors import RerankError
from paperhound.models import Paper

_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

# Module-level cache: model_name → loaded SentenceTransformer instance.
_model_cache: dict[str, object] = {}


def is_available() -> bool:
    """Return True if sentence-transformers is importable, False otherwise."""
    try:
        import importlib

        importlib.import_module("sentence_transformers")
        return True
    except ImportError:
        return False


def _cosine(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors using only stdlib."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _default_encoder(model_name: str) -> Callable[[list[str]], list[list[float]]]:
    """Return a callable that encodes texts using a cached SentenceTransformer."""
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RerankError(
            "Rerank requires sentence-transformers. Install with: pip install 'paperhound[rerank]'"
        ) from exc

    if model_name not in _model_cache:
        try:
            _model_cache[model_name] = SentenceTransformer(model_name)
        except Exception as exc:
            raise RerankError(f"Failed to load rerank model {model_name!r}: {exc}") from exc

    model = _model_cache[model_name]

    def encode(texts: list[str]) -> list[list[float]]:
        vecs = model.encode(texts, convert_to_numpy=False, show_progress_bar=False)  # type: ignore[union-attr]
        # sentence-transformers may return numpy arrays or lists; normalise.
        return [list(map(float, v)) for v in vecs]

    return encode


def rerank(
    query: str,
    papers: list[Paper],
    model_name: str | None = None,
    *,
    _encoder: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[Paper]:
    """Rerank *papers* by cosine similarity between the query and each paper.

    Parameters
    ----------
    query:
        The search query string.
    papers:
        Candidates to rerank.  A new list is returned; the input is not mutated.
    model_name:
        SentenceTransformer model name (defaults to
        ``"sentence-transformers/all-MiniLM-L6-v2"``).
    _encoder:
        Inject a custom encoder for testing.  Must accept a ``list[str]`` and
        return a ``list[list[float]]``.  When provided, *model_name* is ignored
        and the real sentence-transformers library is never imported.

    Returns
    -------
    list[Paper]
        A new list sorted by descending cosine similarity.  Papers with neither
        a title nor an abstract (i.e. those we cannot embed meaningfully) are
        pushed to the end, preserving their relative order.
    """
    if not papers:
        return []

    effective_model = model_name or _DEFAULT_MODEL

    if _encoder is None:
        encode = _default_encoder(effective_model)
    else:
        encode = _encoder

    # Separate papers we can embed from those we cannot.
    embeddable: list[tuple[int, Paper, str]] = []  # (original_index, paper, text)
    no_text: list[tuple[int, Paper]] = []

    for idx, paper in enumerate(papers):
        text_parts = []
        if paper.title:
            text_parts.append(paper.title)
        if paper.abstract:
            text_parts.append(paper.abstract)
        if text_parts:
            embeddable.append((idx, paper, " ".join(text_parts)))
        else:
            no_text.append((idx, paper))

    if not embeddable:
        return list(papers)

    # Encode query + all candidate texts in one batch for efficiency.
    texts = [query] + [t for _, _, t in embeddable]
    vectors = encode(texts)
    query_vec = vectors[0]
    candidate_vecs = vectors[1:]

    # Compute similarities and sort (desc). Use negative index as tiebreaker to
    # produce a *stable* sort: equal-similarity papers keep their original order.
    scored = [
        (
            _cosine(query_vec, candidate_vecs[i]),
            -(embeddable[i][0]),  # stable: earlier original index wins on tie
            embeddable[i][1],
        )
        for i in range(len(embeddable))
    ]
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)

    ranked = [paper for _, _, paper in scored]
    ranked.extend(paper for _, paper in no_text)
    return ranked
