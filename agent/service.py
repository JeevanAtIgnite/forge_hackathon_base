"""End-to-end workbook knowledge builder and multi-agent query orchestrator."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from agent.data_agent import DataAgent
from agent.insight_agent import InsightAgent
from agent.models import AgentAnswer, WorkbookKnowledgeBundle
from agent.planner import PlannerAgent
from agent.responder import ResponseGenerator
from agent.simulation_agent import SimulationAgent
from agent.tools import WorkbookToolExecutor
from agent.validator_agent import ValidatorAgent
from data_quality.engine import DataQualityEngine
from embedding_layer.index import MetadataEmbeddingIndex
from excel_parser.parser import ExcelWorkbookParser
from formula_engine.engine import FormulaInterpreter
from kpi_engine.engine import KPIRecommendationEngine
from query_engine.translator import QueryTranslator
from relationship_graph.graph import RelationshipGraphBuilder
from schema_builder.builder import SchemaBuilder
from semantic_model.builder import SemanticModelBuilder


class ExcelReasoningAgent:
    """Treat Excel as a structured database with multi-agent reasoning."""

    def __init__(self) -> None:
        self.parser = ExcelWorkbookParser()
        self.schema_builder = SchemaBuilder()
        self.formula_interpreter = FormulaInterpreter()
        self.relationship_builder = RelationshipGraphBuilder()
        self.semantic_builder = SemanticModelBuilder()
        self.data_quality_engine = DataQualityEngine()
        self.kpi_engine = KPIRecommendationEngine()
        self.planner = PlannerAgent()
        self.query_translator = QueryTranslator()
        self.insight_agent = InsightAgent()
        self.simulation_agent = SimulationAgent()
        self.validator_agent = ValidatorAgent()
        self.responder = ResponseGenerator()

    @lru_cache(maxsize=16)
    def build_bundle(self, file_path: str, file_mtime_ns: int) -> WorkbookKnowledgeBundle:
        parsed_tables = self.parser.parse(file_path)
        formulas = self.formula_interpreter.build_catalog(parsed_tables.tables)
        schema = self.schema_builder.build(parsed_tables, formulas)
        relationships = self.relationship_builder.build(schema.tables)
        metadata_index = MetadataEmbeddingIndex.build(schema, relationships)
        semantic_model = self.semantic_builder.build(schema, formulas, relationships)
        dataframes = self._dataframes(parsed_tables)
        data_quality_report = self.data_quality_engine.analyze(dataframes, schema)
        kpi_recommendations = self.kpi_engine.recommend(schema, relationships)

        return WorkbookKnowledgeBundle(
            parsed_tables=parsed_tables,
            schema=schema,
            formulas=formulas,
            relationships=relationships,
            metadata_index=metadata_index.snapshot(),
            semantic_model=semantic_model,
            data_quality_report=data_quality_report,
            kpi_recommendations=kpi_recommendations,
        )

    def load_bundle(self, file_path: str) -> WorkbookKnowledgeBundle:
        path = Path(file_path)
        stat = path.stat()
        return self.build_bundle(str(path), stat.st_mtime_ns)

    def answer_query(self, file_path: str, query: str) -> AgentAnswer:
        bundle = self.load_bundle(file_path)
        metadata_index = MetadataEmbeddingIndex.build(bundle.schema, bundle.relationships)
        plan = self.planner.create_plan(query, bundle.schema, bundle.relationships, metadata_index)

        dataframes = self._dataframes(bundle.parsed_tables)
        executor = WorkbookToolExecutor(
            dataframes=dataframes,
            schema=bundle.schema,
            relationships=bundle.relationships,
        )
        data_agent = DataAgent(executor)

        working_df, base_trace = executor.build_working_dataframe(plan.selected_tables)
        context = executor.resolve_query_context(query, working_df)
        query_translation = self.query_translator.translate(
            plan,
            metric_column=context.get("metric_column"),
            grouping_column=context.get("grouping_column"),
        )

        result_df = pd.DataFrame()
        execution_trace = list(base_trace)
        metrics: dict[str, object] = {
            "metric_column": context.get("metric_column"),
            "grouping_column": context.get("grouping_column"),
        }
        insight_report = None
        simulation_result = None
        data_quality_report = None
        kpi_recommendations = []

        if plan.intent == "simulation":
            simulation_result = self.simulation_agent.simulate(query, working_df, context.get("grouping_column"))
            result_df = pd.DataFrame(simulation_result.after_rows)
            execution_trace.append("Applied the requested what-if transformation to the selected dataset.")
            execution_trace.append("Recomputed projected metrics from the transformed workbook values.")
            metrics["operation"] = "simulation"
            if simulation_result.scenario:
                query_translation.simulation = simulation_result.scenario.model_dump(mode="json")

        elif plan.intent == "data_quality":
            data_quality_report = bundle.data_quality_report
            result_df = pd.DataFrame([issue.model_dump(mode="json") for issue in data_quality_report.issues[:20]])
            execution_trace.append("Scanned workbook tables for missing values, invalid ranges, and outliers.")
            metrics["operation"] = "data_quality"

        elif plan.intent == "kpi_recommendation":
            kpi_recommendations = bundle.kpi_recommendations
            result_df = pd.DataFrame([item.model_dump(mode="json") for item in kpi_recommendations[:10]])
            execution_trace.append("Suggested KPIs from schema columns, formula-derived metrics, and joins.")
            metrics["operation"] = "kpi_recommendation"

        elif plan.intent == "insight":
            insight_report = self.insight_agent.analyze(
                query=query,
                dataframe=working_df,
                grouping_column=context.get("grouping_column"),
                metric_column=context.get("metric_column"),
            )
            result_df = pd.DataFrame(insight_report.benchmark_rows or working_df.head(10).to_dict(orient="records"))
            execution_trace.append("Computed peer benchmarks for the selected entity and metric.")
            execution_trace.append("Generated explainable insight findings from workbook-backed comparisons.")
            metrics["operation"] = "insight"

        else:
            execution = data_agent.execute(query, plan.selected_tables)
            result_df = execution.dataframe
            execution_trace = execution.trace
            metrics.update(execution.metrics)
            if plan.intent == "ranking":
                insight_report = self.insight_agent.analyze(
                    query=query,
                    dataframe=working_df,
                    grouping_column=context.get("grouping_column"),
                    metric_column=context.get("metric_column"),
                )

        verification = self.validator_agent.validate(
            plan=plan,
            schema=bundle.schema,
            relationships=bundle.relationships,
            result_df=result_df,
            metrics=metrics,
        )

        return self.responder.generate(
            query=query,
            plan=plan,
            result_df=result_df,
            execution_trace=execution_trace,
            verification=verification,
            metrics=metrics,
            query_translation=query_translation,
            insight_report=insight_report,
            simulation_result=simulation_result,
            data_quality_report=data_quality_report,
            kpi_recommendations=kpi_recommendations,
        )

    def _dataframes(self, parsed_tables) -> dict[str, pd.DataFrame]:
        return {table.name: pd.DataFrame(table.rows) for table in parsed_tables.tables}
