"""Unit tests for paperhound.rerank.

All tests are offline.  The real sentence-transformers library is never imported;
instead tests inject a fake encoder via the ``_encoder`` parameter or monkeypatch
the import machinery.
"""

from __future__ import annotations

import math
import sys
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from paperhound.errors import RerankError
from paperhound.models import Author, Paper, PaperIdentifier
from paperhound.rerank import _cosine, is_available, rerank

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_paper(
    title: str = "A Paper",
    abstract: str | None = "An abstract.",
    arxiv_id: str = "0000.00000",
) -> Paper:
    return Paper(
        title=title,
        abstract=abstract,
        authors=[Author(name="Alice")],
        year=2024,
        identifiers=PaperIdentifier(arxiv_id=arxiv_id),
        sources=["arxiv"],
    )


def _unit_vec(dim: int, hot: int) -> list[float]:
    """Return a one-hot unit vector of length *dim* with a 1 at position *hot*."""
    v = [0.0] * dim
    v[hot] = 1.0
    return v


def _fake_encoder_factory(
    mapping: dict[str, list[float]],
) -> Callable[[list[str]], list[list[float]]]:
    """Return an encoder that looks up pre-set vectors by text; unknown texts get zeros."""

    def encode(texts: list[str]) -> list[list[float]]:
        dim = max(len(v) for v in mapping.values()) if mapping else 4
        return [mapping.get(t, [0.0] * dim) for t in texts]

    return encode


# ---------------------------------------------------------------------------
# _cosine helpers
# ---------------------------------------------------------------------------


