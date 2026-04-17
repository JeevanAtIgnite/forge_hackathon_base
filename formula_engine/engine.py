"""Convert Excel formulas into reusable semantic logic."""

from __future__ import annotations

import re
from typing import Any

from excel_parser.models import Table
from formula_engine.models import DerivedColumnLogic, FormulaCatalog


class FormulaInterpreter:
    """Interpret formulas into human-readable logic statements."""

    def build_catalog(self, tables: list[Table]) -> FormulaCatalog:
        derived_columns: list[DerivedColumnLogic] = []

        for table in tables:
            by_column: dict[str, list[Any]] = {}
            for formula in table.formulas:
                by_column.setdefault(formula.column_name, []).append(formula)

            column_lookup = {column.excel_letter: column.name for column in table.columns}

            for column_name, formulas in by_column.items():
                first_formula = formulas[0]
                derived_columns.append(
                    DerivedColumnLogic(
                        table_name=table.name,
                        column_name=column_name,
                        formula_type=self._infer_formula_type(first_formula.formula),
                        logic=self._semantic_logic(first_formula.formula, column_name, column_lookup),
                        depends_on=self._column_dependencies(first_formula.formula, column_lookup),
                        excel_formula_examples=[f.formula for f in formulas[:3]],
                        sample_values=[str(f.cached_value) for f in formulas[:3] if f.cached_value not in (None, "")],
                    )
                )

        return FormulaCatalog(derived_columns=derived_columns)

    def _infer_formula_type(self, formula: str) -> str:
        normalized = formula.upper()
        if normalized.startswith("=IF("):
            return "conditional"
        if any(token in normalized for token in ("SUM(", "AVERAGE(", "COUNT(")):
            return "aggregation"
        if any(token in normalized for token in ("/", "*", "+", "-")):
            return "arithmetic"
        return "derived"

    def _semantic_logic(self, formula: str, column_name: str, column_lookup: dict[str, str]) -> str:
        normalized = formula.strip()

        if_match = re.match(r'=IF\((.+?),(.*?),(.*)\)$', normalized, re.IGNORECASE)
        if if_match:
            condition = self._replace_cell_refs(if_match.group(1), column_lookup)
            true_case = if_match.group(2).strip().strip('"')
            false_case = if_match.group(3).strip().strip('"')
            return f"{column_name} is '{true_case}' when {condition}; otherwise '{false_case}'."

        expression = normalized.lstrip("=")
        expression = self._replace_cell_refs(expression, column_lookup)
        expression = expression.replace("*", " * ").replace("/", " / ").replace("+", " + ").replace("-", " - ")
        expression = re.sub(r"\s+", " ", expression).strip()
        return f"{column_name} is derived from {expression}."

    def _replace_cell_refs(self, expression: str, column_lookup: dict[str, str]) -> str:
        def replace(match: re.Match[str]) -> str:
            ref = match.group(0)
            letter = re.match(r"([A-Z]{1,3})\d+", ref)
            if not letter:
                return ref
            return column_lookup.get(letter.group(1), ref)

        return re.sub(r"\b[A-Z]{1,3}\d+\b", replace, expression)

    def _column_dependencies(self, formula: str, column_lookup: dict[str, str]) -> list[str]:
        dependencies: list[str] = []
        for ref in re.findall(r"\b([A-Z]{1,3})\d+\b", formula.upper()):
            dependency = column_lookup.get(ref)
            if dependency and dependency not in dependencies:
                dependencies.append(dependency)
        return dependencies
