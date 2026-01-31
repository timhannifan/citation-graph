"""MCP server for OpenWebUI with Neo4j knowledge-graph demo tools."""

import datetime
import logging
import os
import re
import sys
import urllib.parse
from typing import Annotated, Any

import defusedxml.ElementTree as ET
import httpx
import uvicorn
from arxiv_tools import fetch_arxiv_metadata, fetch_citations_semantic_scholar
from fastmcp import FastMCP
from neo4j_demo import execute_cypher_query, get_driver
from pydantic import Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stderr,
    force=True,  # Force reconfiguration if already configured
)
logger = logging.getLogger(__name__)
# Ensure logs are flushed immediately
sys.stderr.flush()

# Create FastMCP instance
mcp = FastMCP("openwebui-tools")


# Internal tool for write operations
def _execute_write(driver, cypher: str, **params) -> str:
    """Execute a write query (internal use only)."""
    with driver.session() as session:
        result = session.run(cypher, params)
        summary = result.consume()
        return f"Created {summary.counters.nodes_created} nodes, {summary.counters.relationships_created} relationships"


@mcp.tool()
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
        resp = await client.get(f"https://export.arxiv.org/api/query?{params}", timeout=30)
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


@mcp.tool()
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

    # Normalize ID
    arxiv_id = arxiv_id.strip()
    arxiv_id = re.sub(r"^https?://arxiv\.org/abs/", "", arxiv_id)
    arxiv_id = re.sub(r"v\d+$", "", arxiv_id)

    # Fetch metadata
    meta = await fetch_arxiv_metadata(arxiv_id)
    if not meta or not meta.get("title"):
        return f"Could not fetch paper {arxiv_id} from arXiv."

    # Create the main paper
    with driver.session() as session:
        # MERGE paper node
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

        # MERGE authors and relationships
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

        # MERGE topics from categories
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

    # Fetch and add citations if requested
    if include_references or include_citations:
        citation_data = await fetch_citations_semantic_scholar(arxiv_id)

        if include_references and citation_data["references"]:
            ref_ids = [r["arxiv_id"] for r in citation_data["references"][:10]]
            with driver.session() as session:
                for ref in citation_data["references"][:10]:
                    # Create stub paper for reference (can be enriched later)
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

    # Update citation counts
    with driver.session() as session:
        session.run("""
            MATCH (p:Paper)<-[c:CITES]-()
            WITH p, count(c) as cnt
            SET p.citations = cnt
        """)

    return "\n".join(result_parts)


@mcp.tool()
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

        # Update citation count
        session.run("""
            MATCH (p:Paper)<-[c:CITES]-()
            WITH p, count(c) as cnt
            SET p.citations = cnt
        """)

        return f"Linked: '{record['from_title'][:40]}...' → '{record['to_title'][:40]}...'"


# Register tools
@mcp.tool()
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
    """Execute a custom Cypher query against the Neo4j citation demo graph. Use this when the user asks for custom queries, ad-hoc analysis, or queries that aren't covered by other tools. Generate the Cypher query based on the user's natural language request, then call this tool with the generated query. The query must be read-only (MATCH, RETURN, etc.) - write operations are blocked for safety. Returns formatted query results or an error message."""
    try:
        driver = get_driver()
        if driver is None:
            error_msg = (
                "Neo4j not configured. Set NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD. "
                "Run the citation demo seed script first: scripts/neo4j_citation_demo.py"
            )
            logger.error("Neo4j driver not available")
            return error_msg
        return execute_cypher_query(driver, query, params)
    except Exception as e:
        logger.exception("neo4j_execute_cypher failed")
        return f"Unexpected error in neo4j_execute_cypher: {e}"


