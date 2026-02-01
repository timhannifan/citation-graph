# semantic_scholar.py
"""Semantic Scholar API client with rate limiting and caching."""

import asyncio
import logging
import os
import time
from typing import Annotated, Any

import httpx
from neo4j_driver import get_driver
from pydantic import Field


logger = logging.getLogger(__name__)

# API configuration
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")

# Rate limiting: space requests to avoid 429 (default 2s between requests)
SEMANTIC_SCHOLAR_DELAY = float(os.getenv("SEMANTIC_SCHOLAR_DELAY_SECONDS", "2"))
_last_call: list[float] = [0.0]
_first_request_done = False
_lock = asyncio.Lock()

# HTTP status codes
HTTP_NOT_FOUND = 404
HTTP_TOO_MANY_REQUESTS = 429


def _get_headers() -> dict[str, str]:
    """Get headers including API key if available."""
    headers = {"Accept": "application/json"}
    if SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = SEMANTIC_SCHOLAR_API_KEY
    return headers


async def _rate_limit() -> None:
    """Enforce minimum delay between API calls."""
    async with _lock:
        now = time.monotonic()
        elapsed = now - _last_call[0]
        if elapsed < SEMANTIC_SCHOLAR_DELAY:
            wait = SEMANTIC_SCHOLAR_DELAY - elapsed
            logger.debug("Semantic Scholar rate limit: waiting %.2fs", wait)
            await asyncio.sleep(wait)
        _last_call[0] = time.monotonic()


