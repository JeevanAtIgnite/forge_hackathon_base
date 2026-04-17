"""Build a business-facing semantic model from structured workbook schema."""

from __future__ import annotations

import re

from formula_engine.models import FormulaCatalog
from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema
from semantic_model.models import SemanticEntity, SemanticMetric, SemanticModel


class SemanticModelBuilder:
    """Infer entities and metrics from workbook schema and formula logic."""

    def build(
        self,
        schema: WorkbookSchema,
        formulas: FormulaCatalog,
        relationships: RelationshipGraphModel,
    ) -> SemanticModel:
        entity_details: list[SemanticEntity] = []
        metric_details: list[SemanticMetric] = []

        for table in schema.tables:
            entity_columns = [
                column.name
                for column in table.columns
                if column.semantic_role in {"dimension", "identifier"}
            ]
            metric_columns = [
                column.name
                for column in table.columns
                if column.semantic_role == "metric"
            ]

            if entity_columns:
                entity_name = self._entity_name(entity_columns[0])
                entity_details.append(
                    SemanticEntity(
                        name=entity_name,
                        table_name=table.table_name,
                        columns=entity_columns,
                        description=f"{entity_name} is represented in {table.table_name} by {', '.join(entity_columns[:4])}.",
                    )
                )

            for column_name in metric_columns:
                metric_details.append(
                    SemanticMetric(
                        name=self._pretty(column_name),
                        table_name=table.table_name,
                        source_columns=[column_name],
                        description=f"{self._pretty(column_name)} is a tracked metric in {table.table_name}.",
                        derived=False,
                    )
                )

        for derived in formulas.derived_columns:
            metric_details.append(
                SemanticMetric(
                    name=self._pretty(derived.column_name),
                    table_name=derived.table_name,
                    source_columns=derived.depends_on,
                    description=derived.logic,
                    derived=True,
                )
            )

        entities = list(dict.fromkeys(detail.name for detail in entity_details))
        metrics = list(dict.fromkeys(detail.name for detail in metric_details))
        derived_metrics = list(dict.fromkeys(self._pretty(item.column_name) for item in formulas.derived_columns))
        tables = [table.table_name for table in schema.tables]

        summary = (
            f"The workbook exposes {len(tables)} logical tables, {len(entities)} business entities, "
            f"and {len(metrics)} metrics. It is suitable for execution-backed analytics over Excel data."
        )

        return SemanticModel(
            tables=tables,
            entities=entities,
            metrics=metrics,
            relationships=relationships.relationships,
            derived_metrics=derived_metrics,
            entity_details=entity_details,
            metric_details=metric_details,
            summary=summary,
        )

    def _entity_name(self, column_name: str) -> str:
        normalized = column_name.lower()
        if "dealer" in normalized:
            return "Dealer"
        if "region" in normalized:
            return "Region"
        if "store" in normalized or "location" in normalized:
            return "Location"
        if "employee" in normalized or "staff" in normalized:
            return "Staff"
        return self._pretty(column_name)

    def _pretty(self, value: str) -> str:
        value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
        return value.replace("_", " ").strip().title()
