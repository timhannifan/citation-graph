"""Graph tools: link papers and execute Cypher queries."""

import logging
from typing import Annotated, Any

from neo4j_driver import execute_cypher_query, get_driver
from pydantic import Field

logger = logging.getLogger(__name__)


async def link_papers(
    citing_arxiv_id: Annotated[str, Field(description="arXiv ID of the paper that cites")],
    cited_arxiv_id: Annotated[str, Field(description="arXiv ID of the paper being cited")],
) -> str:
    """Manually add a citation relationship between two papers already in the graph."""
    driver = get_driver()
    if driver is None:
        return "Neo4j not configured."

    with driver.session() as session:
        result = session.run(
            """
            MATCH (citing:Paper {arxiv_id: $citing_id})
            MATCH (cited:Paper {arxiv_id: $cited_id})
            MERGE (citing)-[r:CITES]->(cited)
            RETURN citing.title as from_title, cited.title as to_title
        """,
            citing_id=citing_arxiv_id,
            cited_id=cited_arxiv_id,
        )

        record = result.single()
        if not record:
            return "One or both papers not found in graph. Add them first with arxiv_add_paper."

        session.run("""
            MATCH (p:Paper)<-[c:CITES]-()
            WITH p, count(c) as cnt
            SET p.citations = cnt
        """)

        return f"Linked: '{record['from_title'][:40]}...' → '{record['to_title'][:40]}...'"


def _normalize_paper_id(paper_id: str) -> str:
    """Strip ARXIV: prefix for lookup."""
    if paper_id.startswith("ARXIV:"):
        return paper_id.replace("ARXIV:", "")
    return paper_id


async def graph_get_paper(
    paper_id: Annotated[str, Field(description="Paper ID: S2 ID, arXiv ID, or DOI. Use first to avoid API for papers already in Neo4j.")],
) -> dict[str, Any]:
    """Look up a paper in the graph by s2_id, arxiv_id, or doi (read-only). Returns paper data if found, or error dict. No API call."""
    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured."}

    pid = _normalize_paper_id(paper_id)
    with driver.session() as session:
        result = session.run(
            """
            MATCH (p:Paper)
            WHERE p.s2_id = $paper_id OR p.arxiv_id = $paper_id OR p.doi = $paper_id
            RETURN p.s2_id as s2_id,
                   p.arxiv_id as arxiv_id,
                   p.doi as doi,
                   p.title as title,
                   p.year as year,
                   p.abstract as abstract,
                   p.citation_count as citation_count,
                   p.influential_citation_count as influential_citation_count,
                   p.tldr as tldr,
                   p.open_access_url as open_access_url,
                   p.fields_of_study as fields_of_study
            """,
            paper_id=pid,
        )
        record = result.single()
    if not record:
        return {"error": "Paper not in graph"}
    return {
        "s2_id": record["s2_id"],
        "arxiv_id": record["arxiv_id"],
        "doi": record["doi"],
        "title": record["title"],
        "year": record["year"],
        "abstract": record["abstract"],
        "citation_count": record["citation_count"],
        "influential_citation_count": record["influential_citation_count"],
        "tldr": record["tldr"],
        "open_access_url": record["open_access_url"],
        "fields_of_study": record["fields_of_study"] or [],
    }


async def graph_add_paper(
    s2_id: Annotated[str, Field(description="Semantic Scholar paper ID")],
    title: Annotated[str, Field(description="Paper title")],
    year: Annotated[int | None, Field(default=None, description="Publication year")] = None,
    abstract: Annotated[str | None, Field(default=None, description="Abstract")] = None,
    arxiv_id: Annotated[str | None, Field(default=None, description="arXiv ID")] = None,
    doi: Annotated[str | None, Field(default=None, description="DOI")] = None,
    citation_count: Annotated[int | None, Field(default=None, description="Citation count")] = None,
    influential_citation_count: Annotated[int | None, Field(default=None, description="Influential citation count")] = None,
    tldr: Annotated[str | None, Field(default=None, description="TLDR summary")] = None,
    open_access_url: Annotated[str | None, Field(default=None, description="Open access PDF URL")] = None,
    fields_of_study: Annotated[list[str] | None, Field(default=None, description="Fields of study")] = None,
    authors: Annotated[list[dict[str, Any]] | None, Field(default=None, description="List of {authorId, name}")] = None,
    embedding: Annotated[list[float] | None, Field(default=None, description="SPECTER2 embedding vector")] = None,
) -> str:
    """Add or update a paper node and related authors/topics (DB only). Use payload from semantic_scholar_get_paper when paper is not in graph. Map paperId->s2_id, citationCount->citation_count, influentialCitationCount->influential_citation_count, openAccessPdf->open_access_url."""
    driver = get_driver()
    if driver is None:
        return "Neo4j not configured."

    with driver.session() as session:
        session.run(
            """
            MERGE (p:Paper {s2_id: $s2_id})
            SET p.title = $title,
                p.year = $year,
                p.abstract = $abstract,
                p.arxiv_id = $arxiv_id,
                p.doi = $doi,
                p.citation_count = $citation_count,
                p.influential_citation_count = $influential_citation_count,
                p.tldr = $tldr,
                p.open_access_url = $open_access_url,
                p.fields_of_study = $fields_of_study,
                p.updated_at = datetime()
            """,
            s2_id=s2_id,
            title=title,
            year=year,
            abstract=abstract,
            arxiv_id=arxiv_id,
            doi=doi,
            citation_count=citation_count,
            influential_citation_count=influential_citation_count,
            tldr=tldr,
            open_access_url=open_access_url,
            fields_of_study=fields_of_study or [],
        )
        for author in authors or []:
            aid = author.get("authorId")
            name = author.get("name")
            if aid:
                session.run(
                    """
                    MERGE (a:Author {s2_id: $author_id})
                    SET a.name = $name
                    WITH a
                    MATCH (p:Paper {s2_id: $paper_id})
                    MERGE (a)-[:AUTHORED]->(p)
                    """,
                    author_id=aid,
                    name=name,
                    paper_id=s2_id,
                )
        for field in fields_of_study or []:
            session.run(
                """
                MERGE (t:Topic {name: $name})
                WITH t
                MATCH (p:Paper {s2_id: $paper_id})
                MERGE (p)-[:ABOUT]->(t)
                """,
                name=field,
                paper_id=s2_id,
            )
        if embedding is not None:
            session.run(
                """
                MATCH (p:Paper {s2_id: $paper_id})
                SET p.embedding = $embedding
                """,
                paper_id=s2_id,
                embedding=embedding,
            )
    return f"Added/updated paper {title[:60]}... ({s2_id})." if len(title) > 60 else f"Added/updated paper {title} ({s2_id})."


