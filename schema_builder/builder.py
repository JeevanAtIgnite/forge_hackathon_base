"""Infer schema, types, and natural-language summaries for parsed tables."""

from __future__ import annotations

from datetime import date, datetime
from statistics import mean
from typing import Any

import pandas as pd

from excel_parser.models import Table, WorkbookTables
from formula_engine.models import FormulaCatalog
from schema_builder.models import ColumnSchema, TableSchema, WorkbookSchema


class SchemaBuilder:
    """Build structured table schemas from parsed workbook tables."""

    def build(self, workbook: WorkbookTables, formulas: FormulaCatalog) -> WorkbookSchema:
        derived_by_table: dict[str, list] = {}
        for item in formulas.derived_columns:
            derived_by_table.setdefault(item.table_name, []).append(item)

        table_schemas = [self._build_table_schema(table, derived_by_table.get(table.name, [])) for table in workbook.tables]
        overview = self._build_overview(workbook.workbook_title, table_schemas)
        domain = self._infer_domain(table_schemas)
        suggested_questions = self._suggest_questions(table_schemas)

        return WorkbookSchema(
            workbook_title=workbook.workbook_title,
            overview=overview,
            domain=domain,
            tables=table_schemas,
            table_summaries=[table.description for table in table_schemas],
            suggested_questions=suggested_questions,
        )

    def _build_table_schema(self, table: Table, derived_columns: list) -> TableSchema:
        df = pd.DataFrame(table.rows)
        columns = [self._build_column_schema(df, column.name) for column in table.columns]
        primary_key = self._infer_primary_key(df)
        description = self._describe_table(table, columns, derived_columns)

        return TableSchema(
            table_name=table.name,
            description=description,
            columns=columns,
            primary_key=primary_key,
            sample_rows=df.head(3).to_dict(orient="records"),
            row_count=len(df),
            sheet_name=table.sheet_name,
            derived_columns=derived_columns,
        )

    def _build_column_schema(self, df: pd.DataFrame, column_name: str) -> ColumnSchema:
        series = df[column_name]
        sample_values = [value for value in series.head(3).tolist() if value not in (None, "")]
        unique_ratio = 0.0
        if len(series) > 0:
            unique_ratio = float(series.dropna().nunique() / max(len(series.dropna()), 1))

        data_type = self._infer_type(series.tolist())
        semantic_role = self._infer_semantic_role(column_name, data_type)
        description = self._describe_column(column_name, semantic_role, data_type)

        return ColumnSchema(
            name=column_name,
            data_type=data_type,
            description=description,
            semantic_role=semantic_role,
            nullable=series.isna().any(),
            unique_ratio=round(unique_ratio, 3),
            sample_values=sample_values,
            is_primary_candidate=bool(unique_ratio > 0.95 and semantic_role == "identifier"),
        )

    def _infer_type(self, values: list[Any]) -> str:
        non_empty = [value for value in values if value not in (None, "")]
        if not non_empty:
            return "string"

        if all(isinstance(value, bool) for value in non_empty):
            return "boolean"
        if all(isinstance(value, int) and not isinstance(value, bool) for value in non_empty):
            return "int"
        if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_empty):
            return "float"
        if all(isinstance(value, (datetime, date, pd.Timestamp)) for value in non_empty):
            return "date"

        numeric_values = pd.to_numeric(pd.Series(non_empty), errors="coerce")
        if numeric_values.notna().mean() > 0.8:
            return "float" if any(float(v) != int(v) for v in numeric_values.dropna()) else "int"

        parsed_dates = pd.to_datetime(pd.Series(non_empty), errors="coerce")
        if parsed_dates.notna().mean() > 0.8:
            return "date"

        return "string"

    def _infer_semantic_role(self, column_name: str, data_type: str) -> str:
        normalized = column_name.lower()
        if "id" in normalized or normalized.endswith("_key"):
            return "identifier"
        if any(token in normalized for token in ("date", "month", "year", "quarter")) or data_type == "date":
            return "time"
        if data_type in {"int", "float"}:
            return "metric"
        if any(token in normalized for token in ("name", "type", "category", "dealer", "region", "store", "location")):
            return "dimension"
        return "attribute"

    def _describe_column(self, column_name: str, semantic_role: str, data_type: str) -> str:
        pretty = column_name.replace("_", " ")
        return f"{pretty.title()} is a {semantic_role} column stored as {data_type}."

    def _infer_primary_key(self, df: pd.DataFrame) -> str | None:
        if df.empty:
            return None

        candidates: list[tuple[str, float]] = []
        for column in df.columns:
            non_null = df[column].dropna()
            if non_null.empty:
                continue
            uniqueness = float(non_null.nunique() / len(non_null))
            score = uniqueness
            normalized = column.lower()
            if "id" in normalized:
                score += 0.3
            if normalized.endswith("_id"):
                score += 0.3
            candidates.append((column, score))

        if not candidates:
            return None

        candidates.sort(key=lambda item: item[1], reverse=True)
        best_column, score = candidates[0]
        return best_column if score >= 0.95 else None

    def _describe_table(self, table: Table, columns: list[ColumnSchema], derived_columns: list) -> str:
        metric_columns = [column.name for column in columns if column.semantic_role == "metric"][:3]
        dimension_columns = [column.name for column in columns if column.semantic_role in {"dimension", "identifier"}][:3]
        derived_text = ""
        if derived_columns:
            derived_text = f" Derived metrics include {', '.join(item.column_name for item in derived_columns[:3])}."

        subject = table.name.replace("_", " ")
        dimensions = ", ".join(col.replace("_", " ") for col in dimension_columns) or "business entities"
        metrics = ", ".join(col.replace("_", " ") for col in metric_columns) or "operational values"
        return (
            f"{subject.title()} contains {table.row_count} rows from sheet {table.sheet_name} "
            f"covering {dimensions} and measures such as {metrics}.{derived_text}"
        )

    def _build_overview(self, workbook_title: str, tables: list[TableSchema]) -> str:
        if not tables:
            return f"{workbook_title} does not contain any confidently detected logical tables."

        subjects = ", ".join(table.table_name.replace("_", " ") for table in tables[:4])
        return (
            f"{workbook_title} is organized into {len(tables)} logical tables. "
            f"The workbook captures structured entities such as {subjects}, "
            "with enough schema and formula context for execution-backed reasoning."
        )

    def _infer_domain(self, tables: list[TableSchema]) -> str:
        text = " ".join(
            " ".join(column.name for column in table.columns).lower()
            for table in tables
        )
        if any(token in text for token in ("lead", "appointment", "dealer", "sales", "conversion")):
            return "sales_operations"
        if any(token in text for token in ("revenue", "ebitda", "expense", "margin", "cash")):
            return "finance"
        if any(token in text for token in ("staff", "employee", "headcount", "labor")):
            return "staffing"
        return "general_operations"

    def _suggest_questions(self, tables: list[TableSchema]) -> list[str]:
        suggestions: list[str] = []
        for table in tables[:3]:
            dimensions = [col.name for col in table.columns if col.semantic_role in {"identifier", "dimension"}]
            metrics = [col.name for col in table.columns if col.semantic_role == "metric"]
            derived = [item.column_name for item in table.derived_columns]

            if dimensions and metrics:
                suggestions.append(f"Which {dimensions[0].replace('_', ' ')} has the highest {metrics[0].replace('_', ' ')}?")
            if metrics:
                suggestions.append(f"What is the average {metrics[0].replace('_', ' ')} in {table.table_name.replace('_', ' ')}?")
            if derived:
                suggestions.append(f"Which rows in {table.table_name.replace('_', ' ')} are classified by {derived[0].replace('_', ' ')}?")
            if dimensions:
                suggestions.append(f"Why is {dimensions[0].replace('_', ' ')} performance underperforming?")
            if any("staff" in column.name.lower() for column in table.columns):
                suggestions.append("What if staffing increases by 20%?")

        # Preserve order while deduplicating.
        suggestions.extend(
            [
                "What KPIs should I track?",
                "Are there issues in this dataset?",
            ]
        )
        return list(dict.fromkeys(suggestions))[:12]
