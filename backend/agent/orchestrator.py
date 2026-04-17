"""Single clean execution pipeline for agent collaboration and pandas execution."""

from __future__ import annotations

from typing import Any

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

    def run_query(self, query: str, tables) -> dict[str, Any]:
        logs: list[dict[str, str]] = []
        logs.append({"agent": "Planner", "message": "Understanding the query and identifying required data..."})
        plan = self.planner.plan(query, tables)

        logs.append({"agent": "Data Agent", "message": "Fetching relevant data and performing calculations..."})
        result = self.data_agent.execute(plan, tables)
        result["query"] = query
        result["plan"] = plan

        if "why" in query.lower() or "underperform" in query.lower():
            logs.append({"agent": "Insight Agent", "message": "Analyzing performance differences and identifying root causes..."})
            result = self.insight_engine.analyze(result)

        if "what if" in query.lower():
            logs.append({"agent": "Simulation Agent", "message": "Applying scenario changes and recalculating results..."})
            result = self.simulation_engine.simulate(result, tables)

        logs.append({"agent": "Validator", "message": "Validating results and ensuring correctness..."})
        validated = self.validator.validate(result)

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
        }