async def graph_get_author(
    author_id: Annotated[str, Field(description="Semantic Scholar author ID (s2_id). Use first to avoid calling API for authors already in Neo4j.")],
) -> dict[str, Any]:
    """Look up an author in the graph by s2_id (read-only). Returns author data if found, or error dict. No API call."""
    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured."}

    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Author {s2_id: $author_id})
            RETURN a.s2_id as authorId,
                   a.name as name,
                   a.affiliations as affiliations,
                   a.homepage as homepage,
                   a.paper_count as paper_count,
                   a.citation_count as citation_count,
                   a.h_index as h_index
            """,
            author_id=author_id,
        )
        record = result.single()
    if not record:
        return {"error": "Author not in graph"}
    return {
        "authorId": record["authorId"],
        "name": record["name"],
        "affiliations": record["affiliations"] or [],
        "homepage": record["homepage"],
        "paper_count": record["paper_count"],
        "citation_count": record["citation_count"],
        "h_index": record["h_index"],
    }


async def graph_add_author(
    author_id: Annotated[str, Field(description="Semantic Scholar author ID (s2_id)")],
    name: Annotated[str, Field(description="Author display name")],
    affiliations: Annotated[list[str] | None, Field(default=None, description="Affiliation strings")] = None,
    homepage: Annotated[str | None, Field(default=None, description="Author homepage URL")] = None,
    paper_count: Annotated[int | None, Field(default=None, description="Paper count")] = None,
    citation_count: Annotated[int | None, Field(default=None, description="Citation count")] = None,
    h_index: Annotated[int | None, Field(default=None, description="h-index")] = None,
) -> str:
    """Add or update an author node in the graph (DB only). Use payload from semantic_scholar_get_author when author is not in graph."""
    driver = get_driver()
    if driver is None:
        return "Neo4j not configured."

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
            author_id=author_id,
            name=name,
            affiliations=affiliations or [],
            homepage=homepage,
            paper_count=paper_count,
            citation_count=citation_count,
            h_index=h_index,
        )
    return f"Added/updated author {name} ({author_id})."


async def neo4j_execute_cypher(
    query: Annotated[
        str,
        Field(
            description="The Cypher query to execute. Use ONLY to query data already in the Neo4j graph (papers/authors/topics already added). Do NOT use for searching the web or finding papers by topic—use arxiv_search for that. Do NOT use for adding a paper by arXiv ID—use arxiv_add_paper for that. Must be a read-only query (MATCH, RETURN, etc.). Dangerous operations (DELETE, DROP, CREATE, MERGE, SET) are blocked for safety."
        ),
    ],
    params: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description="Optional dictionary of query parameters. Keys should match parameter names in the query (e.g., {'name': 'Alice Chen'}).",
        ),
    ] = None,
) -> str:
    """Execute a custom Cypher query against the Neo4j citation graph. Use this when the user asks for custom queries, ad-hoc analysis, or queries that aren't covered by other tools. Generate the Cypher query based on the user's natural language request, then call this tool with the generated query. The query must be read-only (MATCH, RETURN, etc.) - write operations are blocked for safety. Returns formatted query results or an error message."""
    try:
        driver = get_driver()
        if driver is None:
            error_msg = (
                "Neo4j not configured. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD. "
                "Run the citation graph seed/demo script first: scripts/neo4j_citation_demo.py"
            )
            logger.error("Neo4j driver not available")
            return error_msg
        return execute_cypher_query(driver, query, params)
    except Exception as e:
        logger.exception("neo4j_execute_cypher failed")
        return f"Unexpected error in neo4j_execute_cypher: {e}"


def register(mcp):
    """Register graph tools with the FastMCP instance."""
    mcp.tool()(link_papers)
    mcp.tool()(graph_get_paper)
    mcp.tool()(graph_add_paper)
    mcp.tool()(graph_get_author)
    mcp.tool()(graph_add_author)
    mcp.tool()(neo4j_execute_cypher)
