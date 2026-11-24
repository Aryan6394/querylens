"""CLI script to index BigQuery schemas, glossary terms, and few-shot SQL into ChromaDB."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.bigquery_client import BigQueryService
from app.services.rag_retriever import RAGRetriever


def main() -> None:
    parser = argparse.ArgumentParser(description="Index dataset context into ChromaDB.")
    parser.add_argument(
        "--skip-bigquery",
        action="store_true",
        help="Index only local glossary and few-shot JSON files without calling BigQuery.",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=2,
        help="Number of sample rows to fetch per table (default: 2).",
    )
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level)
    retriever = RAGRetriever(settings=settings)

    glossary_count = retriever.index_glossary(Path("data/business_glossary.json"))
    example_count = retriever.index_few_shot_examples(Path("data/few_shot_examples.json"))

    schema_count = 0
    if not args.skip_bigquery:
        bq = BigQueryService(settings=settings)
        tables = bq.fetch_dataset_schema(sample_limit=args.sample_rows)
        schema_count = retriever.index_table_schemas(tables)

    print(
        f"Indexing complete | Schemas: {schema_count} | "
        f"Glossary: {glossary_count} | Few-shot examples: {example_count}"
    )


if __name__ == "__main__":
    main()