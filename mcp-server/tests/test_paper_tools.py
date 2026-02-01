"""Unit tests for paper tools: semantic_scholar_get_paper, graph_get_paper, graph_add_paper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import sys
from pathlib import Path

mcp_code = Path(__file__).resolve().parent.parent
if str(mcp_code) not in sys.path:
    sys.path.insert(0, str(mcp_code))


@pytest.fixture(autouse=True)
def _reset_neo4j_driver():
    """Ensure get_driver is patched per test."""
    with patch.dict("sys.modules", {"neo4j_driver": MagicMock()}):
        yield


@pytest.mark.asyncio
async def test_semantic_scholar_get_paper_returns_fixed_shape():
    """semantic_scholar_get_paper returns paperId, title, authors, etc.; no DB."""
    from tools.semantic_scholar import semantic_scholar_get_paper, get_paper

    mock_paper = {
        "paperId": "abc123",
        "title": "Test Paper",
        "year": 2023,
        "abstract": "An abstract.",
        "authors": [{"authorId": "a1", "name": "Alice"}],
        "fieldsOfStudy": ["Computer Science"],
        "citationCount": 10,
        "influentialCitationCount": 2,
        "tldr": {"text": "TLDR text"},
        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
        "externalIds": {"ArXiv": "2301.07041", "DOI": "10.1234/xyz"},
    }
    with patch("tools.semantic_scholar.get_paper", new_callable=AsyncMock, return_value=mock_paper):
        result = await semantic_scholar_get_paper("abc123", include_embedding=False)
    assert "error" not in result
    assert result["paperId"] == "abc123"
    assert result["title"] == "Test Paper"
    assert result["year"] == 2023
    assert result["abstract"] == "An abstract."
    assert result["authors"] == [{"authorId": "a1", "name": "Alice"}]
    assert result["fieldsOfStudy"] == ["Computer Science"]
    assert result["citationCount"] == 10
    assert result["influentialCitationCount"] == 2
    assert result["tldr"] == "TLDR text"
    assert result["openAccessPdf"] == "https://example.com/paper.pdf"
    assert result["externalIds"] == {"ArXiv": "2301.07041", "DOI": "10.1234/xyz"}
    assert "added_to_graph" not in result


@pytest.mark.asyncio
async def test_semantic_scholar_get_paper_not_found():
    """semantic_scholar_get_paper returns error dict when paper not found."""
    from tools.semantic_scholar import semantic_scholar_get_paper

    with patch("tools.semantic_scholar.get_paper", new_callable=AsyncMock, return_value=None):
        result = await semantic_scholar_get_paper("nonexistent")
    assert result == {"error": "Paper not found: nonexistent"}


@pytest.mark.asyncio
async def test_semantic_scholar_get_paper_with_embedding():
    """semantic_scholar_get_paper can include embedding when requested."""
    from tools.semantic_scholar import semantic_scholar_get_paper

    mock_paper = {
        "paperId": "p1",
        "title": "Paper",
        "year": 2020,
        "abstract": None,
        "authors": [],
        "fieldsOfStudy": [],
        "citationCount": 0,
        "influentialCitationCount": None,
        "tldr": None,
        "openAccessPdf": None,
        "externalIds": None,
        "embedding": {"vector": [0.1, 0.2, 0.3]},
    }
    with patch("tools.semantic_scholar.get_paper", new_callable=AsyncMock, return_value=mock_paper):
        result = await semantic_scholar_get_paper("p1", include_embedding=True)
    assert result.get("embedding") == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_graph_get_paper_not_configured():
    """graph_get_paper returns error dict when Neo4j not configured."""
    from tools.graph import graph_get_paper

    with patch("tools.graph.get_driver", return_value=None):
        result = await graph_get_paper("123")
    assert result == {"error": "Neo4j not configured."}


@pytest.mark.asyncio
async def test_graph_get_paper_not_in_graph():
    """graph_get_paper returns error dict when paper not found."""
    from tools.graph import graph_get_paper

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = None
    mock_session.run.return_value = mock_result
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_get_paper("999")
    assert result == {"error": "Paper not in graph"}


@pytest.mark.asyncio
async def test_graph_get_paper_found_by_s2_id():
    """graph_get_paper returns paper dict when found by s2_id."""
    from tools.graph import graph_get_paper

    mock_record = {
        "s2_id": "s2-123",
        "arxiv_id": "2301.07041",
        "doi": "10.1234/xyz",
        "title": "A Paper",
        "year": 2023,
        "abstract": "Abstract",
        "citation_count": 5,
        "influential_citation_count": 1,
        "tldr": "TLDR",
        "open_access_url": "https://example.com/pdf",
        "fields_of_study": ["CS"],
    }
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record
    mock_session.run.return_value = mock_result
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_get_paper("s2-123")
    assert "error" not in result
    assert result["s2_id"] == "s2-123"
    assert result["arxiv_id"] == "2301.07041"
    assert result["title"] == "A Paper"
    assert result["fields_of_study"] == ["CS"]


@pytest.mark.asyncio
async def test_graph_get_paper_normalizes_arxiv_prefix():
    """graph_get_paper normalizes ARXIV: prefix for lookup."""
    from tools.graph import graph_get_paper

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = {
        "s2_id": None,
        "arxiv_id": "2301.07041",
        "doi": None,
        "title": "Paper",
        "year": 2023,
        "abstract": None,
        "citation_count": None,
        "influential_citation_count": None,
        "tldr": None,
        "open_access_url": None,
        "fields_of_study": [],
    }
    mock_session.run.return_value = mock_result
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_get_paper("ARXIV:2301.07041")
    assert "error" not in result
    assert result["arxiv_id"] == "2301.07041"
    call_args = mock_session.run.call_args
    assert call_args[1]["paper_id"] == "2301.07041"


@pytest.mark.asyncio
async def test_graph_add_paper_not_configured():
    """graph_add_paper returns string error when Neo4j not configured."""
    from tools.graph import graph_add_paper

    with patch("tools.graph.get_driver", return_value=None):
        result = await graph_add_paper("s2-1", "My Paper")
    assert result == "Neo4j not configured."


@pytest.mark.asyncio
async def test_graph_add_paper_runs_merge_and_returns_message():
    """graph_add_paper runs MERGE Cypher and returns deterministic message."""
    from tools.graph import graph_add_paper

    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_add_paper(
            "s2-abc",
            "Short Title",
            year=2023,
            abstract="Abstract",
            arxiv_id="2301.07041",
            citation_count=10,
            influential_citation_count=2,
            fields_of_study=["Computer Science"],
            authors=[{"authorId": "a1", "name": "Alice"}],
        )
    assert result == "Added/updated paper Short Title (s2-abc)."
    assert mock_session.run.call_count >= 1
    first_call = mock_session.run.call_args_list[0]
    cypher = first_call[0][0]
    params = first_call[1]
    assert "MERGE" in cypher and "Paper" in cypher and "s2_id" in cypher
    assert params["s2_id"] == "s2-abc"
    assert params["title"] == "Short Title"
    assert params["year"] == 2023
    assert params["citation_count"] == 10
    assert params["influential_citation_count"] == 2
    assert params["fields_of_study"] == ["Computer Science"]


@pytest.mark.asyncio
async def test_graph_add_paper_with_embedding():
    """graph_add_paper sets embedding when provided."""
    from tools.graph import graph_add_paper

    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    embedding = [0.1, 0.2, 0.3]
    with patch("tools.graph.get_driver", return_value=mock_driver):
        await graph_add_paper("s2-1", "Paper", embedding=embedding)

    set_embedding_calls = [
        c for c in mock_session.run.call_args_list
        if len(c[0]) and "embedding" in c[0][0]
    ]
    assert len(set_embedding_calls) == 1
    assert set_embedding_calls[0][1]["embedding"] == embedding
