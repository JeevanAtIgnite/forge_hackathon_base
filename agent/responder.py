"""Response generation for execution-backed workbook answers."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd

from agent.models import AgentAnswer, ExecutionPlan, VerificationReport
from data_quality.models import DataQualityReport
from insight_engine.models import InsightReport
from kpi_engine.models import KPIRecommendation
from query_engine.models import QueryTranslation
from simulation_engine.models import SimulationResult


class ResponseGenerator:
    """Convert tool results into a demo-ready answer with trace."""

    def generate(
        self,
        query: str,
        plan: ExecutionPlan,
        result_df: pd.DataFrame,
        execution_trace: list[str],
        verification: VerificationReport,
        metrics: dict[str, Any],
        query_translation: QueryTranslation,
        insight_report: InsightReport | None = None,
        simulation_result: SimulationResult | None = None,
        data_quality_report: DataQualityReport | None = None,
        kpi_recommendations: list[KPIRecommendation] | None = None,
    ) -> AgentAnswer:
        operation = metrics.get("operation", "lookup")
        supporting_data = result_df.head(10).replace({pd.NA: None}).to_dict(orient="records")
        answer_title = "Verified Workbook Answer"

        if simulation_result is not None:
            answer_title = "Simulation Projection"
            answer_text = simulation_result.summary
        elif data_quality_report is not None:
            answer_title = "Data Quality Assessment"
            answer_text = data_quality_report.summary
        elif kpi_recommendations:
            answer_title = "Recommended KPIs"
            answer_text = (
                f"Identified {len(kpi_recommendations)} KPI recommendations from the workbook schema. "
                f"Start with {kpi_recommendations[0].name}."
            )
        elif plan.intent == "insight" and insight_report is not None and insight_report.summary:
            answer_title = "Insight Report"
            answer_text = insight_report.summary
        elif operation == "ranking" and not result_df.empty:
            top_row = supporting_data[0]
            grouping_column = metrics.get("grouping_column")
            metric_column = metrics.get("metric_column")
            subject = top_row.get(grouping_column)
            value = top_row.get(metric_column)
            if metrics.get("base_metric") and metrics.get("staffing_column"):
                answer_text = (
                    f"{subject} has the highest staffing impact score ({value}) based on "
                    f"{self._label(metrics['base_metric'])} combined with {self._label(metrics['staffing_column'])}."
                )
            else:
                answer_text = f"{subject} ranks highest for {self._label(metric_column)} with a value of {value}."
        elif operation == "average" and not result_df.empty:
            metric_column = metrics.get("metric_column", "metric")
            value = supporting_data[0].get(metric_column)
            answer_text = f"The average {self._label(metric_column)} is {value:.4f}."
        elif operation == "classification":
            answer_text = (
                f"Found {len(supporting_data)} rows that match the requested formula-based classification. "
                "The supporting rows below are filtered from the workbook directly."
            )
        elif not supporting_data:
            answer_text = "The workbook execution completed, but no rows matched the request."
        else:
            answer_text = "The workbook query executed successfully. Supporting rows are included below."

        reasoning_trace = [step.reasoning for step in plan.steps]
        return AgentAnswer(
            answer_text=answer_text,
            answer_title=answer_title,
            execution_trace=execution_trace,
            reasoning_trace=reasoning_trace,
            supporting_data=supporting_data,
            selected_tables=plan.selected_tables,
            verification=verification,
            plan=plan,
            metrics=metrics,
            query_translation=query_translation,
            insight_report=insight_report,
            simulation_result=simulation_result,
            data_quality_report=data_quality_report,
            kpi_recommendations=kpi_recommendations or [],
        )

    def _label(self, value: Any) -> str:
        text = str(value or "metric")
        text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
        text = text.replace("_", " ")
        return text.strip().lower()
