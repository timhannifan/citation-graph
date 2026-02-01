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
    mcp.tool()(graph_get_author)
    mcp.tool()(graph_add_author)
    mcp.tool()(neo4j_execute_cypher)
