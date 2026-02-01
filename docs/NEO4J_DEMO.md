# Citation graph (Neo4j + MCP)

The MCP server talks to Neo4j and exposes citation-graph tools so OpenWebUI chat can query and extend the graph. A seed/demo script populates the DB and runs example queries; the server exposes tools including `neo4j_execute_cypher`, arXiv search, add paper, and influence metrics.

## Why knowledge graphs?

- **Model relationships naturally** — Entities and links map directly to nodes and edges; no heavy normalization or junction tables.
- **Traverse efficiently** — Follow connections in one hop; path and neighborhood queries stay simple.
- **Discover patterns** — Structure and connectivity (clusters, centrality, paths) are first-class.
- **Query relationships directly** — No JOINs; add relationship types without schema churn.

The stack uses a **citation graph**: nodes = Papers, Authors, Topics; edges = CITES, AUTHORED, ABOUT. Node properties include title/year/citation_count on papers, name/affiliation on authors.

## Prerequisites

- Docker Compose (`make dev` or `make prod`).

## Quick start

1. **Start the stack**  
   `make dev` or `make prod`.

2. **Seed the citation graph (once)**  
   ```bash
   make seed-db
   ```
   Runs the seed/demo script inside the mcp-server container. Run anytime to reset and re-seed.

3. **Connect the MCP server in OpenWebUI**  
   Admin Settings → External Tools → Add Connection → URL. In a chat, enable tools via Integrations.

