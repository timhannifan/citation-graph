"""arXiv tools: search and add papers to the citation graph (metadata from arXiv; citations from Semantic Scholar)."""

import logging
import re
import urllib.parse
from typing import Annotated, Any

import defusedxml.ElementTree as ET
import httpx
from neo4j_driver import get_driver
from pydantic import Field

from .semantic_scholar import fetch_citations_semantic_scholar

logger = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"


async def fetch_arxiv_metadata(arxiv_id: str) -> dict[str, Any] | None:
    """Fetch paper metadata from arXiv API."""
    arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", arxiv_id)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    query = urllib.parse.urlencode({"id_list": arxiv_id})
    url = f"{ARXIV_API}?{query}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, timeout=30)
        resp.raise_for_status()

    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    root = ET.fromstring(resp.text)
    entry = root.find("atom:entry", ns)

    if entry is None:
        return None

    authors = []
    for author in entry.findall("atom:author", ns):
        name = author.find("atom:name", ns)
        if name is not None and name.text:
            authors.append(name.text)

    categories = []
    for cat in entry.findall("arxiv:primary_category", ns):
        if cat.get("term"):
            categories.append(cat.get("term"))
    for cat in entry.findall("atom:category", ns):
        term = cat.get("term")
        if term and term not in categories:
            categories.append(term)

    title_el = entry.find("atom:title", ns)
    abstract_el = entry.find("atom:summary", ns)
    published_el = entry.find("atom:published", ns)

    return {
        "arxiv_id": arxiv_id,
        "title": " ".join(title_el.text.split())
        if title_el is not None and title_el.text
        else None,
        "abstract": " ".join(abstract_el.text.split())
        if abstract_el is not None and abstract_el.text
        else None,
        "authors": authors,
        "categories": categories[:5],
        "year": int(published_el.text[:4])
        if published_el is not None and published_el.text
        else None,
    }


# --- MCP tools ---


async def arxiv_search(
    query: Annotated[str, Field(description="Search query for arXiv papers")],
    max_results: Annotated[int, Field(default=5, ge=1, le=20, description="Max results")] = 5,
) -> str:
    """Search arXiv for papers. Returns paper IDs and titles that can be added with arxiv_add_paper. Use when the user wants to search or find papers by topic/keyword on arXiv. Call this first when they ask to `search for papers on X` or `find papers about Y`."""
    params = urllib.parse.urlencode(
        {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
        }
    )

    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{ARXIV_API}?{params}", timeout=30)
        resp.raise_for_status()

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(resp.text)

    results = []
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        title_el = entry.find("atom:title", ns)
        if id_el is not None and id_el.text:
            arxiv_id = id_el.text.split("/abs/")[-1]
            title = (
                " ".join(title_el.text.split())
                if title_el is not None and title_el.text
                else "Unknown"
            )
            results.append(f"  {arxiv_id}: {title[:80]}")

    if not results:
        return "No results found."
    return "arXiv Search Results:\n" + "\n".join(results)


async def arxiv_add_paper(
    arxiv_id: Annotated[str, Field(description="arXiv paper ID (e.g., '2301.07041' or full URL)")],
    include_references: Annotated[
        bool, Field(default=True, description="Also add papers this cites")
    ] = True,
    include_citations: Annotated[
        bool, Field(default=False, description="Also add papers that cite this")
    ] = False,
) -> str:
    """
    Add an arXiv paper to the citation graph.

    Fetches metadata from arXiv and citation data from Semantic Scholar.
    Creates Paper, Author, and Topic nodes with appropriate relationships.
    Safe to call multiple times (uses MERGE for idempotency).
    """
    driver = get_driver()
    if driver is None:
        return "Neo4j not configured."

    arxiv_id = arxiv_id.strip()
    arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", arxiv_id)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    meta = await fetch_arxiv_metadata(arxiv_id)
    if not meta or not meta.get("title"):
        return f"Could not fetch paper {arxiv_id} from arXiv."

    with driver.session() as session:
        session.run(
            """
            MERGE (p:Paper {arxiv_id: $arxiv_id})
            ON CREATE SET p.title = $title, p.year = $year, p.abstract = $abstract, p.citations = 0
            ON MATCH SET p.title = $title, p.year = $year, p.abstract = $abstract
        """,
            arxiv_id=meta["arxiv_id"],
            title=meta["title"],
            year=meta["year"],
            abstract=meta["abstract"],
        )

        for author_name in meta["authors"]:
            session.run(
                """
                MERGE (a:Author {name: $name})
                WITH a
                MATCH (p:Paper {arxiv_id: $arxiv_id})
                MERGE (a)-[:AUTHORED]->(p)
            """,
                name=author_name,
                arxiv_id=meta["arxiv_id"],
            )

        for category in meta["categories"]:
            session.run(
                """
                MERGE (t:Topic {name: $name})
                WITH t
                MATCH (p:Paper {arxiv_id: $arxiv_id})
                MERGE (p)-[:ABOUT]->(t)
            """,
                name=category,
                arxiv_id=meta["arxiv_id"],
            )

    result_parts = [
        f"Added: {meta['title'][:60]}...",
        f"  Authors: {', '.join(meta['authors'][:3])}",
    ]

    if include_references or include_citations:
        citation_data = await fetch_citations_semantic_scholar(arxiv_id)

        if include_references and citation_data["references"]:
            ref_ids = [r["arxiv_id"] for r in citation_data["references"][:10]]
            with driver.session() as session:
                for ref in citation_data["references"][:10]:
                    session.run(
                        """
                        MERGE (ref:Paper {arxiv_id: $ref_id})
                        ON CREATE SET ref.title = $title, ref.citations = 0
                        WITH ref
                        MATCH (p:Paper {arxiv_id: $paper_id})
                        MERGE (p)-[:CITES]->(ref)
                    """,
                        ref_id=ref["arxiv_id"],
                        title=ref.get("title", "Unknown"),
                        paper_id=arxiv_id,
                    )
            result_parts.append(f"  Added {len(ref_ids)} references")

        if include_citations and citation_data["citations"]:
            cit_ids = [c["arxiv_id"] for c in citation_data["citations"][:10]]
            with driver.session() as session:
                for cit in citation_data["citations"][:10]:
                    session.run(
                        """
                        MERGE (citer:Paper {arxiv_id: $citer_id})
                        ON CREATE SET citer.title = $title, citer.citations = 0
                        WITH citer
                        MATCH (p:Paper {arxiv_id: $paper_id})
                        MERGE (citer)-[:CITES]->(p)
                    """,
                        citer_id=cit["arxiv_id"],
                        title=cit.get("title", "Unknown"),
                        paper_id=arxiv_id,
                    )
            result_parts.append(f"  Added {len(cit_ids)} citing papers")

    with driver.session() as session:
        session.run("""
            MATCH (p:Paper)<-[c:CITES]-()
            WITH p, count(c) as cnt
            SET p.citations = cnt
        """)

    return "\n".join(result_parts)


def register(mcp):
    """Register arXiv tools with the FastMCP instance."""
    mcp.tool()(arxiv_search)
    mcp.tool()(arxiv_add_paper)
