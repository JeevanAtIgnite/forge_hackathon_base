"""Data agent responsible for executable joins, filters, aggregations, and rankings."""

from __future__ import annotations

from agent.tools import ToolExecutionResult, WorkbookToolExecutor


class DataAgent:
    """Thin orchestration layer over the workbook executor."""

    def __init__(self, executor: WorkbookToolExecutor):
        self.executor = executor

    def execute(self, query: str, selected_tables: list[str]) -> ToolExecutionResult:
        return self.executor.execute_plan(query, selected_tables)