4. **Edit the chat system prompt**  
   Use the controls in the upper right of the chat to open the system prompt / custom instructions. Paste the [System prompt](#system-prompt) block below.

5. **Use the citation graph tools in chat**  
   Enable the MCP tools in Integrations and ask about the citation graph (e.g. "Find papers by Alice Chen", "Search for papers on transformers", "Add paper 1609.02907").

## Example queries

Prompts that elicit the intended tool flow:

**Authors (check graph first, then API only if needed)**  
- "Search for authors named Yann LeCun and add the first one to the graph." → `semantic_scholar_author_search` → for the chosen author: `graph_get_author(author_id)`; if not in graph → `semantic_scholar_get_author(author_id)` → `graph_add_author(...)` with the returned data.  
- "Is author 2043216 in the graph? If not, add them." → `graph_get_author("2043216")`; if "Author not in graph" → `semantic_scholar_get_author("2043216")` → `graph_add_author(...)`.  
- "Add Geoffrey Hinton to the citation graph." → search by name, then same flow (graph_get_author first, then API + graph_add_author if missing).

**Papers and graph**  
- "Find papers by Alice Chen" → `neo4j_execute_cypher` (MATCH Author → Paper).  
- "Search for papers on graph databases" → `arxiv_search` or `semantic_scholar_search`.  
- "Add paper 1609.02907 to the graph" → `arxiv_add_paper("1609.02907")`.  
- "Add paper 2301.07041 and its references" → `graph_get_paper("2301.07041")`; if not in graph → `semantic_scholar_get_paper("2301.07041")` → `graph_add_paper(...)` with returned data; then `semantic_scholar_expand_citations` (direction=references).

**Influence**  
- "How influential is paper 1609.02907?" → `compute_paper_influence("1609.02907")`.  
- "Top 10 most influential papers on machine learning" → `find_most_influential_papers(topic="Machine Learning", limit=10)`.

## System prompt

Paste into the chat system prompt (upper-right controls). For copy-paste convenience, the same prompt is in [SYSTEM_PROMPT.md](SYSTEM_PROMPT.md).

```
You have access to a Neo4j citation graph with these tools. You can call multiple tools in sequence; use each tool's result to decide the next step. For example: if graph_get_author(author_id) returns author data (not "Author not in graph"), stop—do not call graph_add_author or semantic_scholar_get_author. Same for papers: if graph_get_paper(paper_id) returns paper data (not "Paper not in graph"), stop—do not call semantic_scholar_get_paper or graph_add_paper.

Graph
1. neo4j_execute_cypher — Query the graph. Use when the user asks about papers, authors, topics, or custom analysis. Pass "query" (Cypher) and optionally "params". Read-only only (MATCH, RETURN, etc.); writes are blocked.
2. link_papers — Manually add a citation edge: citing_arxiv_id (paper that cites) and cited_arxiv_id (paper cited). Both papers must already exist; add them first with arxiv_add_paper or graph_add_paper (after semantic_scholar_get_paper if from S2).
3. graph_get_paper — Look up paper in graph by s2_id, arxiv_id, or doi (read-only). Use first to avoid calling the API for papers already in Neo4j. Returns paper data or "Paper not in graph".
4. graph_add_paper — Add or update a paper node and related authors/topics (DB only). Call only when the paper is NOT already in the graph. If graph_get_paper or a Cypher query shows the paper exists, do not call this. Use payload from semantic_scholar_get_paper (map paperId→s2_id, citationCount→citation_count, openAccessPdf→open_access_url, authors list with authorId/name).
5. graph_get_author — Look up author in graph by s2_id (read-only). Use first to avoid calling the API for authors already in Neo4j. Returns author data or "Author not in graph".
6. graph_add_author — Add or update an author node (DB only). Call only when the author is NOT already in the graph. If graph_get_author or a Cypher query shows the author exists, do not call this.

arXiv (metadata only)
7. arxiv_search — Search arXiv by topic. Returns paper IDs and titles. Use when the user wants to find papers by keyword.
8. arxiv_add_paper — Add an arXiv paper to the graph by arXiv ID (e.g. 2301.07041 or URL). Fetches title, authors, topics from arXiv only. Safe to call multiple times.

Semantic Scholar (papers, authors, citations, embeddings)
9. semantic_scholar_get_paper — Get paper by S2 ID, ARXIV:..., DOI:..., or URL (API only). Call only when graph_get_paper returns not found. Returns paperId, title, year, abstract, authors, fieldsOfStudy, citationCount, tldr, openAccessPdf, externalIds; optionally include_embedding. No DB side effects.
10. semantic_scholar_search — Search papers by keyword (broader than arXiv). Returns paper IDs; add with graph_get_paper then semantic_scholar_get_paper + graph_add_paper if not in graph. Supports year, fields_of_study, min_citations, open_access_only.
11. semantic_scholar_get_author — Get author by Semantic Scholar author ID (API only). Call only when graph_get_author returns not found. Optionally include_papers. No DB side effects.
12. semantic_scholar_author_search — Search authors by name. Returns author IDs for graph_get_author / semantic_scholar_get_author / graph_add_author.
13. semantic_scholar_expand_citations — Expand a paper's references (papers it cites) or citations (papers citing it). Use direction='references' or 'citations'. Optionally add fetched papers and CITES edges to the graph.
14. semantic_scholar_similar_papers — Find papers similar to a given paper (by embedding). Paper must have an embedding in the graph; use semantic_scholar_add_embeddings first.
15. semantic_scholar_add_embeddings — Batch-add SPECTER2 embeddings to papers in the graph (rate-limited). Enables semantic_scholar_similar_papers.
16. semantic_scholar_cluster_papers — Cluster papers by embedding similarity. Requires embeddings (run semantic_scholar_add_embeddings first). Optional topic filter.

Influence (require papers in graph)
17. compute_paper_influence — Influence metrics for one paper: citations, PageRank, betweenness, citation velocity, trends. Paper identified by paper_id (arXiv ID, Semantic Scholar ID, or DOI).
18. find_most_influential_papers — Top papers by topic and/or min_year, ranked by metric (pagerank, citations, betweenness). Returns paper_id (arXiv or S2), title, year, scores.

Graph schema:
- Nodes: Paper (arxiv_id, s2_id, title, year, abstract, citations, embedding, ...), Author (name, s2_id, ...), Topic (name)
- Relationships: CITES (Paper -> Paper), AUTHORED (Author -> Paper), ABOUT (Paper -> Topic)

When to use which:
- Finding papers by topic: arxiv_search or semantic_scholar_search (SS is broader).
- Adding a paper by arXiv ID (metadata only): arxiv_add_paper.
- Adding a paper with rich metadata / citations from Semantic Scholar: First graph_get_paper(paper_id). If not in graph, semantic_scholar_get_paper(paper_id) then graph_add_paper(...) with the returned data (map keys as above). If the paper is already in the graph, do NOT call graph_add_paper or semantic_scholar_get_paper—do not "add again" or "refresh" existing papers. Then semantic_scholar_expand_citations for refs/citations.
- Adding citation edges: semantic_scholar_expand_citations, or link_papers if both papers already in graph.
- Authors: First graph_get_author(author_id). If not in graph, semantic_scholar_get_author(author_id) then graph_add_author(...) with the returned data. If the author is already in the graph (from graph_get_author or from a Cypher query), do NOT call graph_add_author or semantic_scholar_get_author—do not "add again" or "refresh" existing authors.
- Similar papers: semantic_scholar_add_embeddings then semantic_scholar_similar_papers.
- Influence: compute_paper_influence (paper_id), find_most_influential_papers.
```

## Tools

The MCP server exposes graph, arXiv, Semantic Scholar, and influence tools. The system prompt above lists them and when to use each.

| Tool | Description |
|------|-------------|
| **Graph** | |
| `neo4j_execute_cypher` | Execute read-only Cypher queries against the citation graph |
| `link_papers` | Link two papers already in the graph (citing → cited) |
| `graph_get_paper` | Look up paper in graph by s2_id, arxiv_id, or doi (read-only); use first to avoid API for papers already in Neo4j |
| `graph_add_paper` | Add or update paper node and authors/topics (DB only); use payload from semantic_scholar_get_paper when not in graph |
| `graph_get_author` | Look up author in graph by s2_id (read-only); use first to avoid API for authors already in Neo4j |
| `graph_add_author` | Add or update author node (DB only); use payload from semantic_scholar_get_author when not in graph |
| **arXiv** | |
| `arxiv_search` | Search arXiv by topic; returns paper IDs and titles |
| `arxiv_add_paper` | Add an arXiv paper to the graph (metadata from arXiv only) |
| **Semantic Scholar** | |
| `semantic_scholar_get_paper` | Get paper by S2/ARXIV/DOI/URL (API only); call when graph_get_paper returns not found; optionally include_embedding |
| `semantic_scholar_search` | Search papers (broader than arXiv); filter by year, field, citations |
| `semantic_scholar_get_author` | Get author by S2 ID (API only); call when graph_get_author returns not found |
| `semantic_scholar_author_search` | Search authors by name |
| `semantic_scholar_expand_citations` | Fetch references or citations for a paper; optionally add to graph |
| `semantic_scholar_similar_papers` | Find similar papers by embedding (run add_embeddings first) |
| `semantic_scholar_add_embeddings` | Batch-add SPECTER2 embeddings to papers in graph |
| `semantic_scholar_cluster_papers` | Cluster papers by embedding (requires embeddings) |
| **Influence** | |
| `compute_paper_influence` | Influence metrics for one paper; paper_id = arXiv ID, S2 ID, or DOI |
| `find_most_influential_papers` | Top papers by topic/year and metric |

**neo4j_execute_cypher safety:** Queries are validated; only read-only operations (MATCH, RETURN, etc.) are allowed. Dangerous operations (DELETE, DROP, CREATE, MERGE, SET) are blocked.

## Neo4j Browser (local only)

Inspect the graph at `http://localhost:7474`. Sign in with user `neo4j` and `NEO4J_PASSWORD` (default `password123`).

**Environment:** Neo4j connection uses `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. See [env.example](../env.example); defaults are fine for local dev.