async def _request(
    method: str,
    endpoint: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    retry_count: int = 0,
) -> dict[str, Any] | None:
    """Make a rate-limited request to Semantic Scholar API."""
    global _first_request_done
    # Wait before first request so we don't hit the API at t=0 (1 req/sec across users)
    if not _first_request_done:
        async with _lock:
            if not _first_request_done:
                logger.info(
                    "Semantic Scholar: API key %s; waiting %.1fs before first request",
                    "configured" if SEMANTIC_SCHOLAR_API_KEY else "NOT SET (anonymous limit)",
                    SEMANTIC_SCHOLAR_DELAY,
                )
                await asyncio.sleep(SEMANTIC_SCHOLAR_DELAY)
                _first_request_done = True
    await _rate_limit()

    url = f"{SEMANTIC_SCHOLAR_API}{endpoint}"
    headers = _get_headers()

    async with httpx.AsyncClient() as client:
        try:
            if method == "GET":
                resp = await client.get(url, params=params, headers=headers, timeout=30)
            elif method == "POST":
                resp = await client.post(url, params=params, json=json_body, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == HTTP_NOT_FOUND:
                return None

            if resp.status_code == HTTP_TOO_MANY_REQUESTS:
                if retry_count >= 2:
                    logger.error("Semantic Scholar rate limit exceeded after retries")
                    return {"error": "Rate limit exceeded"}

                retry_after = int(resp.headers.get("Retry-After", "60"))
                logger.warning("Rate limited (429), waiting %ds before retry", retry_after)
                await asyncio.sleep(retry_after)
                # Mark "last call" as now so the next _rate_limit() enforces our delay before retry
                async with _lock:
                    _last_call[0] = time.monotonic()
                return await _request(method, endpoint, params, json_body, retry_count + 1)

            resp.raise_for_status()
            return resp.json()

        except httpx.HTTPStatusError as e:
            logger.error("Semantic Scholar API error: %s", e)
            return {"error": str(e)}
        except httpx.RequestError as e:
            logger.error("Semantic Scholar request failed: %s", e)
            return {"error": str(e)}


# --- Paper endpoints ---

# Default fields for paper queries
PAPER_FIELDS = ",".join([
    "paperId",
    "externalIds",
    "title",
    "abstract",
    "year",
    "authors",
    "fieldsOfStudy",
    "s2FieldsOfStudy",
    "publicationTypes",
    "citationCount",
    "influentialCitationCount",
    "openAccessPdf",
    "tldr",
])

PAPER_FIELDS_WITH_EMBEDDING = PAPER_FIELDS + ",embedding"

PAPER_FIELDS_WITH_CITATIONS = PAPER_FIELDS + ",references.paperId,references.externalIds,references.title,citations.paperId,citations.externalIds,citations.title"


async def get_paper(
    paper_id: str,
    include_embedding: bool = False,
    include_citations: bool = False,
) -> dict[str, Any] | None:
    """
    Get paper details by ID.

    Args:
        paper_id: Semantic Scholar ID, arXiv ID (as "ARXIV:id"), DOI, etc.
        include_embedding: Include SPECTER2 embedding (768-dim vector)
        include_citations: Include references and citations lists
    """
    fields = PAPER_FIELDS
    if include_embedding:
        fields = PAPER_FIELDS_WITH_EMBEDDING
    elif include_citations:
        fields = PAPER_FIELDS_WITH_CITATIONS

    return await _request("GET", f"/paper/{paper_id}", params={"fields": fields})


async def search_papers(
    query: str,
    limit: int = 10,
    year: str | None = None,
    fields_of_study: list[str] | None = None,
    min_citation_count: int | None = None,
    open_access_only: bool = False,
) -> dict[str, Any] | None:
    """
    Search for papers by keyword.

    Args:
        query: Search query
        limit: Max results (up to 100)
        year: Year or range (e.g., "2020", "2018-2022", "2020-")
        fields_of_study: Filter by fields (e.g., ["Computer Science", "Mathematics"])
        min_citation_count: Minimum citations
        open_access_only: Only return papers with open access PDFs
    """
    params = {
        "query": query,
        "limit": min(limit, 100),
        "fields": PAPER_FIELDS,
    }

    if year:
        params["year"] = year
    if fields_of_study:
        params["fieldsOfStudy"] = ",".join(fields_of_study)
    if min_citation_count:
        params["minCitationCount"] = min_citation_count
    if open_access_only:
        params["openAccessPdf"] = ""

    return await _request("GET", "/paper/search", params=params)


async def get_paper_batch(
    paper_ids: list[str],
    include_embedding: bool = False,
) -> list[dict[str, Any]]:
    """
    Fetch multiple papers in one request (up to 500).

    Args:
        paper_ids: List of paper IDs (S2 IDs, ARXIV:id, DOI:doi, etc.)
        include_embedding: Include SPECTER2 embeddings
    """
    if not paper_ids:
        return []

    fields = PAPER_FIELDS_WITH_EMBEDDING if include_embedding else PAPER_FIELDS

    # API limit is 500 papers per batch
    batch_size = 500
    all_papers = []

    for i in range(0, len(paper_ids), batch_size):
        batch = paper_ids[i : i + batch_size]
        result = await _request(
            "POST",
            "/paper/batch",
            params={"fields": fields},
            json_body={"ids": batch},
        )
        if result and not isinstance(result, dict) or "error" not in result:
            # Result is a list for batch endpoint
            if isinstance(result, list):
                all_papers.extend([p for p in result if p is not None])

    return all_papers


async def get_paper_citations(
    paper_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any] | None:
    """Get papers that cite this paper (paginated)."""
    fields = "paperId,externalIds,title,year,authors,citationCount"
    return await _request(
        "GET",
        f"/paper/{paper_id}/citations",
        params={"fields": fields, "limit": limit, "offset": offset},
    )


async def get_paper_references(
    paper_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any] | None:
    """Get papers that this paper cites (paginated)."""
    fields = "paperId,externalIds,title,year,authors,citationCount"
    return await _request(
        "GET",
        f"/paper/{paper_id}/references",
        params={"fields": fields, "limit": limit, "offset": offset},
    )


# --- Author endpoints ---

AUTHOR_FIELDS = ",".join([
    "authorId",
    "name",
    "affiliations",
    "homepage",
    "paperCount",
    "citationCount",
    "hIndex",
])


async def get_author(author_id: str) -> dict[str, Any] | None:
    """Get author details by Semantic Scholar author ID."""
    return await _request("GET", f"/author/{author_id}", params={"fields": AUTHOR_FIELDS})


async def search_authors(query: str, limit: int = 10) -> dict[str, Any] | None:
    """Search for authors by name."""
    return await _request(
        "GET",
        "/author/search",
        params={"query": query, "limit": min(limit, 100), "fields": AUTHOR_FIELDS},
    )


async def get_author_papers(
    author_id: str,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any] | None:
    """Get papers by an author (paginated)."""
    fields = "paperId,externalIds,title,year,citationCount,influentialCitationCount"
    return await _request(
        "GET",
        f"/author/{author_id}/papers",
        params={"fields": fields, "limit": limit, "offset": offset},
    )


# --- Utility functions ---


def extract_arxiv_id(paper: dict[str, Any]) -> str | None:
    """Extract arXiv ID from paper's externalIds."""
    ext_ids = paper.get("externalIds") or {}
    return ext_ids.get("ArXiv")


def extract_doi(paper: dict[str, Any]) -> str | None:
    """Extract DOI from paper's externalIds."""
    ext_ids = paper.get("externalIds") or {}
    return ext_ids.get("DOI")


async def semantic_scholar_paper(
    paper_id: Annotated[str, Field(description="Paper ID: S2 ID, 'ARXIV:2301.07041', 'DOI:10.1234/...', or URL")],
    add_to_graph: Annotated[bool, Field(default=True, description="Add/update paper in Neo4j")] = True,
    include_embedding: Annotated[bool, Field(default=False, description="Fetch SPECTER2 embedding")] = False,
) -> dict[str, Any]:
    """
    Get detailed paper information from Semantic Scholar.

    Returns title, abstract, authors, fieldsOfStudy, TLDR summary, citation counts,
    and open access PDF link if available. Optionally stores in Neo4j.
    """
    paper = await get_paper(paper_id, include_embedding=include_embedding)

    if not paper:
        return {"error": f"Paper not found: {paper_id}"}
    if "error" in paper:
        return paper

    result = {
        "paperId": paper.get("paperId"),
        "title": paper.get("title"),
        "year": paper.get("year"),
        "abstract": paper.get("abstract"),
        "authors": [
            {"id": a.get("authorId"), "name": a.get("name")}
            for a in (paper.get("authors") or [])
        ],
        "fieldsOfStudy": paper.get("fieldsOfStudy") or [],
        "s2FieldsOfStudy": paper.get("s2FieldsOfStudy") or [],
        "citationCount": paper.get("citationCount"),
        "influentialCitationCount": paper.get("influentialCitationCount"),
        "tldr": paper.get("tldr", {}).get("text") if paper.get("tldr") else None,
        "openAccessPdf": paper.get("openAccessPdf", {}).get("url") if paper.get("openAccessPdf") else None,
        "externalIds": paper.get("externalIds"),
    }

    if include_embedding and paper.get("embedding"):
        result["embedding"] = paper["embedding"].get("vector")

    # Add to Neo4j if requested
    if add_to_graph:
        driver = get_driver()
        if driver:
            arxiv_id = extract_arxiv_id(paper)
            with driver.session() as session:
                # Use S2 paper ID as primary key, arxiv_id as optional
                session.run(
                    """
                    MERGE (p:Paper {s2_id: $s2_id})
                    SET p.title = $title,
                        p.year = $year,
                        p.abstract = $abstract,
                        p.arxiv_id = $arxiv_id,
                        p.doi = $doi,
                        p.citation_count = $citation_count,
                        p.influential_citation_count = $influential_citations,
                        p.tldr = $tldr,
                        p.open_access_url = $open_access_url,
                        p.fields_of_study = $fields_of_study,
                        p.updated_at = datetime()
                    """,
                    s2_id=paper.get("paperId"),
                    title=paper.get("title"),
                    year=paper.get("year"),
                    abstract=paper.get("abstract"),
                    arxiv_id=arxiv_id,
                    doi=extract_doi(paper),
                    citation_count=paper.get("citationCount"),
                    influential_citations=paper.get("influentialCitationCount"),
                    tldr=paper.get("tldr", {}).get("text") if paper.get("tldr") else None,
                    open_access_url=paper.get("openAccessPdf", {}).get("url") if paper.get("openAccessPdf") else None,
                    fields_of_study=paper.get("fieldsOfStudy") or [],
                )

                # Add authors
                for author in paper.get("authors") or []:
                    if author.get("authorId"):
                        session.run(
                            """
                            MERGE (a:Author {s2_id: $author_id})
                            SET a.name = $name
                            WITH a
                            MATCH (p:Paper {s2_id: $paper_id})
                            MERGE (a)-[:AUTHORED]->(p)
                            """,
                            author_id=author["authorId"],
                            name=author.get("name"),
                            paper_id=paper.get("paperId"),
                        )

                # Add fields of study as topics
                for field in paper.get("fieldsOfStudy") or []:
                    session.run(
                        """
                        MERGE (t:Topic {name: $name})
                        WITH t
                        MATCH (p:Paper {s2_id: $paper_id})
                        MERGE (p)-[:ABOUT]->(t)
                        """,
                        name=field,
                        paper_id=paper.get("paperId"),
                    )

                # Store embedding if present
                if include_embedding and paper.get("embedding"):
                    session.run(
                        """
                        MATCH (p:Paper {s2_id: $paper_id})
                        SET p.embedding = $embedding
                        """,
                        paper_id=paper.get("paperId"),
                        embedding=paper["embedding"].get("vector"),
                    )

            result["added_to_graph"] = True

    return result


async def semantic_scholar_search(
    query: Annotated[str, Field(description="Search query")],
    limit: Annotated[int, Field(default=10, ge=1, le=100, description="Max results")] = 10,
    year: Annotated[str | None, Field(default=None, description="Year or range: '2020', '2018-2022', '2020-'")] = None,
    fields_of_study: Annotated[list[str] | None, Field(default=None, description="Filter by fields, e.g. ['Computer Science']")] = None,
    min_citations: Annotated[int | None, Field(default=None, description="Minimum citation count")] = None,
    open_access_only: Annotated[bool, Field(default=False, description="Only open access papers")] = False,
) -> dict[str, Any]:
    """
    Search Semantic Scholar for papers by keyword.

    More comprehensive than arXiv search—covers all academic disciplines.
    Returns paper IDs that can be added to the graph with semantic_scholar_paper.
    """
    result = await search_papers(
        query=query,
        limit=limit,
        year=year,
        fields_of_study=fields_of_study,
        min_citation_count=min_citations,
        open_access_only=open_access_only,
    )

    if not result:
        return {"error": "Search failed", "papers": []}
    if "error" in result:
        return result

    papers = []
    for paper in result.get("data") or []:
        papers.append({
            "paperId": paper.get("paperId"),
            "title": paper.get("title"),
            "year": paper.get("year"),
            "citationCount": paper.get("citationCount"),
            "tldr": paper.get("tldr", {}).get("text") if paper.get("tldr") else None,
            "arxivId": extract_arxiv_id(paper),
            "openAccess": bool(paper.get("openAccessPdf")),
        })

    return {
        "total": result.get("total", len(papers)),
        "papers": papers,
    }


async def semantic_scholar_author(
    author_id: Annotated[str, Field(description="Semantic Scholar author ID")],
    add_to_graph: Annotated[bool, Field(default=True, description="Add/update author in Neo4j")] = True,
    include_papers: Annotated[bool, Field(default=False, description="Also fetch author's papers")] = False,
    papers_limit: Annotated[int, Field(default=20, ge=1, le=100, description="Max papers to fetch")] = 20,
) -> dict[str, Any]:
    """
    Get author details from Semantic Scholar.

    Returns name, affiliations, h-index, citation count, paper count.
    Optionally fetches their papers and adds everything to Neo4j.
    """
    author = await get_author(author_id)

    if not author:
        return {"error": f"Author not found: {author_id}"}
    if "error" in author:
        return author

    result = {
        "authorId": author.get("authorId"),
        "name": author.get("name"),
        "affiliations": author.get("affiliations") or [],
        "homepage": author.get("homepage"),
        "paperCount": author.get("paperCount"),
        "citationCount": author.get("citationCount"),
        "hIndex": author.get("hIndex"),
    }

    # Fetch papers if requested
    if include_papers:
        papers_result = await get_author_papers(author_id, limit=papers_limit)
        if papers_result and "data" in papers_result:
            result["papers"] = [
                {
                    "paperId": p.get("paperId"),
                    "title": p.get("title"),
                    "year": p.get("year"),
                    "citationCount": p.get("citationCount"),
                    "arxivId": extract_arxiv_id(p),
                }
                for p in papers_result["data"]
            ]

    # Add to Neo4j if requested
    if add_to_graph:
        driver = get_driver()
        if driver:
            with driver.session() as session:
                session.run(
                    """
                    MERGE (a:Author {s2_id: $author_id})
                    SET a.name = $name,
                        a.affiliations = $affiliations,
                        a.homepage = $homepage,
                        a.paper_count = $paper_count,
                        a.citation_count = $citation_count,
                        a.h_index = $h_index,
                        a.updated_at = datetime()
                    """,
                    author_id=author.get("authorId"),
                    name=author.get("name"),
                    affiliations=author.get("affiliations") or [],
                    homepage=author.get("homepage"),
                    paper_count=author.get("paperCount"),
                    citation_count=author.get("citationCount"),
                    h_index=author.get("hIndex"),
                )
            result["added_to_graph"] = True

    return result


async def semantic_scholar_author_search(
    query: Annotated[str, Field(description="Author name to search")],
    limit: Annotated[int, Field(default=10, ge=1, le=100, description="Max results")] = 10,
) -> dict[str, Any]:
    """
    Search for authors by name on Semantic Scholar.

    Returns author IDs that can be used with semantic_scholar_author.
    """
    result = await search_authors(query=query, limit=limit)

    if not result:
        return {"error": "Search failed", "authors": []}
    if "error" in result:
        return result

    authors = []
    for author in result.get("data") or []:
        authors.append({
            "authorId": author.get("authorId"),
            "name": author.get("name"),
            "affiliations": author.get("affiliations") or [],
            "paperCount": author.get("paperCount"),
            "citationCount": author.get("citationCount"),
            "hIndex": author.get("hIndex"),
        })

    return {"authors": authors}


async def semantic_scholar_expand_citations(
    paper_id: Annotated[str, Field(description="Paper ID (S2 ID or 'ARXIV:...')")],
    direction: Annotated[str, Field(description="'references' (papers this cites) or 'citations' (papers citing this)")] = "references",
    limit: Annotated[int, Field(default=20, ge=1, le=100, description="Max papers to fetch")] = 20,
    add_to_graph: Annotated[bool, Field(default=True, description="Add papers and links to Neo4j")] = True,
) -> dict[str, Any]:
    """
    Expand the citation graph by fetching a paper's references or citations.

    Use direction='references' to get papers this paper cites.
    Use direction='citations' to get papers that cite this paper.
    """
    if direction == "references":
        result = await get_paper_references(paper_id, limit=limit)
    elif direction == "citations":
        result = await get_paper_citations(paper_id, limit=limit)
    else:
        return {"error": "direction must be 'references' or 'citations'"}

    if not result:
        return {"error": f"Paper not found: {paper_id}"}
    if "error" in result:
        return result

    papers = []
    for item in result.get("data") or []:
        # The structure is {citingPaper: {...}} or {citedPaper: {...}}
        paper = item.get("citingPaper") or item.get("citedPaper") or {}
        if paper.get("paperId"):
            papers.append({
                "paperId": paper.get("paperId"),
                "title": paper.get("title"),
                "year": paper.get("year"),
                "citationCount": paper.get("citationCount"),
                "arxivId": extract_arxiv_id(paper),
            })

    # Add to Neo4j
    if add_to_graph and papers:
        driver = get_driver()
        if driver:
            with driver.session() as session:
                for paper in papers:
                    # Create paper node
                    session.run(
                        """
                        MERGE (p:Paper {s2_id: $s2_id})
                        SET p.title = $title,
                            p.year = $year,
                            p.citation_count = $citation_count,
                            p.arxiv_id = $arxiv_id
                        """,
                        s2_id=paper["paperId"],
                        title=paper.get("title"),
                        year=paper.get("year"),
                        citation_count=paper.get("citationCount"),
                        arxiv_id=paper.get("arxivId"),
                    )

                    # Create citation relationship
                    if direction == "references":
                        # This paper cites the fetched paper
                        session.run(
                            """
                            MATCH (citing:Paper {s2_id: $citing_id})
                            MATCH (cited:Paper {s2_id: $cited_id})
                            MERGE (citing)-[:CITES]->(cited)
                            """,
                            citing_id=paper_id.replace("ARXIV:", "") if paper_id.startswith("ARXIV:") else paper_id,
                            cited_id=paper["paperId"],
                        )
                    else:
                        # Fetched paper cites this paper
                        session.run(
                            """
                            MATCH (citing:Paper {s2_id: $citing_id})
                            MATCH (cited:Paper {s2_id: $cited_id})
                            MERGE (citing)-[:CITES]->(cited)
                            """,
                            citing_id=paper["paperId"],
                            cited_id=paper_id.replace("ARXIV:", "") if paper_id.startswith("ARXIV:") else paper_id,
                        )

    return {
        "direction": direction,
        "count": len(papers),
        "papers": papers,
        "added_to_graph": add_to_graph,
    }


async def semantic_scholar_similar_papers(
    paper_id: Annotated[str, Field(description="Paper ID (S2 ID or 'ARXIV:...') to find similar papers for")],
    limit: Annotated[int, Field(default=10, ge=1, le=50, description="Max similar papers to return")] = 10,
    min_year: Annotated[int | None, Field(default=None, description="Only return papers from this year or later")] = None,
    add_to_graph: Annotated[bool, Field(default=False, description="Add similar papers to Neo4j")] = False,
) -> dict[str, Any]:
    """
    Find papers similar to a given paper using SPECTER2 embeddings.

    Requires the source paper to have an embedding stored in Neo4j.
    Uses cosine similarity via Neo4j's vector index for fast lookup.
    """
    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured"}

    # Normalize paper_id for lookup
    lookup_id = paper_id
    if paper_id.startswith("ARXIV:"):
        arxiv_id = paper_id.replace("ARXIV:", "")
        # Try to find by arxiv_id first
        with driver.session() as session:
            result = session.run(
                "MATCH (p:Paper {arxiv_id: $arxiv_id}) RETURN p.s2_id as s2_id",
                arxiv_id=arxiv_id,
            )
            record = result.single()
            if record and record["s2_id"]:
                lookup_id = record["s2_id"]

    with driver.session() as session:
        # Check if source paper has embedding
        result = session.run(
            """
            MATCH (p:Paper)
            WHERE p.s2_id = $paper_id OR p.arxiv_id = $paper_id
            RETURN p.s2_id as s2_id, p.title as title, p.embedding as embedding
            """,
            paper_id=lookup_id,
        )
        record = result.single()

        if not record:
            return {"error": f"Paper not found in graph: {paper_id}"}

        if not record["embedding"]:
            # Try to fetch embedding from Semantic Scholar
            return {
                "error": f"Paper '{record['title'][:50]}...' has no embedding. "
                "Re-add it with include_embedding=True: "
                f"semantic_scholar_paper('{paper_id}', include_embedding=True)"
            }

        source_paper = {
            "s2_id": record["s2_id"],
            "title": record["title"],
        }

        # Try vector index first (fast)
        try:
            query = """
                MATCH (source:Paper)
                WHERE source.s2_id = $paper_id OR source.arxiv_id = $paper_id
                CALL db.index.vector.queryNodes('paper_embedding', $limit + 1, source.embedding)
                YIELD node, score
                WHERE node <> source
            """
            if min_year:
                query += " AND node.year >= $min_year"
            query += """
                RETURN node.s2_id as s2_id,
                       node.arxiv_id as arxiv_id,
                       node.title as title,
                       node.year as year,
                       node.citation_count as citation_count,
                       node.tldr as tldr,
                       score as similarity
                ORDER BY similarity DESC
                LIMIT $limit
            """

            result = session.run(
                query,
                paper_id=lookup_id,
                limit=limit,
                min_year=min_year,
            )

            similar_papers = []
            for r in result:
                similar_papers.append({
                    "s2_id": r["s2_id"],
                    "arxiv_id": r["arxiv_id"],
                    "title": r["title"],
                    "year": r["year"],
                    "citationCount": r["citation_count"],
                    "tldr": r["tldr"],
                    "similarity": round(r["similarity"], 4),
                })

            method = "vector_index"

        except Exception as e:
            # Fallback: manual cosine similarity (slower)
            logger.warning("Vector index unavailable, using fallback: %s", e)

            query = """
                MATCH (source:Paper)
                WHERE source.s2_id = $paper_id OR source.arxiv_id = $paper_id
                MATCH (other:Paper)
                WHERE other <> source AND other.embedding IS NOT NULL
            """
            if min_year:
                query += " AND other.year >= $min_year"
            query += """
                WITH other,
                     gds.similarity.cosine(source.embedding, other.embedding) as similarity
                ORDER BY similarity DESC
                LIMIT $limit
                RETURN other.s2_id as s2_id,
                       other.arxiv_id as arxiv_id,
                       other.title as title,
                       other.year as year,
                       other.citation_count as citation_count,
                       other.tldr as tldr,
                       similarity
            """

            try:
                result = session.run(query, paper_id=lookup_id, limit=limit, min_year=min_year)
                similar_papers = []
                for r in result:
                    similar_papers.append({
                        "s2_id": r["s2_id"],
                        "arxiv_id": r["arxiv_id"],
                        "title": r["title"],
                        "year": r["year"],
                        "citationCount": r["citation_count"],
                        "tldr": r["tldr"],
                        "similarity": round(r["similarity"], 4),
                    })
                method = "gds_cosine"

            except Exception:
                # Last resort: pure Cypher cosine (very slow for large graphs)
                logger.warning("GDS unavailable, using pure Cypher cosine similarity")

                query = """
                    MATCH (source:Paper)
                    WHERE source.s2_id = $paper_id OR source.arxiv_id = $paper_id
                    MATCH (other:Paper)
                    WHERE other <> source AND other.embedding IS NOT NULL
                """
                if min_year:
                    query += " AND other.year >= $min_year"
                query += """
                    WITH other, source.embedding as e1, other.embedding as e2
                    WITH other,
                         reduce(dot = 0.0, i IN range(0, size(e1)-1) | dot + e1[i] * e2[i]) /
                         (sqrt(reduce(s = 0.0, x IN e1 | s + x*x)) * 
                          sqrt(reduce(s = 0.0, x IN e2 | s + x*x))) as similarity
                    ORDER BY similarity DESC
                    LIMIT $limit
                    RETURN other.s2_id as s2_id,
                           other.arxiv_id as arxiv_id,
                           other.title as title,
                           other.year as year,
                           other.citation_count as citation_count,
                           other.tldr as tldr,
                           similarity
                """

                result = session.run(query, paper_id=lookup_id, limit=limit, min_year=min_year)
                similar_papers = []
                for r in result:
                    similar_papers.append({
                        "s2_id": r["s2_id"],
                        "arxiv_id": r["arxiv_id"],
                        "title": r["title"],
                        "year": r["year"],
                        "citationCount": r["citation_count"],
                        "tldr": r["tldr"],
                        "similarity": round(r["similarity"], 4),
                    })
                method = "cypher_cosine"

    # Add to graph if requested (create SIMILAR_TO relationships)
    if add_to_graph and similar_papers:
        with driver.session() as session:
            for paper in similar_papers:
                session.run(
                    """
                    MATCH (source:Paper)
                    WHERE source.s2_id = $source_id OR source.arxiv_id = $source_id
                    MATCH (target:Paper {s2_id: $target_id})
                    MERGE (source)-[r:SIMILAR_TO]->(target)
                    SET r.similarity = $similarity,
                        r.computed_at = datetime()
                    """,
                    source_id=lookup_id,
                    target_id=paper["s2_id"],
                    similarity=paper["similarity"],
                )

    return {
        "source_paper": source_paper,
        "similar_papers": similar_papers,
        "count": len(similar_papers),
        "method": method,
        "added_to_graph": add_to_graph,
    }


async def semantic_scholar_add_embeddings(
    limit: Annotated[int, Field(default=50, ge=1, le=200, description="Max papers to process")] = 50,
    only_missing: Annotated[bool, Field(default=True, description="Only fetch for papers without embeddings")] = True,
) -> dict[str, Any]:
    """
    Batch-add SPECTER2 embeddings to papers in the graph.

    Fetches embeddings from Semantic Scholar for papers that don't have them.
    This enables similarity search via semantic_scholar_similar_papers.

    Note: Rate-limited to ~1 request/second, so processing 50 papers takes ~1 minute.
    """
    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured"}

    # Find papers needing embeddings
    with driver.session() as session:
        if only_missing:
            result = session.run(
                """
                MATCH (p:Paper)
                WHERE p.s2_id IS NOT NULL AND p.embedding IS NULL
                RETURN p.s2_id as s2_id, p.title as title
                LIMIT $limit
                """,
                limit=limit,
            )
        else:
            result = session.run(
                """
                MATCH (p:Paper)
                WHERE p.s2_id IS NOT NULL
                RETURN p.s2_id as s2_id, p.title as title
                LIMIT $limit
                """,
                limit=limit,
            )

        papers_to_process = [{"s2_id": r["s2_id"], "title": r["title"]} for r in result]

    if not papers_to_process:
        return {
            "message": "No papers need embeddings",
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
        }

    # Process in batches using the batch endpoint
    succeeded = 0
    failed = 0
    failed_papers = []

    # Semantic Scholar batch endpoint accepts up to 500 papers
    batch_size = 100  # Conservative to avoid timeouts
    paper_ids = [p["s2_id"] for p in papers_to_process]

    for i in range(0, len(paper_ids), batch_size):
        batch_ids = paper_ids[i : i + batch_size]

        # Fetch papers with embeddings
        papers_data = await get_paper_batch(batch_ids, include_embedding=True)

        if not papers_data:
            failed += len(batch_ids)
            failed_papers.extend(batch_ids)
            continue

        # Store embeddings
        with driver.session() as session:
            for paper in papers_data:
                if paper and paper.get("embedding"):
                    session.run(
                        """
                        MATCH (p:Paper {s2_id: $s2_id})
                        SET p.embedding = $embedding
                        """,
                        s2_id=paper["paperId"],
                        embedding=paper["embedding"].get("vector"),
                    )
                    succeeded += 1
                else:
                    failed += 1
                    if paper:
                        failed_papers.append(paper.get("paperId", "unknown"))

    return {
        "processed": len(papers_to_process),
        "succeeded": succeeded,
        "failed": failed,
        "failed_papers": failed_papers[:10],  # First 10 failures
        "message": f"Added embeddings to {succeeded} papers. Run semantic_scholar_similar_papers to find similar papers.",
    }


async def semantic_scholar_cluster_papers(
    topic: Annotated[str | None, Field(default=None, description="Filter by topic")] = None,
    min_papers: Annotated[int, Field(default=5, ge=2, description="Minimum papers for clustering")] = 5,
    num_clusters: Annotated[int, Field(default=5, ge=2, le=20, description="Number of clusters")] = 5,
) -> dict[str, Any]:
    """
    Cluster papers in the graph by embedding similarity.

    Groups papers into clusters based on their SPECTER2 embeddings.
    Useful for discovering research themes and related work.

    Requires papers to have embeddings (use semantic_scholar_add_embeddings first).
    """
    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured"}

    with driver.session() as session:
        # Get papers with embeddings
        query = """
            MATCH (p:Paper)
            WHERE p.embedding IS NOT NULL
        """
        if topic:
            query += " AND EXISTS((p)-[:ABOUT]->(:Topic {name: $topic}))"
        query += """
            RETURN p.s2_id as s2_id,
                   p.title as title,
                   p.year as year,
                   p.citation_count as citations,
                   p.embedding as embedding
        """

        result = session.run(query, topic=topic)
        papers = [
            {
                "s2_id": r["s2_id"],
                "title": r["title"],
                "year": r["year"],
                "citations": r["citations"],
                "embedding": r["embedding"],
            }
            for r in result
        ]

    if len(papers) < min_papers:
        return {
            "error": f"Not enough papers with embeddings ({len(papers)} found, need {min_papers}). "
            "Run semantic_scholar_add_embeddings first."
        }

    # Simple k-means clustering in Python (no external deps needed)
    import random

    embeddings = [p["embedding"] for p in papers]
    dim = len(embeddings[0])

    def cosine_distance(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = sum(x * x for x in a) ** 0.5
        norm_b = sum(x * x for x in b) ** 0.5
        if norm_a == 0 or norm_b == 0:
            return 1.0
        return 1.0 - (dot / (norm_a * norm_b))

    def mean_vector(vectors):
        if not vectors:
            return [0.0] * dim
        return [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]

    # Initialize centroids randomly
    k = min(num_clusters, len(papers))
    centroid_indices = random.sample(range(len(papers)), k)
    centroids = [embeddings[i][:] for i in centroid_indices]

    # K-means iterations
    max_iterations = 20
    for _ in range(max_iterations):
        # Assign papers to nearest centroid
        assignments = []
        for emb in embeddings:
            distances = [cosine_distance(emb, c) for c in centroids]
            assignments.append(distances.index(min(distances)))

        # Update centroids
        new_centroids = []
        for cluster_id in range(k):
            cluster_embeddings = [
                embeddings[i] for i, a in enumerate(assignments) if a == cluster_id
            ]
            if cluster_embeddings:
                new_centroids.append(mean_vector(cluster_embeddings))
            else:
                new_centroids.append(centroids[cluster_id])

        # Check convergence
        if new_centroids == centroids:
            break
        centroids = new_centroids

    # Build cluster results
    clusters = {i: [] for i in range(k)}
    for idx, cluster_id in enumerate(assignments):
        paper = papers[idx]
        clusters[cluster_id].append({
            "s2_id": paper["s2_id"],
            "title": paper["title"],
            "year": paper["year"],
            "citations": paper["citations"],
        })

    # Sort clusters by size and papers by citations
    cluster_list = []
    for cluster_id, cluster_papers in clusters.items():
        if cluster_papers:
            sorted_papers = sorted(
                cluster_papers, key=lambda x: x["citations"] or 0, reverse=True
            )
            cluster_list.append({
                "cluster_id": cluster_id,
                "size": len(sorted_papers),
                "top_papers": sorted_papers[:5],
                "representative_title": sorted_papers[0]["title"],
            })

    cluster_list.sort(key=lambda x: x["size"], reverse=True)

    # Store cluster assignments in graph
    with driver.session() as session:
        for cluster in cluster_list:
            for paper in cluster["top_papers"]:
                session.run(
                    """
                    MATCH (p:Paper {s2_id: $s2_id})
                    SET p.cluster_id = $cluster_id
                    """,
                    s2_id=paper["s2_id"],
                    cluster_id=cluster["cluster_id"],
                )

    return {
        "total_papers": len(papers),
        "num_clusters": len(cluster_list),
        "clusters": cluster_list,
        "topic_filter": topic,
    }

def register(mcp):
    """Register Semantic Scholar tools with the FastMCP instance."""
    mcp.tool()(semantic_scholar_paper)
    mcp.tool()(semantic_scholar_search)
    mcp.tool()(semantic_scholar_author)
    mcp.tool()(semantic_scholar_author_search)
    mcp.tool()(semantic_scholar_expand_citations)
    mcp.tool()(semantic_scholar_similar_papers)
    mcp.tool()(semantic_scholar_add_embeddings)
    mcp.tool()(semantic_scholar_cluster_papers)