@mcp.tool()
def compute_paper_influence(
    arxiv_id: str,
    metrics: list[str] | None = None,
    _time_window: str = "all",
    normalize_by_age: bool = True,
    store_in_graph: bool = True,
) -> dict[str, Any]:
    """
    Compute influence metrics for a paper in the citation graph.

    Args:
        arxiv_id: ArXiv ID of the paper (e.g., "1609.02907")
        metrics: List of metrics to compute. Options:
                 ["citations", "pagerank", "betweenness", "h_index",
                  "citation_velocity", "second_order_citations"]
                 Default: all metrics
        time_window: Time window for analysis ("all", "1y", "3y", "5y")
        normalize_by_age: Whether to normalize scores by paper age
        store_in_graph: Whether to store computed metrics in Neo4j

    Returns:
        Dictionary containing influence scores, rankings, and trends
    """
    if metrics is None:
        metrics = [
            "citations",
            "pagerank",
            "betweenness",
            "citation_velocity",
            "second_order_citations",
        ]

    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured."}

    with driver.session() as session:
        # Get paper info and citation data
        result = session.run(
            """
            MATCH (p:Paper {arxiv_id: $arxiv_id})
            OPTIONAL MATCH (p)<-[:CITES]-(citing:Paper)
            OPTIONAL MATCH (p)-[:CITES]->(cited:Paper)
            OPTIONAL MATCH (citing)<-[:CITES]-(second_order:Paper)
            WITH p, 
                 collect(DISTINCT citing) as citing_papers,
                 collect(DISTINCT cited) as cited_papers,
                 collect(DISTINCT second_order) as second_order_papers
            RETURN p.title as title,
                   p.arxiv_id as arxiv_id,
                   p.year as year,
                   citing_papers,
                   cited_papers,
                   second_order_papers
        """,
            arxiv_id=arxiv_id,
        )

        record = result.single()
        if not record:
            return {"error": f"Paper {arxiv_id} not found in database"}

        paper_data = {
            "title": record["title"],
            "arxiv_id": record["arxiv_id"],
            "year": record["year"],
        }

        citing_papers = record["citing_papers"]
        _ = record["cited_papers"]
        second_order_papers = record["second_order_papers"]

        # Calculate paper age
        current_year = datetime.datetime.now().year
        paper_age = current_year - (paper_data["year"] or current_year)
        paper_age = max(1, paper_age)  # Avoid division by zero

        # Initialize scores
        influence_scores = {}

        # Metric 1: Total Citations
        if "citations" in metrics:
            total_citations = len(citing_papers)
            influence_scores["total_citations"] = total_citations

        # Metric 2: Citation Velocity
        if "citation_velocity" in metrics:
            velocity = len(citing_papers) / paper_age if paper_age > 0 else 0
            influence_scores["citation_velocity"] = round(velocity, 2)

        # Metric 3: Second-order Citations
        if "second_order_citations" in metrics:
            influence_scores["second_order_citations"] = len(second_order_papers)

        # Metric 4: PageRank
        if "pagerank" in metrics:
            pagerank = compute_pagerank(session, arxiv_id)
            influence_scores["pagerank"] = round(pagerank, 6)

        # Metric 5: Betweenness Centrality
        if "betweenness" in metrics:
            betweenness = compute_betweenness(session, arxiv_id)
            influence_scores["betweenness"] = round(betweenness, 6)

        # Metric 6: H-index Contribution
        if "h_index" in metrics:
            h_contribution = compute_h_index_contribution(session, arxiv_id)
            influence_scores["h_index_contribution"] = h_contribution

        # Normalize by age if requested
        if normalize_by_age and paper_age > 0:
            normalized_score = (
                influence_scores.get("total_citations", 0) / paper_age
                + influence_scores.get("pagerank", 0) * 1000
            )
            influence_scores["age_normalized_score"] = round(normalized_score, 2)

        # Compute rankings
        rankings = compute_rankings(session, arxiv_id, influence_scores)

        # Compute trends
        trends = compute_trends(session, arxiv_id, citing_papers, paper_data["year"])

        # Store in graph if requested
        if store_in_graph:
            store_influence_metrics(session, arxiv_id, influence_scores, rankings)

        return {
            "paper": paper_data,
            "influence_scores": influence_scores,
            "rankings": rankings,
            "trends": trends,
            "metadata": {
                "paper_age": paper_age,
                "computed_at": datetime.datetime.now().isoformat(),
                "metrics_computed": metrics,
            },
        }


def compute_pagerank(_session, arxiv_id: str) -> float:
    """Compute PageRank for a paper using Neo4j GDS."""
    driver = get_driver()
    if driver is None:
        return 0.0
    with driver.session() as neo4j_session:
        try:
            # Try using Neo4j GDS if available
            result = neo4j_session.run(
                """
                CALL gds.pageRank.stream('citations-graph')
                YIELD nodeId, score
                WITH gds.util.asNode(nodeId) AS node, score
                WHERE node.arxiv_id = $arxiv_id
                RETURN score
            """,
                arxiv_id=arxiv_id,
            )

            record = result.single()
            return record["score"] if record else 0.0
        except Exception:  # noqa: BLE001 - intentional fallback when GDS unavailable
            # Fallback: Simple PageRank approximation
            result = neo4j_session.run(
                """
                MATCH (p:Paper {arxiv_id: $arxiv_id})<-[:CITES]-(citing)
                OPTIONAL MATCH (citing)<-[:CITES]-(second)
                WITH p, count(DISTINCT citing) as direct, count(DISTINCT second) as indirect
                RETURN (direct + indirect * 0.5) as approx_pagerank
            """,
                arxiv_id=arxiv_id,
            )

            record = result.single()
            # Normalize to 0-1 range (approximation)
            return (record["approx_pagerank"] or 0) / 10000.0


