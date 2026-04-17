"""Heuristic KPI suggestions derived from workbook schema and relationships."""

from __future__ import annotations

from kpi_engine.models import KPIRecommendation
from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema


class KPIRecommendationEngine:
    """Suggest practical KPIs that can be computed from the workbook schema."""

    def recommend(
        self,
        schema: WorkbookSchema,
        relationships: RelationshipGraphModel,
    ) -> list[KPIRecommendation]:
        recommendations: list[KPIRecommendation] = []

        for table in schema.tables:
            column_names = {column.name.lower(): column.name for column in table.columns}
            table_name = table.table_name

            leads = self._find(column_names, ["leads", "lead_count"])
            appointments = self._find(column_names, ["appointments", "appts", "appointment_count"])
            staff = self._find(column_names, ["staffcount", "staff_count", "staffing", "headcount", "employee_count"])
            revenue = self._find(column_names, ["revenue", "sales", "gross_profit"])

            if leads and appointments:
                recommendations.append(
                    KPIRecommendation(
                        name="Conversion Rate",
                        formula=f"{appointments} / {leads}",
                        rationale="Tracks how effectively leads convert into appointments.",
                        tables=[table_name],
                        source_columns=[appointments, leads],
                        category="conversion",
                    )
                )

            if leads and staff:
                recommendations.append(
                    KPIRecommendation(
                        name="Leads Per Staff",
                        formula=f"{leads} / {staff}",
                        rationale="Measures workload and staffing efficiency per business entity.",
                        tables=[table_name],
                        source_columns=[leads, staff],
                        category="productivity",
                    )
                )

            if revenue and staff:
                recommendations.append(
                    KPIRecommendation(
                        name="Revenue Per Staff",
                        formula=f"{revenue} / {staff}",
                        rationale="Measures productivity and staffing ROI.",
                        tables=[table_name],
                        source_columns=[revenue, staff],
                        category="productivity",
                    )
                )

        for relationship in relationships.relationships:
            recommendations.append(
                KPIRecommendation(
                    name=f"Joined Performance On {relationship.join_key}",
                    formula=f"JOIN {relationship.left_table} TO {relationship.right_table} ON {relationship.join_key}",
                    rationale="A join KPI combines operational and contextual tables for richer entity performance views.",
                    tables=[relationship.left_table, relationship.right_table],
                    source_columns=[relationship.left_column, relationship.right_column],
                    category="joined_analysis",
                )
            )

        deduped: dict[tuple[str, str], KPIRecommendation] = {}
        for item in recommendations:
            deduped[(item.name, item.formula)] = item
        return list(deduped.values())[:10]

    def _find(self, columns: dict[str, str], candidates: list[str]) -> str | None:
        normalized_columns = {key.replace("_", ""): value for key, value in columns.items()}
        for candidate in candidates:
            if candidate in normalized_columns:
                return normalized_columns[candidate]
        for key, value in columns.items():
            for candidate in candidates:
                if candidate.replace("_", "") in key.replace("_", ""):
                    return value
        return None
