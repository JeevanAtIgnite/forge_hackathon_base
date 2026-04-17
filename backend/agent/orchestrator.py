"""Single clean execution pipeline for agent collaboration and pandas execution."""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.agent.data_agent import DataAgent
from backend.agent.insight_engine import InsightEngine
from backend.agent.planner import Planner
from backend.agent.simulation_engine import SimulationEngine
from backend.agent.validator import Validator


class AgenticOrchestrator:
    """Planner -> Data Agent -> optional Insight/Simulation -> Validator."""

    def __init__(self) -> None:
        self.planner = Planner()
        self.data_agent = DataAgent()
        self.insight_engine = InsightEngine()
        self.simulation_engine = SimulationEngine()
        self.validator = Validator()

    def run_query(self, query: str, tables: dict[str, pd.DataFrame]) -> dict[str, Any]:
        logs: list[dict[str, str]] = []

        plan = self.planner.plan(query, tables)
        logs.append({"agent": "Planner", "message": self._log_planner(plan)})

        result = self.data_agent.execute(plan, tables)
        result["query"] = query
        result["plan"] = plan
        logs.append({"agent": "Data Agent", "message": self._log_data_agent(plan, result)})

        needs_insight = "why" in query.lower() or "underperform" in query.lower()
        if needs_insight:
            result = self.insight_engine.analyze(result)
            logs.append({"agent": "Insight Agent", "message": self._log_insight(result)})

        needs_simulation = "what if" in query.lower()
        if needs_simulation:
            result = self.simulation_engine.simulate(result, tables)
            logs.append({"agent": "Simulation Agent", "message": self._log_simulation(result)})

        validated = self.validator.validate(result)
        logs.append({"agent": "Validator", "message": self._log_validator(validated)})

        narrative = self._build_narrative(query, plan, validated, needs_insight, needs_simulation)

        return {
            "answer": validated.get("answer", "No answer available."),
            "status": "warning" if validated.get("warnings") else "success",
            "agent_logs": logs,
            "warnings": validated.get("warnings", []),
            "selected_tables": plan.get("selected_tables", []),
            "query_logic": {
                "pandas": validated.get("pandas_logic", ""),
                "sql_like": validated.get("sql_like", ""),
            },
            "result_table": validated.get("dataframe").head(10).replace({None: None}).to_dict(orient="records"),
            "insight_card": validated.get("insight_card"),
            "simulation": validated.get("simulation"),
            "reasoning": {
                "intent": plan.get("intent"),
                "metric_column": result.get("metric_column"),
                "dimension_column": result.get("dimension_column"),
                "aggregation_op": plan.get("aggregation_op"),
                "target_entity": plan.get("target_entity"),
                "selected_tables": plan.get("selected_tables", []),
                "row_count": int(len(validated.get("dataframe", pd.DataFrame()))),
                "narrative": narrative,
            },
        }

    # -------------------- log helpers --------------------

    def _log_planner(self, plan: dict[str, Any]) -> str:
        intent = plan.get("intent", "lookup")
        tables = plan.get("selected_tables") or []
        table_label = tables[0] if tables else "the workbook"
        intent_desc = {
            "ranking": "a ranking question",
            "aggregation": "an aggregation",
            "insight": "a diagnostic explanation",
            "simulation": "a what-if scenario",
            "lookup": "a lookup",
        }.get(intent, intent)
        target = plan.get("target_entity")
        target_clause = f" focused on {target}" if target else ""
        return f"Classified as {intent_desc} against {table_label}{target_clause}."

    def _log_data_agent(self, plan: dict[str, Any], result: dict[str, Any]) -> str:
        tables = plan.get("selected_tables") or []
        table_label = tables[0] if tables else "the table"
        metric = result.get("metric_column")
        dimension = result.get("dimension_column")
        op = plan.get("aggregation_op")
        intent = plan.get("intent")
        df = result.get("dataframe")
        row_count = len(df) if isinstance(df, pd.DataFrame) else 0

        if intent == "aggregation" and metric:
            op_label = {"sum": "summed", "mean": "averaged", "median": "took the median of", "count": "counted"}.get(op or "sum", "aggregated")
            return f"Loaded {table_label}, {op_label} {metric} across {row_count} records."
        if intent == "ranking" and metric and dimension:
            return f"Loaded {table_label}, grouped by {dimension} and summed {metric} into {row_count} ranked records."
        if intent == "insight" and metric and dimension:
            return f"Loaded {table_label} and compared {metric} across {dimension}."
        if intent == "simulation" and metric:
            return f"Loaded {table_label} and prepared {metric} for the scenario."
        return f"Loaded {table_label} ({row_count} rows)."

    def _log_insight(self, result: dict[str, Any]) -> str:
        card = result.get("insight_card") or {}
        return card.get("message") or "Compared the target entity to the rest of the table."

    def _log_simulation(self, result: dict[str, Any]) -> str:
        sim = result.get("simulation") or {}
        return sim.get("summary") or "Applied the scenario adjustment."

    def _log_validator(self, validated: dict[str, Any]) -> str:
        df = validated.get("dataframe")
        warnings = validated.get("warnings") or []
        row_count = len(df) if isinstance(df, pd.DataFrame) else 0
        if warnings:
            return f"Flagged {len(warnings)} warning(s). Result still returned as best-effort."
        return f"Cross-checked {row_count} returned row(s) against source data. Answer is defensible."

    # -------------------- narrative builder --------------------

    def _build_narrative(
        self,
        query: str,
        plan: dict[str, Any],
        result: dict[str, Any],
        needs_insight: bool,
        needs_simulation: bool,
    ) -> list[dict[str, str]]:
        tables = plan.get("selected_tables") or []
        table_label = tables[0] if tables else "the workbook"
        intent = plan.get("intent", "lookup")
        metric = result.get("metric_column")
        dimension = result.get("dimension_column")
        op = plan.get("aggregation_op")
        target = plan.get("target_entity")
        df = result.get("dataframe") if isinstance(result.get("dataframe"), pd.DataFrame) else pd.DataFrame()

        steps: list[dict[str, str]] = []

        # Step 1 — Understand
        intent_human = {
            "ranking": "who or what contributes the most",
            "aggregation": "a single aggregated number",
            "insight": "an explanation of performance",
            "simulation": "a what-if scenario",
            "lookup": "a quick lookup",
        }.get(intent, intent)
        understand = f'You asked: "{query.strip()}". The Planner classified this as {intent_human}.'
        if target:
            understand += f' The phrase "{target}" was identified as the specific entity to focus on.'
        steps.append({"title": "Understanding the question", "body": understand})

        # Step 2 — Table selection
        if tables:
            table_reason = self._table_selection_reason(tables, metric, dimension)
            steps.append({"title": "Choosing the right table", "body": table_reason})

        # Step 3 — Computation
        compute_body = self._compute_explanation(intent, op, metric, dimension, df, table_label, target)
        steps.append({"title": "How the answer was computed", "body": compute_body})

        # Step 4 — Optional insight / simulation
        if needs_insight and result.get("insight_card"):
            steps.append({
                "title": "Diagnostic insight",
                "body": result["insight_card"]["message"],
            })

        if needs_simulation and result.get("simulation"):
            steps.append({
                "title": "Scenario outcome",
                "body": result["simulation"]["summary"],
            })

        # Step 5 — Validation
        row_count = len(df)
        warnings = result.get("warnings") or []
        if warnings:
            validator_text = (
                f"The Validator reviewed the output and flagged {len(warnings)} point(s) for your attention. "
                "The answer is returned as best-effort — see the warnings for details."
            )
        else:
            validator_text = (
                f"The Validator cross-checked {row_count or 'the'} resulting row(s) against the source data and confirmed the numbers line up. "
                "Nothing was generated — every figure comes directly from executed pandas on the workbook."
            )
        steps.append({"title": "Validation", "body": validator_text})

        # Step 6 — Final answer echo
        steps.append({"title": "Final answer", "body": result.get("answer", "")})

        return steps

    def _table_selection_reason(self, tables: list[str], metric: str | None, dimension: str | None) -> str:
        table_label = tables[0]
        reasons: list[str] = []
        if metric:
            reasons.append(f'a numeric column "{metric}" that matches the metric you asked about')
        if dimension:
            reasons.append(f'a categorical column "{dimension}" to group by')
        if not reasons:
            reasons.append("the most column-name and value overlap with your question")
        reason_text = " and ".join(reasons)
        extra = ""
        if len(tables) > 1:
            extra = f' This query also pulled in "{tables[1]}" because they share a common column.'
        return f'The Data Agent selected "{table_label}" because it has {reason_text}.{extra}'

    def _compute_explanation(
        self,
        intent: str,
        op: str | None,
        metric: str | None,
        dimension: str | None,
        df: pd.DataFrame,
        table_label: str,
        target: str | None,
    ) -> str:
        op_word = {"sum": "Sum", "mean": "Average", "median": "Median", "count": "Count"}.get(op or "sum", "Sum")
        row_count = len(df)

        if intent == "aggregation" and metric:
            return (
                f"The agent executed on live data: it took the {op_word.lower()} of \"{metric}\" across every row in \"{table_label}\" "
                f"({row_count:,} records). No values were estimated — the result is pandas math over the actual cells."
            )

        if intent == "ranking" and metric and dimension:
            top_rows = df.head(3) if not df.empty else df
            top_text = ""
            if not top_rows.empty and dimension in top_rows.columns and metric in top_rows.columns:
                bullets = []
                for _, row in top_rows.iterrows():
                    value = row.get(metric)
                    formatted = self._format_value(metric, value)
                    bullets.append(f"• {row.get(dimension)}: {formatted}")
                top_text = "\n\n" + "\n".join(bullets)
            return (
                f"The agent grouped every row in \"{table_label}\" by \"{dimension}\" and summed \"{metric}\" for each group, "
                f"producing {row_count} ranked buckets. Results were sorted high-to-low so the leader is shown first.{top_text}"
            )

        if intent == "insight" and metric and dimension:
            focus = f' around "{target}"' if target else ""
            return (
                f"The agent compared \"{metric}\" across \"{dimension}\"{focus} to understand which values stand out from the average. "
                "The resulting delta is what the insight card reports."
            )

        if intent == "simulation" and metric:
            scope = f'"{target}"' if target else f'every row of "{metric}"'
            return (
                f"The agent copied the table, applied the percentage change to {scope}, "
                f"then summed \"{metric}\" both before and after so you can see the delta."
            )

        return f"The agent returned the first matching records from \"{table_label}\"."

    @staticmethod
    def _format_value(column: str, value: Any) -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        lowered = str(column).lower()
        is_currency = "$" in str(column) or any(token in lowered for token in ("revenue", "cost", "price", "sales", "income", "gross", "budget"))
        if is_currency:
            if abs(number) >= 1_000_000:
                return f"${number / 1_000_000:,.2f}M"
            if abs(number) >= 10_000:
                return f"${number:,.0f}"
            return f"${number:,.2f}"
        if number.is_integer() and abs(number) >= 1000:
            return f"{int(number):,}"
        return f"{number:,.2f}"
