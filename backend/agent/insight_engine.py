"""Generic insight engine — peer comparison, period drivers, plan variance."""

from __future__ import annotations

import re
from typing import Any

import pandas as pd


PERIOD_PATTERN = re.compile(
    r"^(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
    r"|january|february|march|april|june|july|august|september|october|november|december"
    r"|q[1-4]|fy\s*\d{0,4}|h[12]"
    r"|wk\s*\d+|week\s*\d+|w\d+"
    r"|day\s*\d+|d\d+|m\d{1,2})$",
    re.IGNORECASE,
)

PLAN_TOKENS = ("budget", "plan", "target", "forecast", "expected", "baseline", "goal", "quota")
TOTAL_TOKENS = ("ytd", "total", "actual", "sum", "overall")


class InsightEngine:
    """Generate multi-factor explanations from result + raw data."""

    def analyze(self, execution: dict[str, Any]) -> dict[str, Any]:
        df: pd.DataFrame = execution["dataframe"]
        raw_df = execution.get("raw_dataframe")
        metric_column = execution.get("metric_column")
        dimension_column = execution.get("dimension_column")
        target_entity = execution.get("target_entity")
        query = str(execution.get("query", "")).lower()

        if df.empty or metric_column is None:
            execution["insight_card"] = {
                "title": "No insight available",
                "message": "I could not find enough structured numeric data to explain the result.",
            }
            execution["answer"] = execution.get("answer") or "I could not produce a reliable insight from this workbook."
            return execution

        working = df.copy()
        working[metric_column] = pd.to_numeric(working[metric_column], errors="coerce")
        working = working.dropna(subset=[metric_column])

        if working.empty:
            execution["insight_card"] = {
                "title": "No insight available",
                "message": "The selected metric had no numeric values to compare.",
            }
            execution["answer"] = execution["insight_card"]["message"]
            return execution

        target_row = self._find_target_row(working, dimension_column, target_entity)

        if target_row is None:
            return self._fallback_top(execution, working, metric_column, dimension_column)

        bullets = self._build_bullets(
            target_entity=str(target_row[dimension_column]),
            entity_value=float(target_row[metric_column]),
            working=working,
            metric_column=metric_column,
            dimension_column=dimension_column,
            raw_df=raw_df if isinstance(raw_df, pd.DataFrame) else None,
            query=query,
        )

        message = " ".join(bullets) if bullets else f"{target_row[dimension_column]} did not stand out from peers on {metric_column}."
        execution["insight_card"] = {"title": "Performance drivers", "message": message}
        execution["answer"] = message
        return execution

    # -------------------- core analysis --------------------

    def _build_bullets(
        self,
        target_entity: str,
        entity_value: float,
        working: pd.DataFrame,
        metric_column: str,
        dimension_column: str,
        raw_df: pd.DataFrame | None,
        query: str,
    ) -> list[str]:
        bullets: list[str] = []
        metric_label = self._readable_metric(metric_column)
        average_value = float(working[metric_column].mean())
        peer_count = int(len(working))

        # 1. Peer comparison + framing pushback
        gap_pct = ((entity_value - average_value) / average_value * 100.0) if average_value else 0.0
        asked_under = "underperform" in query or "below" in query or "lag" in query
        asked_over = "overperform" in query or "above" in query or "beat" in query or "lead" in query

        if asked_under and gap_pct >= 0:
            bullets.append(
                f"{target_entity} is actually {abs(gap_pct):.0f}% above the peer average on {metric_label} "
                f"({self._fmt(metric_column, entity_value)} vs {self._fmt(metric_column, average_value)} average across {peer_count}). "
                f"By this metric it is not underperforming."
            )
        elif asked_over and gap_pct < 0:
            bullets.append(
                f"{target_entity} is actually {abs(gap_pct):.0f}% below the peer average on {metric_label} "
                f"({self._fmt(metric_column, entity_value)} vs {self._fmt(metric_column, average_value)} average). "
                f"By this metric it is not overperforming."
            )
        else:
            verb = "beats" if gap_pct > 0 else "trails"
            bullets.append(
                f"{target_entity} {verb} the peer average by {abs(gap_pct):.0f}% — "
                f"{self._fmt(metric_column, entity_value)} vs {self._fmt(metric_column, average_value)} across {peer_count} entries."
            )

        # 2. Ranking position
        rank_df = working.sort_values(metric_column, ascending=False).reset_index(drop=True)
        rank_position: int | None = None
        for index, row in rank_df.iterrows():
            if str(row[dimension_column]).strip().lower() == target_entity.strip().lower():
                rank_position = int(index) + 1
                break
        if rank_position == 1 and peer_count > 1:
            second = rank_df.iloc[1]
            bullets.append(
                f"It ranks #1 of {peer_count}, ahead of {second[dimension_column]} "
                f"({self._fmt(metric_column, second[metric_column])})."
            )
        elif rank_position and rank_position > 1:
            leader = rank_df.iloc[0]
            bullets.append(
                f"It ranks #{rank_position} of {peer_count}, behind {leader[dimension_column]} "
                f"({self._fmt(metric_column, leader[metric_column])})."
            )

        # 3. Period-level driver (only when raw_df has period columns)
        if raw_df is not None and dimension_column in raw_df.columns:
            period_bullet = self._period_driver(raw_df, dimension_column, target_entity, metric_column)
            if period_bullet:
                bullets.append(period_bullet)

        # 4. Plan/Budget comparison
        if raw_df is not None and dimension_column in raw_df.columns:
            plan_bullet = self._plan_variance(raw_df, dimension_column, target_entity, metric_column, entity_value)
            if plan_bullet:
                bullets.append(plan_bullet)

        return bullets

    def _period_driver(
        self,
        raw_df: pd.DataFrame,
        dimension_column: str,
        target_entity: str,
        metric_column: str,
    ) -> str | None:
        period_cols = [c for c in raw_df.columns if PERIOD_PATTERN.match(str(c).strip())]
        if len(period_cols) < 3:
            return None
        mask = raw_df[dimension_column].astype(str).str.lower() == target_entity.lower()
        target_rows = raw_df[mask]
        if target_rows.empty:
            return None
        period_values: list[tuple[str, float]] = []
        for col in period_cols:
            value = pd.to_numeric(target_rows.iloc[0][col], errors="coerce")
            if pd.notna(value):
                period_values.append((str(col), float(value)))
        if len(period_values) < 3:
            return None
        period_values.sort(key=lambda item: item[1], reverse=True)
        top = period_values[:2]
        bottom = period_values[-1]
        top_str = ", ".join(f"{name} ({self._fmt(metric_column, value)})" for name, value in top)
        return f"Strongest periods were {top_str}. Weakest was {bottom[0]} ({self._fmt(metric_column, bottom[1])})."

    def _plan_variance(
        self,
        raw_df: pd.DataFrame,
        dimension_column: str,
        target_entity: str,
        metric_column: str,
        entity_value: float,
    ) -> str | None:
        metric_tokens = set(re.findall(r"[a-z]+", metric_column.lower())) - set(PLAN_TOKENS) - set(TOTAL_TOKENS)

        plan_cols: list[str] = []
        for column in raw_df.columns:
            column_lower = str(column).lower()
            if not any(token in column_lower for token in PLAN_TOKENS):
                continue
            if not pd.api.types.is_numeric_dtype(raw_df[column]):
                continue
            column_tokens = set(re.findall(r"[a-z]+", column_lower)) - set(PLAN_TOKENS)
            # Require overlap with the metric (or the plan column has no other tokens)
            if metric_tokens and column_tokens and not (metric_tokens & column_tokens):
                continue
            plan_cols.append(str(column))

        if not plan_cols:
            return None
        mask = raw_df[dimension_column].astype(str).str.lower() == target_entity.lower()
        target_rows = raw_df[mask]
        if target_rows.empty:
            return None
        plan_col = plan_cols[0]
        plan_value = pd.to_numeric(target_rows.iloc[0][plan_col], errors="coerce")
        if pd.isna(plan_value) or float(plan_value) == 0.0:
            return None
        plan_value = float(plan_value)
        delta_pct = (entity_value - plan_value) / plan_value * 100.0
        sign = "+" if delta_pct >= 0 else "−"
        return (
            f"vs {plan_col}: {self._fmt(metric_column, entity_value)} actual vs "
            f"{self._fmt(metric_column, plan_value)} planned ({sign}{abs(delta_pct):.1f}%)."
        )

    # -------------------- helpers --------------------

    def _find_target_row(
        self,
        working: pd.DataFrame,
        dimension_column: str | None,
        target_entity: str | None,
    ) -> pd.Series | None:
        if not (target_entity and dimension_column and dimension_column in working.columns):
            return None
        mask = working[dimension_column].astype(str).str.strip().str.lower() == target_entity.strip().lower()
        if not mask.any():
            return None
        return working[mask].iloc[0]

    def _fallback_top(
        self,
        execution: dict[str, Any],
        working: pd.DataFrame,
        metric_column: str,
        dimension_column: str | None,
    ) -> dict[str, Any]:
        top_rows = working.sort_values(metric_column, ascending=False).head(1).to_dict(orient="records")
        if top_rows and dimension_column:
            metric_label = self._readable_metric(metric_column)
            execution["insight_card"] = {
                "title": "Top contributor",
                "message": (
                    f"{top_rows[0][dimension_column]} leads on {metric_label} at "
                    f"{self._fmt(metric_column, top_rows[0][metric_column])}."
                ),
            }
            execution["answer"] = execution["insight_card"]["message"]
        return execution

    @staticmethod
    def _readable_metric(column: str) -> str:
        label = str(column).strip()
        label = re.sub(r"\s*\(\$\)\s*$", "", label)
        label = re.sub(r"\s*\(%\)\s*$", "", label)
        return label.replace("_", " ")

    @staticmethod
    def _fmt(column: str, value: Any) -> str:
        if value is None:
            return "—"
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        lowered = str(column).lower()
        is_currency = "$" in str(column) or any(token in lowered for token in (
            "revenue", "cost", "price", "sales", "income", "gross", "budget", "ytd", "amount", "value", "total",
        ))
        if is_currency:
            if abs(number) >= 1_000_000:
                return f"${number / 1_000_000:,.2f}M"
            if abs(number) >= 10_000:
                return f"${number:,.0f}"
            return f"${number:,.2f}"
        if number.is_integer() and abs(number) >= 1000:
            return f"{int(number):,}"
        return f"{number:,.2f}"
