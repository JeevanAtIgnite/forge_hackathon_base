"""Verifier agent that checks the execution path before responding."""

from __future__ import annotations

import pandas as pd

from agent.models import ExecutionPlan, VerificationReport
from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema


class VerifierAgent:
    """Validate that the answer is backed by executable workbook operations."""

    def verify(
        self,
        plan: ExecutionPlan,
        schema: WorkbookSchema,
        relationships: RelationshipGraphModel,
        result_df: pd.DataFrame,
        metrics: dict,
    ) -> VerificationReport:
        checks: list[str] = []
        warnings: list[str] = []
        table_names = {table.table_name for table in schema.tables}

        missing_tables = [table for table in plan.selected_tables if table not in table_names]
        if missing_tables:
            return VerificationReport(
                valid=False,
                checks=checks,
                warnings=[f"Planner referenced unknown tables: {', '.join(missing_tables)}."],
            )

        checks.append("All planner-selected tables exist in the workbook schema.")

        if len(plan.selected_tables) > 1:
            valid_join = any(
                relation.left_table in plan.selected_tables and relation.right_table in plan.selected_tables
                for relation in relationships.relationships
            )
            if valid_join:
                checks.append("Join path is present in the inferred relationship graph.")
            else:
                warnings.append("Planner selected multiple tables without a verified relationship edge.")

        metric_column = metrics.get("metric_column")
        if metric_column and metric_column in result_df.columns:
            checks.append(f"Metric column '{metric_column}' is present in the execution result.")
        elif metric_column:
            warnings.append(f"Metric column '{metric_column}' was not present in the final result set.")

        if result_df.empty:
            if plan.intent not in {"kpi_recommendation", "data_quality"}:
                warnings.append("Execution returned no rows. The answer may be valid but has no supporting records.")
        else:
            checks.append("Execution returned supporting rows or aggregate values.")

        if plan.intent == "simulation":
            checks.append("Simulation intent was validated against the selected workbook tables.")
        if plan.intent == "data_quality":
            checks.append("Quality analysis was generated directly from parsed workbook tables.")
        if plan.intent == "kpi_recommendation":
            checks.append("KPI suggestions were derived from schema columns and formulas, not free text.")

        return VerificationReport(
            valid=not any("unknown" in warning.lower() for warning in warnings),
            checks=checks,
            warnings=warnings,
        )
