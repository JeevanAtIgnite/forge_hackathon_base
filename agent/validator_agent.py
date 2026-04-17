"""Validator agent wrapper around execution verification."""

from __future__ import annotations

import pandas as pd

from agent.models import ExecutionPlan, VerificationReport
from agent.verifier import VerifierAgent
from relationship_graph.models import RelationshipGraphModel
from schema_builder.models import WorkbookSchema


class ValidatorAgent:
    """Validate that outputs remain tied to workbook structure and execution."""

    def __init__(self) -> None:
        self.verifier = VerifierAgent()

    def validate(
        self,
        plan: ExecutionPlan,
        schema: WorkbookSchema,
        relationships: RelationshipGraphModel,
        result_df: pd.DataFrame,
        metrics: dict,
    ) -> VerificationReport:
        return self.verifier.verify(plan=plan, schema=schema, relationships=relationships, result_df=result_df, metrics=metrics)
