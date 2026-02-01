"""Unit tests for author tools: semantic_scholar_get_author, graph_get_author, graph_add_author."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Tests run from repo root or mcp-server; ensure tools are importable
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
async def test_semantic_scholar_get_author_returns_fixed_shape():
    """semantic_scholar_get_author returns authorId, name, affiliations, homepage, paperCount, citationCount, hIndex; no DB."""
    from tools.semantic_scholar import semantic_scholar_get_author, get_author, get_author_papers

    mock_author = {
        "authorId": "123",
        "name": "Alice Chen",
        "affiliations": ["MIT"],
        "homepage": "https://alice.example.com",
        "paperCount": 10,
        "citationCount": 100,
        "hIndex": 5,
    }
    with patch("tools.semantic_scholar.get_author", new_callable=AsyncMock, return_value=mock_author):
        result = await semantic_scholar_get_author("123", include_papers=False)
    assert "error" not in result
    assert result["authorId"] == "123"
    assert result["name"] == "Alice Chen"
    assert result["affiliations"] == ["MIT"]
    assert result["homepage"] == "https://alice.example.com"
    assert result["paperCount"] == 10
    assert result["citationCount"] == 100
    assert result["hIndex"] == 5
    assert "added_to_graph" not in result


@pytest.mark.asyncio
async def test_semantic_scholar_get_author_not_found():
    """semantic_scholar_get_author returns error dict when author not found."""
    from tools.semantic_scholar import semantic_scholar_get_author

    with patch("tools.semantic_scholar.get_author", new_callable=AsyncMock, return_value=None):
        result = await semantic_scholar_get_author("nonexistent")
    assert result == {"error": "Author not found: nonexistent"}


@pytest.mark.asyncio
async def test_semantic_scholar_get_author_with_papers():
    """semantic_scholar_get_author can include papers list."""
    from tools.semantic_scholar import semantic_scholar_get_author

    mock_author = {
        "authorId": "456",
        "name": "Bob",
        "affiliations": [],
        "homepage": None,
        "paperCount": 2,
        "citationCount": 0,
        "hIndex": 0,
    }
    mock_papers = {
        "data": [
            {
                "paperId": "p1",
                "title": "Paper 1",
                "year": 2020,
                "citationCount": 5,
                "externalIds": {"ArXiv": "2001.00001"},
            },
        ],
    }
    with (
        patch("tools.semantic_scholar.get_author", new_callable=AsyncMock, return_value=mock_author),
        patch("tools.semantic_scholar.get_author_papers", new_callable=AsyncMock, return_value=mock_papers),
    ):
        result = await semantic_scholar_get_author("456", include_papers=True, papers_limit=10)
    assert "papers" in result
    assert len(result["papers"]) == 1
    assert result["papers"][0]["paperId"] == "p1"
    assert result["papers"][0]["arxivId"] == "2001.00001"


@pytest.mark.asyncio
async def test_graph_get_author_not_configured():
    """graph_get_author returns error dict when Neo4j not configured."""
    from tools.graph import graph_get_author

    with patch("tools.graph.get_driver", return_value=None):
        result = await graph_get_author("123")
    assert result == {"error": "Neo4j not configured."}


@pytest.mark.asyncio
async def test_graph_get_author_not_in_graph():
    """graph_get_author returns error dict when author not found."""
    from tools.graph import graph_get_author

    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = None
    mock_session.run.return_value = mock_result
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_get_author("999")
    assert result == {"error": "Author not in graph"}


@pytest.mark.asyncio
async def test_graph_get_author_found():
    """graph_get_author returns author dict when found."""
    from tools.graph import graph_get_author

    mock_record = {
        "authorId": "123",
        "name": "Alice",
        "affiliations": ["MIT"],
        "homepage": "https://alice.example.com",
        "paper_count": 10,
        "citation_count": 100,
        "h_index": 5,
    }
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.single.return_value = mock_record
    mock_session.run.return_value = mock_result
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_get_author("123")
    assert "error" not in result
    assert result["authorId"] == "123"
    assert result["name"] == "Alice"
    assert result["paper_count"] == 10
    assert result["citation_count"] == 100
    assert result["h_index"] == 5


@pytest.mark.asyncio
async def test_graph_add_author_not_configured():
    """graph_add_author returns string error when Neo4j not configured."""
    from tools.graph import graph_add_author

    with patch("tools.graph.get_driver", return_value=None):
        result = await graph_add_author("123", "Alice")
    assert result == "Neo4j not configured."


@pytest.mark.asyncio
async def test_graph_add_author_runs_merge_and_returns_message():
    """graph_add_author runs MERGE Cypher and returns deterministic message."""
    from tools.graph import graph_add_author

    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    with patch("tools.graph.get_driver", return_value=mock_driver):
        result = await graph_add_author(
            "author-s2-id",
            "Alice Chen",
            affiliations=["MIT"],
            paper_count=10,
            citation_count=100,
            h_index=5,
        )
    assert "Added/updated author Alice Chen (author-s2-id)." == result
    mock_session.run.assert_called_once()
    call_args = mock_session.run.call_args
    cypher = call_args[0][0]
    params = call_args[1]
    assert "MERGE" in cypher and "Author" in cypher and "s2_id" in cypher
    assert params["author_id"] == "author-s2-id"
    assert params["name"] == "Alice Chen"
    assert params["affiliations"] == ["MIT"]
    assert params["paper_count"] == 10
    assert params["citation_count"] == 100
    assert params["h_index"] == 5
