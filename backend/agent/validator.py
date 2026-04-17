"""Minimal validator that never crashes the pipeline."""

from __future__ import annotations

from typing import Any

import pandas as pd


class Validator:
    """Validate outputs and downgrade to warnings rather than hard failures."""

    def validate(self, execution: dict[str, Any]) -> dict[str, Any]:
        warnings = list(execution.get("warnings", []))
        df: pd.DataFrame = execution.get("dataframe", pd.DataFrame())

        if df.empty and execution.get("status") == "success":
            warnings.append("The execution completed but returned no rows.")

        execution["warnings"] = warnings
        execution["validated"] = True
        execution["success"] = execution.get("status") != "error"
        return execution