def compute_betweenness(session, arxiv_id: str) -> float:
    """Compute betweenness centrality for a paper."""
    try:
        # Try GDS if available
        result = session.run(
            """
            CALL gds.betweenness.stream('citations-graph')
            YIELD nodeId, score
            WITH gds.util.asNode(nodeId) AS node, score
            WHERE node.arxiv_id = $arxiv_id
            RETURN score
        """,
            arxiv_id=arxiv_id,
        )

        record = result.single()
        return record["score"] if record else 0.0
    except Exception:  # noqa: BLE001 - intentional fallback when GDS unavailable
        # Simple approximation: papers that cite this and are cited by others
        result = session.run(
            """
            MATCH (p:Paper {arxiv_id: $arxiv_id})
            MATCH (p)<-[:CITES]-(citing)-[:CITES]->(other)
            WHERE other <> p
            RETURN count(DISTINCT citing) as bridge_count
        """,
            arxiv_id=arxiv_id,
        )

        record = result.single()
        return (record["bridge_count"] or 0) / 1000.0


def compute_h_index_contribution(session, arxiv_id: str) -> int:
    """Compute how this paper contributes to authors' h-index."""
    result = session.run(
        """
        MATCH (p:Paper {arxiv_id: $arxiv_id})<-[:AUTHORED]-(author:Author)
        MATCH (author)-[:AUTHORED]->(other_paper:Paper)
        OPTIONAL MATCH (other_paper)<-[:CITES]-(citing)
        WITH author, other_paper, count(citing) as citations
        WHERE citations >= 1
        WITH author, collect(citations) as citation_counts
        RETURN avg([c in citation_counts WHERE c >= size(citation_counts)]) as h_contribution
    """,
        arxiv_id=arxiv_id,
    )

    record = result.single()
    return int(record["h_contribution"] or 0)


def compute_rankings(session, arxiv_id: str, _influence_scores: dict) -> dict[str, int]:
    """Compute rankings compared to other papers."""
    # Overall rank by PageRank
    result = session.run("""
        MATCH (p:Paper)
        WHERE p.pagerank_score IS NOT NULL
        WITH p ORDER BY p.pagerank_score DESC
        WITH collect(p.arxiv_id) as ranked_papers
        RETURN ranked_papers
    """)

    record = result.single()
    ranked_papers = record["ranked_papers"] if record else []

    overall_rank = ranked_papers.index(arxiv_id) + 1 if arxiv_id in ranked_papers else None

    # Year cohort rank
    result = session.run(
        """
        MATCH (p:Paper {arxiv_id: $arxiv_id})
        MATCH (cohort:Paper)
        WHERE cohort.year = p.year AND cohort.pagerank_score IS NOT NULL
        WITH cohort ORDER BY cohort.pagerank_score DESC
        WITH collect(cohort.arxiv_id) as ranked_cohort
        RETURN ranked_cohort
    """,
        arxiv_id=arxiv_id,
    )

    record = result.single()
    ranked_cohort = record["ranked_cohort"] if record else []
    cohort_rank = ranked_cohort.index(arxiv_id) + 1 if arxiv_id in ranked_cohort else None

    return {
        "overall_rank": overall_rank,
        "year_cohort_rank": cohort_rank,
        "total_papers_in_db": len(ranked_papers),
    }


MIN_YEARS_FOR_TREND = 2
EMERGING_PAPER_AGE_YEARS = 3
MIN_CITATIONS_FOR_EMERGING = 10


def compute_trends(session, arxiv_id: str, citing_papers: list, paper_year: int) -> dict:
    """Analyze citation trends over time."""
    if not paper_year or not citing_papers:
        return {"trend": "insufficient_data"}

    # Get citation distribution by year
    result = session.run(
        """
        MATCH (p:Paper {arxiv_id: $arxiv_id})<-[:CITES]-(citing:Paper)
        WHERE citing.year IS NOT NULL
        RETURN citing.year as year, count(*) as citations
        ORDER BY year
    """,
        arxiv_id=arxiv_id,
    )

    citations_by_year = {record["year"]: record["citations"] for record in result}

    if not citations_by_year:
        return {"trend": "no_temporal_data"}

    # Find peak year
    peak_year = max(citations_by_year, key=citations_by_year.get)

    # Determine trend
    recent_years = sorted(citations_by_year.keys())[-3:]
    if len(recent_years) >= MIN_YEARS_FOR_TREND:
        recent_trend = (
            "growing"
            if citations_by_year[recent_years[-1]] > citations_by_year[recent_years[0]]
            else "declining"
        )
    else:
        recent_trend = "stable"

    # Emerging vs established
    current_year = datetime.datetime.now().year
    paper_age = current_year - paper_year
    status = (
        "emerging"
        if paper_age <= EMERGING_PAPER_AGE_YEARS and len(citing_papers) > MIN_CITATIONS_FOR_EMERGING
        else "established"
    )

    return {
        "peak_citation_year": peak_year,
        "peak_citations": citations_by_year[peak_year],
        "growth_trend": recent_trend,
        "emerging_vs_established": status,
        "citations_by_year": citations_by_year,
    }


