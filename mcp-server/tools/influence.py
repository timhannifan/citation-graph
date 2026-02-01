"""Influence tools: compute and compare paper influence metrics."""

import datetime
from typing import Any

from neo4j_driver import get_driver

MIN_YEARS_FOR_TREND = 2
EMERGING_PAPER_AGE_YEARS = 3
MIN_CITATIONS_FOR_EMERGING = 10


def compute_pagerank(_session, paper_id: str) -> float:
    """Compute PageRank for a paper using Neo4j GDS."""
    driver = get_driver()
    if driver is None:
        return 0.0
    with driver.session() as neo4j_session:
        try:
            result = neo4j_session.run(
                """
                CALL gds.pageRank.stream('citations-graph')
                YIELD nodeId, score
                WITH gds.util.asNode(nodeId) AS node, score
                WHERE node.arxiv_id = $paper_id OR node.s2_id = $paper_id
                RETURN score
            """,
                paper_id=paper_id,
            )
            record = result.single()
            return record["score"] if record else 0.0
        except Exception:  # noqa: BLE001 - intentional fallback when GDS unavailable
            result = neo4j_session.run(
                """
                MATCH (p:Paper)
                WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
                MATCH (p)<-[:CITES]-(citing)
                OPTIONAL MATCH (citing)<-[:CITES]-(second)
                WITH p, count(DISTINCT citing) as direct, count(DISTINCT second) as indirect
                RETURN (direct + indirect * 0.5) as approx_pagerank
            """,
                paper_id=paper_id,
            )
            record = result.single()
            return (record["approx_pagerank"] or 0) / 10000.0


def compute_betweenness(session, paper_id: str) -> float:
    """Compute betweenness centrality for a paper."""
    try:
        result = session.run(
            """
            CALL gds.betweenness.stream('citations-graph')
            YIELD nodeId, score
            WITH gds.util.asNode(nodeId) AS node, score
            WHERE node.arxiv_id = $paper_id OR node.s2_id = $paper_id
            RETURN score
        """,
            paper_id=paper_id,
        )
        record = result.single()
        return record["score"] if record else 0.0
    except Exception:  # noqa: BLE001 - intentional fallback when GDS unavailable
        result = session.run(
            """
            MATCH (p:Paper)
            WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
            MATCH (p)<-[:CITES]-(citing)-[:CITES]->(other)
            WHERE other <> p
            RETURN count(DISTINCT citing) as bridge_count
        """,
            paper_id=paper_id,
        )
        record = result.single()
        return (record["bridge_count"] or 0) / 1000.0


def compute_h_index_contribution(session, paper_id: str) -> int:
    """Compute how this paper contributes to authors' h-index."""
    result = session.run(
        """
        MATCH (p:Paper)
        WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
        MATCH (p)<-[:AUTHORED]-(author:Author)
        MATCH (author)-[:AUTHORED]->(other_paper:Paper)
        OPTIONAL MATCH (other_paper)<-[:CITES]-(citing)
        WITH author, other_paper, count(citing) as citations
        WHERE citations >= 1
        WITH author, collect(citations) as citation_counts
        RETURN avg([c in citation_counts WHERE c >= size(citation_counts)]) as h_contribution
    """,
        paper_id=paper_id,
    )
    record = result.single()
    return int(record["h_contribution"] or 0)


def compute_rankings(session, paper_id: str, _influence_scores: dict) -> dict[str, int]:
    """Compute rankings compared to other papers."""
    result = session.run("""
        MATCH (p:Paper)
        WHERE p.pagerank_score IS NOT NULL
        WITH p ORDER BY p.pagerank_score DESC
        WITH collect(coalesce(p.arxiv_id, p.s2_id)) as ranked_papers
        RETURN ranked_papers
    """)
    record = result.single()
    ranked_papers = record["ranked_papers"] if record else []
    current_canonical = _get_canonical_id(session, paper_id)
    overall_rank = ranked_papers.index(current_canonical) + 1 if current_canonical and current_canonical in ranked_papers else None

    result = session.run(
        """
        MATCH (p:Paper)
        WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
        MATCH (cohort:Paper)
        WHERE cohort.year = p.year AND cohort.pagerank_score IS NOT NULL
        WITH cohort ORDER BY cohort.pagerank_score DESC
        WITH collect(coalesce(cohort.arxiv_id, cohort.s2_id)) as ranked_cohort
        RETURN ranked_cohort
    """,
        paper_id=paper_id,
    )
    record = result.single()
    ranked_cohort = record["ranked_cohort"] if record else []
    cohort_rank = ranked_cohort.index(current_canonical) + 1 if current_canonical and current_canonical in ranked_cohort else None

    return {
        "overall_rank": overall_rank,
        "year_cohort_rank": cohort_rank,
        "total_papers_in_db": len(ranked_papers),
    }


def _get_canonical_id(session, paper_id: str) -> str | None:
    """Return coalesce(arxiv_id, s2_id) for the paper."""
    result = session.run(
        """
        MATCH (p:Paper)
        WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
        RETURN coalesce(p.arxiv_id, p.s2_id) as canonical_id
        """,
        paper_id=paper_id,
    )
    record = result.single()
    return record["canonical_id"] if record else None


