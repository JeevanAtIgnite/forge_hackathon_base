"""Detect quality issues that affect trustworthy workbook reasoning."""

from __future__ import annotations

import math

import pandas as pd

from data_quality.models import DataQualityIssue, DataQualityReport, TableQualityReport
from schema_builder.models import WorkbookSchema


class DataQualityEngine:
    """Run deterministic quality checks over parsed workbook tables."""

    def analyze(
        self,
        dataframes: dict[str, pd.DataFrame],
        schema: WorkbookSchema,
    ) -> DataQualityReport:
        table_reports: list[TableQualityReport] = []
        issues: list[DataQualityIssue] = []

        for table in schema.tables:
            df = dataframes.get(table.table_name, pd.DataFrame())
            table_issues: list[DataQualityIssue] = []

            for column in table.columns:
                if column.name not in df.columns:
                    continue

                series = df[column.name]
                non_null = series.dropna()
                missing_ratio = 1.0 - (len(non_null) / max(len(series), 1))
                if missing_ratio >= 0.1:
                    severity = "high" if missing_ratio >= 0.3 else "medium"
                    table_issues.append(
                        DataQualityIssue(
                            table_name=table.table_name,
                            column_name=column.name,
                            issue_type="missing_values",
                            severity=severity,
                            message=f"{column.name} has {missing_ratio:.0%} missing values.",
                        )
                    )

                if column.data_type in {"int", "float"}:
                    table_issues.extend(self._numeric_issues(table.table_name, column.name, series))

            table_reports.append(
                TableQualityReport(
                    table_name=table.table_name,
                    row_count=len(df),
                    issues=table_issues,
                )
            )
            issues.extend(table_issues)

        warnings = [issue.message for issue in issues[:8]]
        summary = (
            "No major data quality issues detected."
            if not issues
            else f"Detected {len(issues)} quality issues across {len(table_reports)} tables."
        )

        return DataQualityReport(
            summary=summary,
            warnings=warnings,
            issues=issues,
            table_reports=table_reports,
        )

    def _numeric_issues(self, table_name: str, column_name: str, series: pd.Series) -> list[DataQualityIssue]:
        issues: list[DataQualityIssue] = []
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if numeric.empty:
            return issues

        lowered = column_name.lower()
        expects_positive = any(
            token in lowered
            for token in ("lead", "appoint", "revenue", "sales", "staff", "count", "cost", "rate", "conversion")
        )
        if expects_positive and (numeric < 0).any():
            issues.append(
                DataQualityIssue(
                    table_name=table_name,
                    column_name=column_name,
                    issue_type="invalid_negative",
                    severity="high",
                    message=f"{column_name} contains negative values that are unlikely to be valid.",
                )
            )

        if any(token in lowered for token in ("rate", "conversion", "ratio")) and (numeric > 1.0).mean() > 0.5:
            issues.append(
                DataQualityIssue(
                    table_name=table_name,
                    column_name=column_name,
                    issue_type="range_violation",
                    severity="medium",
                    message=f"{column_name} looks like a rate but often exceeds 1.0.",
                )
            )

        if len(numeric) >= 5:
            q1 = numeric.quantile(0.25)
            q3 = numeric.quantile(0.75)
            iqr = q3 - q1
            if not math.isclose(iqr, 0.0):
                lower_bound = q1 - (1.5 * iqr)
                upper_bound = q3 + (1.5 * iqr)
                outlier_count = int(((numeric < lower_bound) | (numeric > upper_bound)).sum())
                if outlier_count:
                    issues.append(
                        DataQualityIssue(
                            table_name=table_name,
                            column_name=column_name,
                            issue_type="outlier",
                            severity="low",
                            message=f"{column_name} has {outlier_count} outlier values outside the IQR range.",
                        )
                    )

        return issues
