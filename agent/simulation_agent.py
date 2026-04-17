"""Simulation agent for deterministic what-if scenarios."""

from __future__ import annotations

import pandas as pd

from simulation_engine.engine import SimulationEngine
from simulation_engine.models import SimulationResult


class SimulationAgent:
    """Apply scenario transformations and produce projections."""

    def __init__(self) -> None:
        self.engine = SimulationEngine()

    def simulate(self, query: str, dataframe: pd.DataFrame, grouping_column: str | None) -> SimulationResult:
        return self.engine.simulate(query, dataframe, grouping_column)
