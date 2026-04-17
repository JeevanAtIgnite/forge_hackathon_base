"""Excel-first workbook loading and lightweight metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass
class WorkbookContext:
    """Workbook data loaded into pandas tables plus demo metadata."""

    file_name: str
    tables: dict[str, pd.DataFrame]
    manifest: dict[str, Any]
    semantic_schema: dict[str, Any]
    enrichment: dict[str, Any]
    suggested_questions: list[str]
    workbook_purpose: str


class WorkbookLoader:
    """Load Excel into pandas tables and derive non-blocking metadata."""

    def load(self, file_path: str) -> WorkbookContext:
        path = Path(file_path)
        excel = pd.ExcelFile(path)
        tables: dict[str, pd.DataFrame] = {}
        sheet_titles: dict[str, list[str]] = {}

        for sheet_name in excel.sheet_names:
            raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
            header_row, titles = self._detect_header_row(raw)
            if header_row > 0:
                df = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
            else:
                df = pd.read_excel(path, sheet_name=sheet_name)
            df = self._clean_dataframe(df)
            if not df.empty:
                tables[sheet_name] = df
                if titles:
                    sheet_titles[sheet_name] = titles

        self._sheet_titles = sheet_titles
        manifest = self._build_manifest(path.name, tables)
        semantic_schema = self._build_semantic_schema(path.stem, tables)
        enrichment = self._build_enrichment(tables)
        suggested_questions = self._suggest_questions(tables)
        workbook_purpose = self._workbook_purpose(tables)

        return WorkbookContext(
            file_name=path.name,
            tables=tables,
            manifest=manifest,
            semantic_schema=semantic_schema,
            enrichment=enrichment,
            suggested_questions=suggested_questions,
            workbook_purpose=workbook_purpose,
        )

    def _detect_header_row(self, raw: pd.DataFrame) -> tuple[int, list[str]]:
        """Pick the best header row in the first few rows. Rows above are treated as title/notes."""
        max_scan = min(6, len(raw))
        best_idx = 0
        best_score = -1.0

        for idx in range(max_scan):
            row = raw.iloc[idx]
            non_null = row.dropna()
            if len(non_null) < 2:
                continue
            string_cells = sum(
                1 for value in non_null
                if isinstance(value, str) and len(str(value).strip()) > 0 and not self._looks_like_number(str(value))
            )
            string_ratio = string_cells / len(non_null)
            if string_ratio < 0.6:
                continue
            unique_ratio = len(set(str(value).strip().lower() for value in non_null)) / len(non_null)
            density = len(non_null) / max(len(row), 1)

            next_row_numeric = 0.0
            if idx + 1 < len(raw):
                next_row = raw.iloc[idx + 1].dropna()
                if len(next_row) > 0:
                    numeric_count = sum(1 for value in next_row if self._looks_like_number(str(value)))
                    next_row_numeric = numeric_count / len(next_row)

            score = string_ratio * 2.0 + unique_ratio * 2.0 + density * 1.5 + next_row_numeric * 1.0
            if score > best_score:
                best_score = score
                best_idx = idx

        titles: list[str] = []
        for i in range(best_idx):
            row = raw.iloc[i].dropna()
            if len(row) == 0:
                continue
            text = " · ".join(str(value).strip() for value in row if str(value).strip())
            if text:
                titles.append(text)
        return best_idx, titles

    @staticmethod
    def _looks_like_number(value: str) -> bool:
        cleaned = value.strip().replace(",", "").replace("$", "").replace("%", "")
        try:
            float(cleaned)
            return True
        except ValueError:
            return False

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        cleaned = df.copy()
        cleaned = cleaned.dropna(axis=0, how="all").dropna(axis=1, how="all")
        # Drop any leftover "Unnamed: N" pandas-generated columns
        drop_columns = [column for column in cleaned.columns if str(column).strip().lower().startswith("unnamed")]
        if drop_columns:
            cleaned = cleaned.drop(columns=drop_columns)
        cleaned.columns = [str(column).strip() for column in cleaned.columns]
        return cleaned.reset_index(drop=True)

    def _build_manifest(self, file_name: str, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        table_entries: list[dict[str, Any]] = []
        formula_count = 0

        for sheet_name, df in tables.items():
            inferred_formulas = [
                column for column in df.columns if any(token in column.lower() for token in ("rate", "margin", "ratio", "percent", "%"))
            ]
            formula_count += len(inferred_formulas)
            table_entries.append(
                {
                    "name": sheet_name,
                    "sheet_name": sheet_name,
                    "row_count": int(len(df)),
                    "column_count": int(len(df.columns)),
                    "columns": [{"name": str(column), "sample_values": self._sample(df[column])} for column in df.columns],
                    "formula_count": len(inferred_formulas),
                }
            )

        return {
            "file_name": file_name,
            "sheet_count": len(tables),
            "sheet_names": list(tables.keys()),
            "table_count": len(tables),
            "relationship_count": 0,
            "formula_column_count": formula_count,
            "tables": table_entries,
            "notes": [],
        }

    def _build_semantic_schema(self, workbook_title: str, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        table_views: list[dict[str, Any]] = []

        for sheet_name, df in tables.items():
            table_views.append(
                {
                    "table_name": sheet_name,
                    "description": self._describe_table(sheet_name, df),
                    "row_count": int(len(df)),
                    "primary_key": self._primary_key(df),
                    "columns": [
                        {
                            "name": str(column),
                            "data_type": self._data_type(df[column]),
                            "semantic_role": self._role(str(column), df[column]),
                            "description": f"{column} from {sheet_name}",
                        }
                        for column in df.columns
                    ],
                    "derived_columns": [
                        {"column_name": str(column), "logic": f"{column} behaves like a derived business metric."}
                        for column in df.columns
                        if any(token in str(column).lower() for token in ("rate", "margin", "ratio", "percent", "%"))
                    ],
                }
            )

        return {
            "workbook_title": workbook_title.replace("_", " ").replace("-", " ").title(),
            "tables": table_views,
        }

    def _build_enrichment(self, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        all_entities: set[str] = set()
        all_metrics: set[str] = set()
        quality_warnings: list[dict[str, Any]] = []
        kpis: list[dict[str, Any]] = []

        for sheet_name, df in tables.items():
            object_columns = [column for column in df.columns if not pd.api.types.is_numeric_dtype(df[column])]
            numeric_columns = [column for column in df.columns if pd.api.types.is_numeric_dtype(df[column])]

            for column in object_columns[:4]:
                if any(token in str(column).lower() for token in ("dealer", "region", "stream", "product", "category", "segment")):
                    all_entities.add(str(column))

            for column in numeric_columns[:6]:
                all_metrics.add(str(column))
                if df[column].isna().sum() > 0:
                    quality_warnings.append(
                        {
                            "table_name": sheet_name,
                            "column_name": str(column),
                            "severity": "medium",
                            "message": f"{column} has missing values.",
                        }
                    )

            if len(numeric_columns) >= 2:
                kpis.append(
                    {
                        "name": f"{numeric_columns[0]} per {numeric_columns[1]}",
                        "formula": f"{numeric_columns[0]} / {numeric_columns[1]}",
                        "rationale": "Simple efficiency KPI inferred from available numeric columns.",
                        "category": "efficiency",
                    }
                )

        return {
            "semantic_model": {
                "summary": f"The workbook contains {len(tables)} Excel tables that can be queried directly with pandas.",
                "entities": sorted(all_entities),
                "metrics": sorted(all_metrics),
                "derived_metrics": [metric for metric in sorted(all_metrics) if any(token in metric.lower() for token in ("rate", "margin", "ratio"))],
            },
            "data_quality": {
                "summary": "Basic quality checks profile missing values and obvious numeric anomalies.",
                "issues": quality_warnings,
            },
            "kpi_recommendations": kpis[:6],
            "table_overview": [
                {"table_name": sheet_name, "columns": [str(column) for column in df.columns], "row_count": int(len(df))}
                for sheet_name, df in tables.items()
            ],
            "demo_scenarios": [
                "Which revenue stream contributes the most?",
                "Why is Used Vehicle Sales underperforming?",
                "What if Used Vehicle Sales increase by 15%?",
            ],
        }

    def _suggest_questions(self, tables: dict[str, pd.DataFrame]) -> list[str]:
        """Generate Query / Diagnostic / Simulation prompts grounded in real columns."""
        query_prompts: list[str] = []
        diagnostic_prompts: list[str] = []
        simulation_prompts: list[str] = []

        for sheet_name, df in tables.items():
            metric = self._pick_business_metric(df)
            dimension, top_value = self._pick_dimension_with_value(df)

            if dimension and metric:
                query_prompts.append(f"Which {dimension.lower()} contributes the most {metric.lower()}?")
            elif metric:
                query_prompts.append(f"What is the total {metric.lower()} in {sheet_name}?")

            if top_value and metric:
                diagnostic_prompts.append(f"Why is {top_value} underperforming on {metric.lower()}?")
            elif dimension and metric:
                diagnostic_prompts.append(f"Which {dimension.lower()} is driving variance in {metric.lower()}?")

            if top_value and metric:
                simulation_prompts.append(f"What if {top_value} {metric.lower()} increases by 15%?")
            elif metric:
                simulation_prompts.append(f"What if {metric.lower()} grows by 10%?")

        ordered: list[str] = []
        for bucket in (query_prompts, diagnostic_prompts, simulation_prompts):
            for prompt in bucket:
                if prompt not in ordered:
                    ordered.append(prompt)
        return ordered[:6]

    def _pick_business_metric(self, df: pd.DataFrame) -> str | None:
        preferred = ("revenue", "sales", "profit", "margin", "gross", "net", "total", "amount", "income", "value", "cost", "price")
        candidates: list[str] = []
        for column in df.columns:
            name = str(column)
            lowered = name.lower()
            if pd.api.types.is_datetime64_any_dtype(df[column]):
                continue
            if any(token in lowered for token in ("date", "year", "quarter", "month")):
                continue
            if "#" in lowered or lowered.endswith("id") or "vin" in lowered:
                continue
            if pd.to_numeric(df[column], errors="coerce").notna().mean() > 0.5:
                candidates.append(name)
        for token in preferred:
            for name in candidates:
                if token in name.lower():
                    return name
        return candidates[0] if candidates else None

    def _pick_dimension_with_value(self, df: pd.DataFrame) -> tuple[str | None, str | None]:
        preferred_tokens = ("type", "category", "group", "segment", "class", "kind", "status", "name", "source", "line item", "channel")
        object_columns = [str(column) for column in df.columns if not pd.api.types.is_numeric_dtype(df[column])]
        ranked: list[str] = []
        for token in preferred_tokens:
            for name in object_columns:
                if token in name.lower() and name not in ranked:
                    ranked.append(name)
        for name in object_columns:
            if name not in ranked and df[name].nunique(dropna=True) <= max(2, len(df) // 2):
                ranked.append(name)

        for name in ranked:
            values = [str(value).strip() for value in df[name].dropna().head(50).tolist() if str(value).strip()]
            for value in values:
                if 3 <= len(value) <= 36 and not value.replace(".", "", 1).isdigit():
                    return name, value
            if values:
                return name, None
        return None, None

    def _workbook_purpose(self, tables: dict[str, pd.DataFrame]) -> str:
        sheet_names = ", ".join(list(tables.keys())[:4]) if tables else "no sheets"
        return f"This workbook is loaded as pandas tables ({sheet_names}) for direct execution-backed analytics."

    def _sample(self, series: pd.Series) -> list[Any]:
        values = [value for value in series.head(3).tolist() if value is not None and str(value) != "nan"]
        return values

    def _data_type(self, series: pd.Series) -> str:
        if pd.api.types.is_integer_dtype(series):
            return "int"
        if pd.api.types.is_float_dtype(series):
            return "float"
        if pd.api.types.is_datetime64_any_dtype(series):
            return "date"
        return "string"

    def _role(self, column_name: str, series: pd.Series) -> str:
        lowered = column_name.lower()
        if any(token in lowered for token in ("id", "key", "#", "number")):
            return "identifier"
        if pd.api.types.is_numeric_dtype(series):
            return "metric"
        if any(token in lowered for token in ("type", "category", "name", "group", "class", "kind", "status", "segment")):
            return "dimension"
        return "attribute"

    def _primary_key(self, df: pd.DataFrame) -> str | None:
        for column in df.columns:
            non_null = df[column].dropna()
            if len(non_null) == 0:
                continue
            if non_null.nunique() == len(non_null):
                return str(column)
        return None

    def _describe_table(self, sheet_name: str, df: pd.DataFrame) -> str:
        profile = self._table_profile(sheet_name, df)
        pieces: list[str] = [profile["purpose"]]
        if profile.get("grain"):
            pieces.append(f"Grain: {profile['grain']}.")
        if profile.get("metrics"):
            top_metrics = ", ".join(profile["metrics"][:4])
            pieces.append(f"Key metrics: {top_metrics}.")
        if profile.get("dimensions"):
            top_dims = ", ".join(profile["dimensions"][:3])
            pieces.append(f"Dimensions: {top_dims}.")
        if profile.get("primary_key"):
            pieces.append(f"Primary key: {profile['primary_key']}.")
        return " ".join(pieces)

    def _table_profile(self, sheet_name: str, df: pd.DataFrame) -> dict[str, Any]:
        columns = [str(column) for column in df.columns]
        lowered_cols = [column.lower() for column in columns]
        numeric_cols = [column for column in columns if pd.api.types.is_numeric_dtype(df[column])]
        text_cols = [column for column in columns if not pd.api.types.is_numeric_dtype(df[column])]
        date_cols = [column for column in columns if pd.api.types.is_datetime64_any_dtype(df[column])]

        metrics = [
            column for column in numeric_cols
            if not any(token in column.lower() for token in ("id", "#", "key", "year", "quarter", "month"))
        ]

        dimensions: list[str] = []
        for column in text_cols:
            lowered = column.lower()
            if any(token in lowered for token in ("type", "name", "category", "group", "class", "kind", "status", "segment", "source")):
                dimensions.append(column)
        if not dimensions and text_cols:
            dimensions = text_cols[:2]

        primary_key = self._primary_key(df)

        entity_label = primary_key.rstrip("#") if primary_key and "#" in primary_key else (primary_key or (dimensions[0] if dimensions else "record"))

        shape = df.shape
        looks_like_period_grid = (
            len(text_cols) == 1
            and len(numeric_cols) >= 3
            and any(month in " ".join(lowered_cols) for month in ["jan", "feb", "q1", "q2"])
        )
        looks_like_parameter_table = (
            shape[0] <= 30
            and any("assumption" in column.lower() or "parameter" in column.lower() for column in columns)
        )
        looks_like_transaction_log = (
            shape[0] >= 20
            and (any("date" in column.lower() for column in columns) or bool(date_cols))
            and len(numeric_cols) >= 2
        )

        if looks_like_period_grid:
            purpose = f"{sheet_name} is a period-over-period financial grid: each row is a {text_cols[0].lower()}, each column is a time bucket or total."
            grain = f"one row per {text_cols[0].lower()}"
        elif looks_like_parameter_table:
            purpose = f"{sheet_name} holds modelling assumptions and parameters used by downstream calculations."
            grain = "one row per assumption"
        elif looks_like_transaction_log:
            purpose = f"{sheet_name} is a transaction-level log with {shape[0]} records. Each row is an individual transaction."
            grain = f"one row per {entity_label}"
        else:
            purpose = f"{sheet_name} is a {shape[0]}-row reference table."
            grain = f"one row per {entity_label}"

        return {
            "purpose": purpose,
            "grain": grain,
            "metrics": metrics,
            "dimensions": dimensions,
            "primary_key": primary_key,
            "numeric_columns": numeric_cols,
            "text_columns": text_cols,
        }
