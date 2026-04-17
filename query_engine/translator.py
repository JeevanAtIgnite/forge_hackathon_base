"""Translate queries and plans into transparent executable descriptions."""

from __future__ import annotations

from agent.models import ExecutionPlan
from query_engine.models import QueryTranslation


class QueryTranslator:
    """Render a deterministic query plan as pandas and SQL-like logic."""

    def translate(self, plan: ExecutionPlan, metric_column: str | None = None, grouping_column: str | None = None) -> QueryTranslation:
        operations = [step.action for step in plan.steps]
        selected_tables = plan.selected_tables
        notes: list[str] = []

        if len(selected_tables) > 1:
            join_text = f"join {selected_tables[0]} with {selected_tables[1]}"
            notes.append(f"Planner uses the inferred relationship graph to {join_text}.")
        if metric_column:
            notes.append(f"Primary metric: {metric_column}.")
        if grouping_column:
            notes.append(f"Primary entity/grouping: {grouping_column}.")

        pandas_logic = self._pandas_logic(plan.intent, selected_tables, metric_column, grouping_column)
        sql_like = self._sql_logic(plan.intent, selected_tables, metric_column, grouping_column)

        return QueryTranslation(
            query=plan.query,
            intent=plan.intent,
            operations=operations,
            selected_tables=selected_tables,
            pandas_logic=pandas_logic,
            sql_like=sql_like,
            notes=notes,
        )

    def _pandas_logic(self, intent: str, tables: list[str], metric_column: str | None, grouping_column: str | None) -> str:
        if intent == "simulation":
            return "df[target_column] = df[target_column] * scenario_multiplier"
        if intent == "data_quality":
            return "for each table: profile missing values, invalid ranges, and numeric outliers"
        if intent == "kpi_recommendation":
            return "inspect schema columns and formula dependencies to suggest KPI expressions"
        if intent == "insight":
            return (
                "working_df = joined_or_selected_df\n"
                f"compare {metric_column or 'metric'} by {grouping_column or 'entity'} against peer averages and rankings"
            )
        if intent == "ranking":
            return f"working_df.sort_values('{metric_column}', ascending=False).head(5)"
        if intent == "aggregation":
            return f"pd.to_numeric(working_df['{metric_column}'], errors='coerce').mean()"
        if intent == "classification":
            return "working_df[category_column].isin(['High', 'Low'])"
        return "working_df.head(10)"

    def _sql_logic(self, intent: str, tables: list[str], metric_column: str | None, grouping_column: str | None) -> str:
        from_clause = tables[0] if tables else "workbook_table"
        if len(tables) > 1:
            from_clause = f"{tables[0]} JOIN {tables[1]} ON inferred_relationship"

        if intent == "simulation":
            return f"SELECT *, {metric_column or 'target_column'} * scenario_multiplier AS simulated_value FROM {from_clause};"
        if intent == "data_quality":
            return f"PROFILE TABLES IN {', '.join(tables) or 'workbook'} FOR missing_values, invalid_ranges, outliers;"
        if intent == "kpi_recommendation":
            return f"ANALYZE SCHEMA OF {', '.join(tables) or 'workbook'} TO SUGGEST KPI DEFINITIONS;"
        if intent == "insight":
            return (
                f"SELECT {grouping_column or 'entity'}, {metric_column or 'metric'} "
                f"FROM {from_clause} ORDER BY {metric_column or 'metric'} DESC;"
            )
        if intent == "ranking":
            return (
                f"SELECT {grouping_column or '*'}, {metric_column or 'metric'} "
                f"FROM {from_clause} ORDER BY {metric_column or 'metric'} DESC LIMIT 5;"
            )
        if intent == "aggregation":
            return f"SELECT AVG({metric_column or 'metric'}) AS average_value FROM {from_clause};"
        if intent == "classification":
            return f"SELECT * FROM {from_clause} WHERE category_column IN ('High', 'Low');"
        return f"SELECT * FROM {from_clause} LIMIT 10;"
