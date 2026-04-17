"""Planner agent that converts a question into deterministic execution steps."""

from __future__ import annotations

import re

from agent.models import ExecutionPlan, ExecutionStep
from embedding_layer.index import MetadataEmbeddingIndex
from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema


class PlannerAgent:
    """Deterministically plan workbook reasoning operations."""

    def create_plan(
        self,
        query: str,
        schema: WorkbookSchema,
        relationships: RelationshipGraphModel,
        metadata_index: MetadataEmbeddingIndex,
    ) -> ExecutionPlan:
        relevant_tables = metadata_index.relevant_tables(query, top_k=3)
        if not relevant_tables and schema.tables:
            relevant_tables = [schema.tables[0].table_name]

        intent = self._intent(query)
        output_mode = self._output_mode(query)
        agents = self._agents_for_intent(intent)
        steps: list[ExecutionStep] = [
            ExecutionStep(
                step_id=1,
                action="identify_tables",
                reasoning="Select the most relevant logical tables using metadata embeddings.",
                params={"query": query, "tables": relevant_tables},
            )
        ]

        if len(relevant_tables) > 1:
            join_candidates = [
                item.model_dump(mode="json")
                for item in relationships.relationships
                if item.left_table in relevant_tables and item.right_table in relevant_tables
            ]
            if join_candidates:
                steps.append(
                    ExecutionStep(
                        step_id=len(steps) + 1,
                        action="join_tables",
                        reasoning="Connect the selected tables through an inferred relationship before computing the answer.",
                        params={"relationships": join_candidates},
                    )
                )

        steps.append(
            ExecutionStep(
                step_id=len(steps) + 1,
                action="analyze_query",
                reasoning="Map the question to filters, metrics, and ranking or aggregation intent.",
                params={"intent": intent, "query_tokens": re.findall(r"[a-z0-9_]+", query.lower())},
            )
        )

        if intent in {"ranking", "aggregation", "insight"}:
            steps.append(
                ExecutionStep(
                    step_id=len(steps) + 1,
                    action="compute_metric",
                    reasoning="Compute the requested metric using structured columns or formula-derived logic.",
                    params={"intent": intent},
                )
            )

        if intent == "classification":
            steps.append(
                ExecutionStep(
                    step_id=len(steps) + 1,
                    action="apply_formula_logic",
                    reasoning="Use derived-column formula semantics to filter or classify matching rows.",
                    params={},
                )
            )

        if intent == "simulation":
            steps.append(
                ExecutionStep(
                    step_id=len(steps) + 1,
                    action="simulate_scenario",
                    reasoning="Apply a deterministic what-if transformation and recompute dependent metrics.",
                    params={},
                )
            )

        if intent == "insight":
            steps.append(
                ExecutionStep(
                    step_id=len(steps) + 1,
                    action="generate_insights",
                    reasoning="Compare the target entity or ranking result against peer benchmarks.",
                    params={},
                )
            )

        if intent == "data_quality":
            steps.append(
                ExecutionStep(
                    step_id=len(steps) + 1,
                    action="assess_quality",
                    reasoning="Profile missing values, invalid values, and outliers before answering.",
                    params={},
                )
            )

        if intent == "kpi_recommendation":
            steps.append(
                ExecutionStep(
                    step_id=len(steps) + 1,
                    action="recommend_kpis",
                    reasoning="Suggest KPI definitions from detected metrics, formulas, and relationships.",
                    params={},
                )
            )

        steps.append(
            ExecutionStep(
                step_id=len(steps) + 1,
                action="generate_answer",
                reasoning="Return a verified answer with supporting rows and an execution trace.",
                params={"output_mode": output_mode},
            )
        )

        return ExecutionPlan(
            query=query,
            intent=intent,
            selected_tables=relevant_tables,
            steps=steps,
            agents=agents,
            output_mode=output_mode,
        )

    def _intent(self, query: str) -> str:
        normalized = query.lower()
        if any(token in normalized for token in ("what if", "increase", "decrease", "simulate", "scenario")):
            return "simulation"
        if any(token in normalized for token in ("data quality", "issues", "missing", "outlier", "invalid")):
            return "data_quality"
        if any(token in normalized for token in ("kpi", "kpis", "track")):
            return "kpi_recommendation"
        if any(token in normalized for token in ("underperform", "why", "deviation", "anomaly")):
            return "insight"
        if any(token in normalized for token in ("highest", "lowest", "top", "best", "worst")):
            return "ranking"
        if any(token in normalized for token in ("average", "avg", "sum", "total", "count")):
            return "aggregation"
        if any(token in normalized for token in ("categorized", "category", "high", "low")):
            return "classification"
        return "lookup"

    def _output_mode(self, query: str) -> str:
        normalized = query.lower()
        if any(token in normalized for token in ("why", "what if", "simulate", "kpi", "quality")):
            return "analysis"
        if any(token in normalized for token in ("which", "top", "highest", "lowest", "list")):
            return "table"
        return "summary"

    def _agents_for_intent(self, intent: str) -> list[str]:
        if intent == "simulation":
            return ["planner", "data_agent", "simulation_agent", "validator_agent"]
        if intent == "insight":
            return ["planner", "data_agent", "insight_agent", "validator_agent"]
        if intent == "data_quality":
            return ["planner", "data_quality_agent", "validator_agent"]
        if intent == "kpi_recommendation":
            return ["planner", "kpi_agent", "validator_agent"]
        return ["planner", "data_agent", "validator_agent"]