class TestCosine:
    def test_identical_vectors(self) -> None:
        v = [1.0, 2.0, 3.0]
        assert math.isclose(_cosine(v, v), 1.0, rel_tol=1e-9)

    def test_orthogonal_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert math.isclose(_cosine(a, b), 0.0, abs_tol=1e-9)

    def test_opposite_vectors(self) -> None:
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert math.isclose(_cosine(a, b), -1.0, rel_tol=1e-9)

    def test_zero_vector_returns_zero(self) -> None:
        assert _cosine([0.0, 0.0], [1.0, 2.0]) == 0.0
        assert _cosine([1.0, 2.0], [0.0, 0.0]) == 0.0


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_returns_true_when_importable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)
        assert is_available() is True

    def test_returns_false_when_not_importable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Ensure the module is *not* in sys.modules and the import will fail.
        monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

        original_import = (
            __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__
        )  # type: ignore[union-attr]

        def mock_import(name: str, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        assert is_available() is False


# ---------------------------------------------------------------------------
# rerank — happy path
# ---------------------------------------------------------------------------


class TestRerankHappyPath:
    """Test that rerank produces the correct ordering with injected encoder."""

    def test_orders_by_cosine_similarity_descending(self) -> None:
        """The paper whose text vector is closest to the query should rank first."""
        query = "attention mechanism"
        paper_a = _make_paper(title="Attention Is All You Need", arxiv_id="1706.03762")
        paper_b = _make_paper(title="Something Unrelated", arxiv_id="2000.00001")
        paper_c = _make_paper(title="Self-Attention Networks", arxiv_id="2000.00002")

        # 3-d embedding space:
        # query → dim 0
        # paper_a text → dim 0  (highest similarity)
        # paper_c text → half on dim 0, half on dim 1
        # paper_b text → dim 1  (lowest similarity)
        mapping = {
            query: _unit_vec(3, 0),
            paper_a.title + " " + paper_a.abstract: _unit_vec(3, 0),
            paper_c.title + " " + paper_c.abstract: [1 / math.sqrt(2), 1 / math.sqrt(2), 0.0],
            paper_b.title + " " + paper_b.abstract: _unit_vec(3, 1),
        }
        encoder = _fake_encoder_factory(mapping)
        result = rerank(query, [paper_a, paper_b, paper_c], _encoder=encoder)

        assert [p.identifiers.arxiv_id for p in result] == [
            "1706.03762",
            "2000.00002",
            "2000.00001",
        ]

    def test_single_candidate_returned_unchanged(self) -> None:
        paper = _make_paper()
        encoder = _fake_encoder_factory(
            {
                "query": [1.0, 0.0],
                paper.title + " " + paper.abstract: [1.0, 0.0],
            }
        )
        result = rerank("query", [paper], _encoder=encoder)
        assert len(result) == 1
        assert result[0] is paper

    def test_returns_new_list(self) -> None:
        papers = [_make_paper(title="P1", arxiv_id="0001.00001")]
        encoder = _fake_encoder_factory(
            {"q": [1.0], papers[0].title + " " + papers[0].abstract: [1.0]}
        )
        result = rerank("q", papers, _encoder=encoder)
        assert result is not papers


# ---------------------------------------------------------------------------
# rerank — edge cases
# ---------------------------------------------------------------------------


class TestRerankEdgeCases:
    def test_empty_candidate_list_returns_empty(self) -> None:
        called: list[bool] = []

        def encoder(texts: list[str]) -> list[list[float]]:
            called.append(True)
            return [[0.0]] * len(texts)

        result = rerank("query", [], _encoder=encoder)
        assert result == []
        assert not called, "encoder should not be called for empty input"

    def test_missing_abstract_falls_back_to_title_only(self) -> None:
        paper = _make_paper(abstract=None)
        # Text used for embedding should be just the title
        title_text = paper.title  # no abstract
        mapping = {
            "q": [1.0, 0.0],
            title_text: [1.0, 0.0],  # title-only key
        }
        encoder = _fake_encoder_factory(mapping)
        result = rerank("q", [paper], _encoder=encoder)
        assert len(result) == 1
        assert result[0].title == paper.title

    def test_missing_title_and_abstract_pushed_to_end(self) -> None:
        # Paper with no embeddable text
        no_text_paper = Paper(
            title="",
            abstract=None,
            identifiers=PaperIdentifier(arxiv_id="0000.00000"),
            sources=[],
        )
        good_paper = _make_paper(title="Real Paper", arxiv_id="1111.11111")

        mapping = {
            "q": [1.0, 0.0],
            good_paper.title + " " + good_paper.abstract: [1.0, 0.0],
        }
        encoder = _fake_encoder_factory(mapping)
        result = rerank("q", [no_text_paper, good_paper], _encoder=encoder)

        # good_paper should come first; no_text_paper at the end
        assert result[0].identifiers.arxiv_id == "1111.11111"
        assert result[-1].identifiers.arxiv_id == "0000.00000"

    def test_identical_similarity_stable_sort(self) -> None:
        """When two papers have equal similarity, original order is preserved."""
        paper_a = _make_paper(title="Alpha", abstract="text", arxiv_id="0001.00001")
        paper_b = _make_paper(title="Beta", abstract="text", arxiv_id="0002.00002")

        # Both map to the same vector → identical cosine similarity
        same_vec = [1.0, 0.0]
        mapping = {
            "q": [1.0, 0.0],
            "Alpha text": same_vec,
            "Beta text": same_vec,
        }
        encoder = _fake_encoder_factory(mapping)
        result = rerank("q", [paper_a, paper_b], _encoder=encoder)

        # Original order should be preserved for ties
        assert result[0].identifiers.arxiv_id == "0001.00001"
        assert result[1].identifiers.arxiv_id == "0002.00002"

    def test_all_papers_missing_text_returns_original_order(self) -> None:
        p1 = Paper(title="", abstract=None, sources=[], identifiers=PaperIdentifier(arxiv_id="A"))
        p2 = Paper(title="", abstract=None, sources=[], identifiers=PaperIdentifier(arxiv_id="B"))

        called: list[bool] = []

        def encoder(texts: list[str]) -> list[list[float]]:
            called.append(True)
            return []

        result = rerank("q", [p1, p2], _encoder=encoder)
        assert [p.identifiers.arxiv_id for p in result] == ["A", "B"]
        assert not called


# ---------------------------------------------------------------------------
# rerank — missing dependency path
# ---------------------------------------------------------------------------


class TestRerankMissingDep:
    def test_raises_rerank_error_when_dep_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When sentence_transformers cannot be imported, RerankError is raised."""
        monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

        original_import = __import__

        def mock_import(name: str, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError("No module named 'sentence_transformers'")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        paper = _make_paper()
        with pytest.raises(RerankError, match="pip install"):
            # No _encoder → will try to import sentence_transformers
            rerank("query", [paper])

    def test_rerank_error_message_contains_install_hint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The RerankError message must contain the pip install hint."""
        monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

        original_import = __import__

        def mock_import(name: str, *args, **kwargs):
            if name == "sentence_transformers":
                raise ImportError
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        paper = _make_paper()
        with pytest.raises(RerankError) as exc_info:
            rerank("query", [paper])

        assert "paperhound[rerank]" in str(exc_info.value)
