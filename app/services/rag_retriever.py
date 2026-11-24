"""Local ChromaDB RAG retriever for schemas, glossary terms, and few-shot SQL."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.bigquery_client import TableSchemaInfo

logger = get_logger(__name__)

SCHEMA_COLLECTION = "table_schemas"
GLOSSARY_COLLECTION = "business_glossary"
EXAMPLES_COLLECTION = "few_shot_examples"


@dataclass(frozen=True)
class RetrievedContext:
    """Grounded context retrieved for a user's natural language question."""

    schemas: list[str]
    glossary: list[str]
    examples: list[str]

    def to_prompt_text(self) -> str:
        sections: list[str] = []
        if self.schemas:
            sections.append("### Relevant Table Schemas\n" + "\n\n".join(self.schemas))
        if self.glossary:
            sections.append(
                "### Business Glossary & Metric Definitions\n" + "\n".join(self.glossary)
            )
            sections.append("### Verified BigQuery SQL Examples\n" + "\n\n".join(self.examples))
        return "\n\n".join(sections)


class RAGRetriever:
    """Indexes and retrieves dataset context from a local persistent ChromaDB."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: chromadb.ClientAPI | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if client is not None:
            self.client = client
        else:
            persist_dir = self.settings.chroma_persist_dir
            persist_dir.mkdir(parents=True, exist_ok=True)
            self.client = chromadb.PersistentClient(path=str(persist_dir))

    def _get_collection(self, name: str) -> chromadb.Collection:
        return self.client.get_or_create_collection(name=name)

    def index_table_schemas(self, tables: list[TableSchemaInfo]) -> int:
        """Upsert introspected BigQuery table schemas and sample rows."""
        if not tables:
            return 0

        collection = self._get_collection(SCHEMA_COLLECTION)
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []

        for table in tables:
            col_lines = [
                f"  - {c['name']} ({c['type']}, nullable={c['nullable']})"
                for c in table.columns
            ]
            doc_parts = [
                f"Table: `{table.full_table_id}`",
                "Columns:\n" + "\n".join(col_lines),
            ]
            if table.sample_rows:
                sample_preview = json.dumps(table.sample_rows[:2], default=str)
                doc_parts.append(f"Sample rows: {sample_preview}")

            ids.append(f"schema_{table.table_name}")
            documents.append("\n".join(doc_parts))
            metadatas.append(
                {"table_name": table.table_name, "full_table_id": table.full_table_id}
            )

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(
            "Indexed table schemas into ChromaDB",
            extra={"extra_data": {"table_count": len(tables)}},
        )
        return len(tables)

    def index_glossary(self, glossary_path: Path = Path("data/business_glossary.json")) -> int:
        """Upsert business metric definitions from JSON."""
        items: list[dict[str, Any]] = json.loads(glossary_path.read_text(encoding="utf-8"))
        if not items:
            return 0

        collection = self._get_collection(GLOSSARY_COLLECTION)
        ids = [item["id"] for item in items]
        documents = [
            f"- **{item['term']}**: {item['definition']} Formula: `{item['formula']}` "
            f"(Tables: {', '.join(item.get('tables', []))})"
            for item in items
        ]
        metadatas = [{"term": item["term"]} for item in items]

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(
            "Indexed business glossary into ChromaDB",
            extra={"extra_data": {"glossary_count": len(items)}},
        )
        return len(items)

    def index_few_shot_examples(
        self,
        examples_path: Path = Path("data/few_shot_examples.json"),
    ) -> int:
        """Upsert verified NL-to-BigQuery SQL examples from JSON."""
        items: list[dict[str, Any]] = json.loads(examples_path.read_text(encoding="utf-8"))
        if not items:
            return 0

        collection = self._get_collection(EXAMPLES_COLLECTION)
        ids = [item["id"] for item in items]
        documents = [
            f"Question: {item['question']}\nSQL:\n```sql\n{item['sql']}\n```"
            for item in items
        ]
        metadatas = [{"question": item["question"]} for item in items]

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info(
            "Indexed few-shot SQL examples into ChromaDB",
            extra={"extra_data": {"example_count": len(items)}},
        )
        return len(items)

    def _query_collection(self, name: str, query_text: str, n_results: int) -> list[str]:
        collection = self._get_collection(name)
        count = collection.count()
        if count == 0 or n_results <= 0:
            return []

        result = collection.query(
            query_texts=[query_text],
            n_results=min(n_results, count),
        )
        docs = result.get("documents") or [[]]
        return list(docs[0])

    def retrieve(
        self,
        question: str,
        n_schemas: int = 7,
        n_glossary: int = 3,
        n_examples: int = 3,
    ) -> RetrievedContext:
        """Retrieve relevant schemas, glossary definitions, and SQL examples."""
        return RetrievedContext(
            schemas=self._query_collection(SCHEMA_COLLECTION, question, n_schemas),
            glossary=self._query_collection(GLOSSARY_COLLECTION, question, n_glossary),
            examples=self._query_collection(EXAMPLES_COLLECTION, question, n_examples),
        )