#!/usr/bin/env python3
"""Neo4j Citation Graph Schema and Demo Data.

Run this script to:
1. Create indexes for optimal query performance
2. Optionally seed demo data for testing

Usage:
    python neo4j_citation_demo.py              # Schema only
    python neo4j_citation_demo.py --seed       # Schema + demo data
    python neo4j_citation_demo.py --clear      # Clear all data first
"""

import argparse
import logging
import os
import sys

from neo4j import GraphDatabase, NotificationMinimumSeverity

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
logger = logging.getLogger(__name__)

URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
USER = os.environ.get("NEO4J_USER", "neo4j")
PASSWORD = os.environ.get("NEO4J_PASSWORD", "password123")


class CitationGraph:
    def __init__(self, uri: str = URI, auth: tuple[str, str] = (USER, PASSWORD)):
        self.driver = GraphDatabase.driver(
            uri,
            auth=auth,
            notifications_min_severity=NotificationMinimumSeverity.OFF,
        )

    def close(self) -> None:
        self.driver.close()

    def clear_database(self) -> None:
        """Remove all nodes and relationships."""
        with self.driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")
        logger.info("✓ Database cleared")

    def create_schema(self) -> None:
        """Create indexes and constraints for optimal performance."""
        with self.driver.session() as s:
            # --- Paper indexes ---
            # Primary identifiers
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.s2_id)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.arxiv_id)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.doi)")
            
            # Legacy index for backward compatibility
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.id)")
            
            # Query optimization
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.year)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.citation_count)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.title)")
            
            # Influence metrics
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.pagerank_score)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Paper) ON (p.influential_citation_count)")

            # --- Author indexes ---
            s.run("CREATE INDEX IF NOT EXISTS FOR (a:Author) ON (a.s2_id)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (a:Author) ON (a.name)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (a:Author) ON (a.h_index)")
            s.run("CREATE INDEX IF NOT EXISTS FOR (a:Author) ON (a.citation_count)")

            # --- Topic indexes ---
            s.run("CREATE INDEX IF NOT EXISTS FOR (t:Topic) ON (t.name)")

            # --- Full-text search indexes (optional, for natural language queries) ---
            try:
                s.run("""
                    CREATE FULLTEXT INDEX paper_search IF NOT EXISTS
                    FOR (p:Paper) ON EACH [p.title, p.abstract, p.tldr]
                """)
                logger.info("✓ Full-text search index created")
            except Exception as e:
                logger.warning("  Full-text index skipped (may already exist): %s", e)

            # --- Vector index for embeddings (Neo4j 5.11+) ---
            try:
                s.run("""
                    CREATE VECTOR INDEX paper_embedding IF NOT EXISTS
                    FOR (p:Paper) ON (p.embedding)
                    OPTIONS {
                        indexConfig: {
                            `vector.dimensions`: 768,
                            `vector.similarity_function`: 'cosine'
                        }
                    }
                """)
                logger.info("✓ Vector index created for embeddings")
            except Exception as e:
                logger.warning("  Vector index skipped (requires Neo4j 5.11+): %s", e)

        logger.info("✓ Schema indexes created")

    def show_schema(self) -> None:
        """Display current indexes."""
        logger.info("\nCurrent indexes:")
        with self.driver.session() as s:
            result = s.run("SHOW INDEXES YIELD name, labelsOrTypes, properties, type")
            for record in result:
                logger.info(
                    "  %s: %s.%s (%s)",
                    record["name"],
                    record["labelsOrTypes"],
                    record["properties"],
                    record["type"],
                )

    def populate_demo_data(self) -> None:
        """
        Create a sample citation network for testing.

        Graph Structure:
        (Author)-[:AUTHORED]->(Paper)-[:CITES]->(Paper)
                                    `-[:ABOUT]->(Topic)
        """
        with self.driver.session() as s:
            # Create foundational papers (highly cited, with S2-style IDs)
            s.run("""
                CREATE (p1:Paper {
                    s2_id: 'demo-paper-001',
                    arxiv_id: '1706.03762',
                    title: 'Attention Is All You Need',
                    year: 2017,
                    citation_count: 50000,
                    influential_citation_count: 5000,
                    abstract: 'The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...',
                    tldr: 'Introduces the Transformer architecture using self-attention mechanisms.',
                    fields_of_study: ['Computer Science', 'Machine Learning']
                })
                CREATE (p2:Paper {
                    s2_id: 'demo-paper-002',
                    arxiv_id: '1810.04805',
                    title: 'BERT: Pre-training of Deep Bidirectional Transformers',
                    year: 2018,
                    citation_count: 40000,
                    influential_citation_count: 4000,
                    abstract: 'We introduce a new language representation model called BERT...',
                    tldr: 'Introduces BERT, a bidirectional transformer for language understanding.',
                    fields_of_study: ['Computer Science', 'Natural Language Processing']
                })
                CREATE (p3:Paper {
                    s2_id: 'demo-paper-003',
                    arxiv_id: '1609.02907',
                    title: 'Semi-Supervised Classification with Graph Convolutional Networks',
                    year: 2016,
                    citation_count: 15000,
                    influential_citation_count: 1500,
                    abstract: 'We present a scalable approach for semi-supervised learning on graph-structured data...',
                    tldr: 'Introduces GCNs for semi-supervised node classification.',
                    fields_of_study: ['Computer Science', 'Machine Learning']
                })

                // Authors with S2-style IDs
                CREATE (a1:Author {
                    s2_id: 'demo-author-001',
                    name: 'Ashish Vaswani',
                    h_index: 45,
                    citation_count: 100000,
                    paper_count: 50,
                    affiliations: ['Google Brain']
                })
                CREATE (a2:Author {
                    s2_id: 'demo-author-002',
                    name: 'Jacob Devlin',
                    h_index: 35,
                    citation_count: 80000,
                    paper_count: 30,
                    affiliations: ['Google AI']
                })
                CREATE (a3:Author {
                    s2_id: 'demo-author-003',
                    name: 'Thomas Kipf',
                    h_index: 25,
                    citation_count: 30000,
                    paper_count: 20,
                    affiliations: ['University of Amsterdam']
                })

                // Topics
                CREATE (t1:Topic {name: 'Machine Learning'})
                CREATE (t2:Topic {name: 'Natural Language Processing'})
                CREATE (t3:Topic {name: 'Deep Learning'})
                CREATE (t4:Topic {name: 'Graph Neural Networks'})
                CREATE (t5:Topic {name: 'Computer Science'})

                // Author-Paper relationships
                CREATE (a1)-[:AUTHORED {role: 'primary'}]->(p1)
                CREATE (a2)-[:AUTHORED {role: 'primary'}]->(p2)
                CREATE (a3)-[:AUTHORED {role: 'primary'}]->(p3)

                // Paper-Topic relationships
                CREATE (p1)-[:ABOUT]->(t1)
                CREATE (p1)-[:ABOUT]->(t3)
                CREATE (p1)-[:ABOUT]->(t5)
                CREATE (p2)-[:ABOUT]->(t2)
                CREATE (p2)-[:ABOUT]->(t3)
                CREATE (p2)-[:ABOUT]->(t5)
                CREATE (p3)-[:ABOUT]->(t1)
                CREATE (p3)-[:ABOUT]->(t4)
                CREATE (p3)-[:ABOUT]->(t5)
            """)

            # Create newer papers that cite the foundational ones
            s.run("""
                CREATE (p4:Paper {
                    s2_id: 'demo-paper-004',
                    arxiv_id: '2005.14165',
                    title: 'Language Models are Few-Shot Learners (GPT-3)',
                    year: 2020,
                    citation_count: 10000,
                    influential_citation_count: 1000,
                    tldr: 'Shows that scaling language models improves few-shot learning.',
                    fields_of_study: ['Computer Science', 'Machine Learning']
                })
                CREATE (p5:Paper {
                    s2_id: 'demo-paper-005',
                    arxiv_id: '2103.00020',
                    title: 'Learning Transferable Visual Models From Natural Language (CLIP)',
                    year: 2021,
                    citation_count: 8000,
                    influential_citation_count: 800,
                    tldr: 'Learns visual representations from natural language supervision.',
                    fields_of_study: ['Computer Science', 'Computer Vision']
                })
                CREATE (p6:Paper {
                    s2_id: 'demo-paper-006',
                    arxiv_id: '2303.08774',
                    title: 'GPT-4 Technical Report',
                    year: 2023,
                    citation_count: 3000,
                    influential_citation_count: 300,
                    tldr: 'Describes GPT-4, a large multimodal model.',
                    fields_of_study: ['Computer Science', 'Machine Learning']
                })

                CREATE (a4:Author {
                    s2_id: 'demo-author-004',
                    name: 'Tom Brown',
                    h_index: 30,
                    citation_count: 50000,
                    paper_count: 25,
                    affiliations: ['OpenAI']
                })
                CREATE (a5:Author {
                    s2_id: 'demo-author-005',
                    name: 'Alec Radford',
                    h_index: 35,
                    citation_count: 60000,
                    paper_count: 30,
                    affiliations: ['OpenAI']
                })

                WITH p4, p5, p6, a4, a5
                MATCH (p1:Paper {s2_id: 'demo-paper-001'})
                MATCH (p2:Paper {s2_id: 'demo-paper-002'})
                MATCH (t1:Topic {name: 'Machine Learning'})
                MATCH (t3:Topic {name: 'Deep Learning'})

                // Author relationships
                CREATE (a4)-[:AUTHORED]->(p4)
                CREATE (a5)-[:AUTHORED]->(p4)
                CREATE (a5)-[:AUTHORED]->(p5)
                CREATE (a4)-[:AUTHORED]->(p6)

                // Citation relationships
                CREATE (p4)-[:CITES]->(p1)
                CREATE (p4)-[:CITES]->(p2)
                CREATE (p5)-[:CITES]->(p1)
                CREATE (p5)-[:CITES]->(p2)
                CREATE (p6)-[:CITES]->(p1)
                CREATE (p6)-[:CITES]->(p2)
                CREATE (p6)-[:CITES]->(p4)
                CREATE (p6)-[:CITES]->(p5)

                // Topic relationships
                CREATE (p4)-[:ABOUT]->(t1)
                CREATE (p4)-[:ABOUT]->(t3)
                CREATE (p5)-[:ABOUT]->(t1)
                CREATE (p6)-[:ABOUT]->(t1)
                CREATE (p6)-[:ABOUT]->(t3)
            """)

            # Update citation counts based on actual relationships
            s.run("""
                MATCH (p:Paper)
                OPTIONAL MATCH (p)<-[c:CITES]-()
                WITH p, count(c) as incoming
                SET p.citations = incoming
            """)

        logger.info("✓ Demo data created (6 papers, 5 authors, 5 topics)")

    def show_stats(self) -> None:
        """Display graph statistics."""
        with self.driver.session() as s:
            result = s.run("""
                MATCH (p:Paper) WITH count(p) as papers
                MATCH (a:Author) WITH papers, count(a) as authors
                MATCH (t:Topic) WITH papers, authors, count(t) as topics
                MATCH ()-[c:CITES]->() WITH papers, authors, topics, count(c) as citations
                MATCH ()-[au:AUTHORED]->() WITH papers, authors, topics, citations, count(au) as authorships
                RETURN papers, authors, topics, citations, authorships
            """)
            record = result.single()
            logger.info("\nGraph statistics:")
            logger.info("  Papers: %d", record["papers"])
            logger.info("  Authors: %d", record["authors"])
            logger.info("  Topics: %d", record["topics"])
            logger.info("  Citation edges: %d", record["citations"])
            logger.info("  Authorship edges: %d", record["authorships"])

    def run_sample_queries(self) -> None:
        """Run sample queries to verify the graph."""
        logger.info("\n" + "=" * 50)
        logger.info("SAMPLE QUERIES")
        logger.info("=" * 50)

        with self.driver.session() as s:
            # Most cited papers
            logger.info("\nMost cited papers:")
            result = s.run("""
                MATCH (p:Paper)
                RETURN p.title as title, p.citation_count as citations, p.year as year
                ORDER BY p.citation_count DESC
                LIMIT 5
            """)
            for r in result:
                logger.info("  [%s] %s (%s)", r["citations"], r["title"][:50], r["year"])

            # Citation chains
            logger.info("\nCitation chains (papers citing papers):")
            result = s.run("""
                MATCH path = (p1:Paper)-[:CITES*1..2]->(p2:Paper)
                RETURN p1.title as citing, p2.title as cited, length(path) as depth
                LIMIT 5
            """)
            for r in result:
                logger.info("  %s → %s", r["citing"][:30], r["cited"][:30])

            # Co-authorship
            logger.info("\nProlific authors:")
            result = s.run("""
                MATCH (a:Author)
                RETURN a.name as name, a.h_index as h_index, a.citation_count as citations
                ORDER BY a.h_index DESC
                LIMIT 5
            """)
            for r in result:
                logger.info("  %s (h-index: %s, citations: %s)", r["name"], r["h_index"], r["citations"])

            # Topic coverage
            logger.info("\nTopics by paper count:")
            result = s.run("""
                MATCH (t:Topic)<-[:ABOUT]-(p:Paper)
                RETURN t.name as topic, count(p) as papers
                ORDER BY papers DESC
            """)
            for r in result:
                logger.info("  %s: %d papers", r["topic"], r["papers"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Neo4j Citation Graph Setup")
    parser.add_argument("--seed", action="store_true", help="Populate with demo data")
    parser.add_argument("--clear", action="store_true", help="Clear existing data first")
    parser.add_argument("--queries", action="store_true", help="Run sample queries")
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("NEO4J CITATION GRAPH SETUP")
    logger.info("=" * 60)
    logger.info("Connecting to %s as %s", URI, USER)

    graph = CitationGraph()

    try:
        if args.clear:
            graph.clear_database()

        graph.create_schema()
        graph.show_schema()

        if args.seed:
            graph.populate_demo_data()

        graph.show_stats()

        if args.queries:
            graph.run_sample_queries()

        logger.info("\n✓ Setup complete!")
        return 0

    except Exception:
        logger.exception("Error during setup")
        return 1
    finally:
        graph.close()


if __name__ == "__main__":
    sys.exit(main())