def compute_trends(session, paper_id: str, citing_papers: list, paper_year: int) -> dict:
    """Analyze citation trends over time."""
    if not paper_year or not citing_papers:
        return {"trend": "insufficient_data"}

    result = session.run(
        """
        MATCH (p:Paper)
        WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
        MATCH (p)<-[:CITES]-(citing:Paper)
        WHERE citing.year IS NOT NULL
        RETURN citing.year as year, count(*) as citations
        ORDER BY year
    """,
        paper_id=paper_id,
    )
    citations_by_year = {record["year"]: record["citations"] for record in result}

    if not citations_by_year:
        return {"trend": "no_temporal_data"}

    peak_year = max(citations_by_year, key=citations_by_year.get)
    recent_years = sorted(citations_by_year.keys())[-3:]
    if len(recent_years) >= MIN_YEARS_FOR_TREND:
        recent_trend = (
            "growing"
            if citations_by_year[recent_years[-1]] > citations_by_year[recent_years[0]]
            else "declining"
        )
    else:
        recent_trend = "stable"

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


def store_influence_metrics(session, paper_id: str, scores: dict, rankings: dict):
    """Store computed metrics back to the graph."""
    session.run(
        """
        MATCH (p:Paper)
        WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
        SET p.pagerank_score = $pagerank,
            p.citation_count = $citations,
            p.citation_velocity = $velocity,
            p.influence_rank = $rank,
            p.betweenness_score = $betweenness,
            p.last_influence_update = datetime()
    """,
        paper_id=paper_id,
        pagerank=scores.get("pagerank", 0),
        citations=scores.get("total_citations", 0),
        velocity=scores.get("citation_velocity", 0),
        rank=rankings.get("overall_rank"),
        betweenness=scores.get("betweenness", 0),
    )


def compute_paper_influence(
    paper_id: str,
    metrics: list[str] | None = None,
    _time_window: str = "all",
    normalize_by_age: bool = True,
    store_in_graph: bool = True,
) -> dict[str, Any]:
    """
    Compute influence metrics for a paper in the citation graph.

    Args:
        paper_id: Paper ID (arXiv ID, Semantic Scholar ID, or DOI).
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
        result = session.run(
            """
            MATCH (p:Paper)
            WHERE p.arxiv_id = $paper_id OR p.s2_id = $paper_id
            OPTIONAL MATCH (p)<-[:CITES]-(citing:Paper)
            OPTIONAL MATCH (p)-[:CITES]->(cited:Paper)
            OPTIONAL MATCH (citing)<-[:CITES]-(second_order:Paper)
            WITH p,
                 collect(DISTINCT citing) as citing_papers,
                 collect(DISTINCT cited) as cited_papers,
                 collect(DISTINCT second_order) as second_order_papers
            RETURN p.title as title,
                   p.arxiv_id as arxiv_id,
                   p.s2_id as s2_id,
                   p.year as year,
                   citing_papers,
                   cited_papers,
                   second_order_papers
            """,
            paper_id=paper_id,
        )

        record = result.single()
        if not record:
            return {"error": f"Paper {paper_id} not found in database"}

        canonical_id = record["arxiv_id"] or record["s2_id"]
        paper_data = {
            "paper_id": canonical_id,
            "title": record["title"],
            "arxiv_id": record["arxiv_id"],
            "s2_id": record["s2_id"],
            "year": record["year"],
        }

        citing_papers = record["citing_papers"]
        _ = record["cited_papers"]
        second_order_papers = record["second_order_papers"]

        current_year = datetime.datetime.now().year
        paper_age = current_year - (paper_data["year"] or current_year)
        paper_age = max(1, paper_age)

        influence_scores = {}

        if "citations" in metrics:
            influence_scores["total_citations"] = len(citing_papers)

        if "citation_velocity" in metrics:
            velocity = len(citing_papers) / paper_age if paper_age > 0 else 0
            influence_scores["citation_velocity"] = round(velocity, 2)

        if "second_order_citations" in metrics:
            influence_scores["second_order_citations"] = len(second_order_papers)

        if "pagerank" in metrics:
            influence_scores["pagerank"] = round(compute_pagerank(session, paper_id), 6)

        if "betweenness" in metrics:
            influence_scores["betweenness"] = round(compute_betweenness(session, paper_id), 6)

        if "h_index" in metrics:
            influence_scores["h_index_contribution"] = compute_h_index_contribution(
                session, paper_id
            )

        if normalize_by_age and paper_age > 0:
            normalized_score = (
                influence_scores.get("total_citations", 0) / paper_age
                + influence_scores.get("pagerank", 0) * 1000
            )
            influence_scores["age_normalized_score"] = round(normalized_score, 2)

        rankings = compute_rankings(session, paper_id, influence_scores)
        trends = compute_trends(session, paper_id, citing_papers, paper_data["year"])

        if store_in_graph:
            store_influence_metrics(session, paper_id, influence_scores, rankings)

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


def find_most_influential_papers(
    topic: str | None = None,
    min_year: int | None = None,
    limit: int = 10,
    metric: str = "pagerank",
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
        return [{"error": "Neo4j not configured."}]

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
            RETURN coalesce(p.arxiv_id, p.s2_id) as paper_id,
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
                    "paper_id": record["paper_id"],
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


def register(mcp):
    """Register influence tools with the FastMCP instance."""
    mcp.tool()(compute_paper_influence)
    mcp.tool()(find_most_influential_papers)