def store_influence_metrics(session, arxiv_id: str, scores: dict, rankings: dict):
    """Store computed metrics back to the graph."""
    session.run(
        """
        MATCH (p:Paper {arxiv_id: $arxiv_id})
        SET p.pagerank_score = $pagerank,
            p.citation_count = $citations,
            p.citation_velocity = $velocity,
            p.influence_rank = $rank,
            p.betweenness_score = $betweenness,
            p.last_influence_update = datetime()
    """,
        arxiv_id=arxiv_id,
        pagerank=scores.get("pagerank", 0),
        citations=scores.get("total_citations", 0),
        velocity=scores.get("citation_velocity", 0),
        rank=rankings.get("overall_rank"),
        betweenness=scores.get("betweenness", 0),
    )


@mcp.tool()
def compare_paper_influence(
    arxiv_ids: list[str],
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """
    Compare influence metrics across multiple papers.

    Args:
        arxiv_ids: List of arXiv IDs to compare
        metrics: Metrics to compare (default: all)

    Returns:
        Comparison table and rankings
    """
    if metrics is None:
        metrics = ["citations", "pagerank", "citation_velocity"]

    comparisons = {}
    for arxiv_id in arxiv_ids:
        result = compute_paper_influence(arxiv_id=arxiv_id, metrics=metrics, store_in_graph=False)
        comparisons[arxiv_id] = result

    # Create comparison table
    comparison_table = []
    for arxiv_id, data in comparisons.items():
        if "error" not in data:
            row = {
                "arxiv_id": arxiv_id,
                "title": data["paper"]["title"][:50] + "...",
                **data["influence_scores"],
            }
            comparison_table.append(row)

    # Rank papers by each metric
    rankings_by_metric = {}
    for metric in metrics:
        sorted_papers = sorted(comparison_table, key=lambda x: x.get(metric, 0), reverse=True)
        rankings_by_metric[metric] = [p["arxiv_id"] for p in sorted_papers]

    return {
        "comparisons": comparison_table,
        "rankings_by_metric": rankings_by_metric,
        "winner_by_metric": {
            metric: rankings[0] for metric, rankings in rankings_by_metric.items()
        },
    }


@mcp.tool()
def find_most_influential_papers(
    topic: str | None = None, min_year: int | None = None, limit: int = 10, metric: str = "pagerank"
) -> list[dict[str, Any]]:
    """
    Find the most influential papers in the database.

    Args:
        topic: Filter by topic (optional)
        min_year: Minimum publication year (optional)
        limit: Number of papers to return
        metric: Metric to rank by ("pagerank", "citations", "betweenness")

    Returns:
        List of most influential papers with their scores
    """
    driver = get_driver()
    if driver is None:
        return {"error": "Neo4j not configured."}

    with driver.session() as session:
        query = """
            MATCH (p:Paper)
            WHERE 1=1
        """

        params = {"limit": limit}

        if topic:
            query += """
                AND EXISTS((p)-[:ABOUT]->(:Topic {name: $topic}))
            """
            params["topic"] = topic

        if min_year:
            query += """
                AND p.year >= $min_year
            """
            params["min_year"] = min_year

        query += """
            RETURN p.arxiv_id as arxiv_id,
                   p.title as title,
                   p.year as year,
                   p.pagerank_score as pagerank,
                   p.citation_count as citations,
                   p.betweenness_score as betweenness
            ORDER BY p.{} DESC
            LIMIT $limit
        """.format(metric + "_score" if metric != "citations" else "citation_count")

        result = session.run(query, **params)

        papers = []
        for record in result:
            papers.append(
                {
                    "arxiv_id": record["arxiv_id"],
                    "title": record["title"],
                    "year": record["year"],
                    "influence_scores": {
                        "pagerank": record["pagerank"],
                        "citations": record["citations"],
                        "betweenness": record["betweenness"],
                    },
                }
            )

        return papers


if __name__ == "__main__":
    host = os.getenv("MCP_SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_SERVER_PORT", "8090"))

    logger.info("Starting MCP server on %s:%s", host, port)
    logger.info("Registered tools: neo4j_execute_cypher")

    app = mcp.http_app(path="/mcp")
    logger.info("MCP endpoint available at http://%s:%s/mcp", host, port)

    uvicorn.run(app, host=host, port=port, log_level="info")
