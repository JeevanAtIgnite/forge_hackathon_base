"""Generic insight engine — peer + period + plan analysis with no domain hardcoding."""

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
SUBTOTAL_PATTERN = re.compile(
    r"\b(total|subtotal|grand|sum|aggregate|overall|all\s)\b",
    re.IGNORECASE,
)


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

        # Build the comparable peer set:
        #   1) drop subtotal-like rows
        #   2) keep rows in the same order of magnitude as the target (0.2x .. 5x)
        peers = self._comparable_peers(working, metric_column, dimension_column, target_entity, entity_value)
        peer_count = int(len(peers))

        # 1. Headline: absolute value + ranking position within comparable peers
        rank_position = self._rank_within(peers, metric_column, dimension_column, target_entity)
        if rank_position == 1 and peer_count > 1:
            second_row = peers.sort_values(metric_column, ascending=False).iloc[1]
            bullets.append(
                f"{target_entity} contributed {self._fmt(metric_column, entity_value)} on {metric_label} — "
                f"the largest of {peer_count} comparable items, ahead of {second_row[dimension_column]} "
                f"({self._fmt(metric_column, second_row[metric_column])})."
            )
        elif rank_position and peer_count > 1:
            sorted_peers = peers.sort_values(metric_column, ascending=False).reset_index(drop=True)
            leader = sorted_peers.iloc[0]
            bullets.append(
                f"{target_entity} contributed {self._fmt(metric_column, entity_value)} on {metric_label} — "
                f"ranked #{rank_position} of {peer_count} comparable items, behind {leader[dimension_column]} "
                f"({self._fmt(metric_column, leader[metric_column])})."
            )
        else:
            bullets.append(
                f"{target_entity} contributed {self._fmt(metric_column, entity_value)} on {metric_label}."
            )

        # 2. Peer-average gap + framing pushback
        if peer_count > 1:
            average_value = float(peers[metric_column].mean())
            gap_pct = ((entity_value - average_value) / average_value * 100.0) if average_value else 0.0
            asked_under = "underperform" in query or "below" in query or "lag" in query
            asked_over = "overperform" in query or "above" in query or "beat" in query

            if asked_under and gap_pct >= 0:
                bullets.append(
                    f"It is {abs(gap_pct):.0f}% above the average of comparable items "
                    f"({self._fmt(metric_column, average_value)}) — by this metric it is not underperforming."
                )
            elif asked_over and gap_pct < 0:
                bullets.append(
                    f"It is {abs(gap_pct):.0f}% below the average of comparable items "
                    f"({self._fmt(metric_column, average_value)}) — by this metric it is not overperforming."
                )
            else:
                verb = "above" if gap_pct >= 0 else "below"
                bullets.append(
                    f"That is {abs(gap_pct):.0f}% {verb} the comparable peer average of "
                    f"{self._fmt(metric_column, average_value)}."
                )

        # 3. Period consistency + trend analysis (very explanatory)
        period_bullet = self._period_analysis(raw_df, dimension_column, target_entity, metric_column)
        if period_bullet:
            bullets.append(period_bullet)

        # 4. Plan / budget variance (only if a matching plan column exists)
        plan_bullet = self._plan_variance(raw_df, dimension_column, target_entity, metric_column, entity_value)
        if plan_bullet:
            bullets.append(plan_bullet)

        return bullets

    # -------------------- comparable-peer logic --------------------

    def _comparable_peers(
        self,
        working: pd.DataFrame,
        metric_column: str,
        dimension_column: str,
        target_entity: str,
        entity_value: float,
    ) -> pd.DataFrame:
        if dimension_column not in working.columns:
            return working
        peers = working.copy()
        peers = peers[~peers[dimension_column].astype(str).str.contains(SUBTOTAL_PATTERN, regex=True, na=False)]
        if entity_value > 0:
            lower = entity_value * 0.2
            upper = entity_value * 5.0
            magnitude_peers = peers[(peers[metric_column] >= lower) & (peers[metric_column] <= upper)]
            if len(magnitude_peers) >= 2:
                peers = magnitude_peers
        if peers.empty:
            return working
        return peers.reset_index(drop=True)

    def _rank_within(
        self,
        peers: pd.DataFrame,
        metric_column: str,
        dimension_column: str,
        target_entity: str,
    ) -> int | None:
        ranked = peers.sort_values(metric_column, ascending=False).reset_index(drop=True)
        for idx, row in ranked.iterrows():
            if str(row[dimension_column]).strip().lower() == target_entity.strip().lower():
                return int(idx) + 1
        return None

    # -------------------- period analysis --------------------

    def _period_analysis(
        self,
        raw_df: pd.DataFrame | None,
        dimension_column: str,
        target_entity: str,
        metric_column: str,
    ) -> str | None:
        if raw_df is None or dimension_column not in raw_df.columns:
            return None

        period_cols = [c for c in raw_df.columns if PERIOD_PATTERN.match(str(c).strip())]
        if len(period_cols) < 4:
            return None

        mask = raw_df[dimension_column].astype(str).str.lower() == target_entity.lower()
        target_rows = raw_df[mask]
        if target_rows.empty:
            return None

        values: list[tuple[str, float]] = []
        for column in period_cols:
            value = pd.to_numeric(target_rows.iloc[0][column], errors="coerce")
            if pd.notna(value):
                values.append((str(column), float(value)))
        if len(values) < 4:
            return None

        numbers = [value for _, value in values]
        mean_value = sum(numbers) / len(numbers)
        if mean_value == 0:
            return None

        max_value = max(numbers)
        min_value = min(numbers)
        spread_pct = (max_value - min_value) / abs(mean_value) * 100.0

        if spread_pct < 25:
            consistency = "very consistent"
        elif spread_pct < 60:
            consistency = "moderately variable"
        else:
            consistency = "highly variable"

        sorted_values = sorted(values, key=lambda item: item[1], reverse=True)
        best = sorted_values[0]
        worst = sorted_values[-1]

        half = len(values) // 2
        first_avg = sum(numbers[:half]) / half if half else mean_value
        second_count = len(numbers) - half
        second_avg = sum(numbers[half:]) / second_count if second_count else mean_value
        if first_avg > 0 and second_avg > first_avg * 1.05:
            trend = f"trending up — second half averaged {self._fmt(metric_column, second_avg)} vs first half {self._fmt(metric_column, first_avg)} (+{(second_avg / first_avg - 1) * 100:.0f}%)"
        elif second_avg > 0 and first_avg > second_avg * 1.05:
            trend = f"trending down — second half averaged {self._fmt(metric_column, second_avg)} vs first half {self._fmt(metric_column, first_avg)} (−{(1 - second_avg / first_avg) * 100:.0f}%)"
        else:
            trend = f"flat across the year (each half averaged ~{self._fmt(metric_column, mean_value)})"

        return (
            f"Across {len(values)} periods it was {consistency}: "
            f"best period {best[0]} at {self._fmt(metric_column, best[1])}, "
            f"weakest {worst[0]} at {self._fmt(metric_column, worst[1])}, {trend}."
        )

    # -------------------- plan / budget variance --------------------

    def _plan_variance(
        self,
        raw_df: pd.DataFrame | None,
        dimension_column: str,
        target_entity: str,
        metric_column: str,
        entity_value: float,
    ) -> str | None:
        if raw_df is None or dimension_column not in raw_df.columns:
            return None

        metric_tokens = set(re.findall(r"[a-z]+", metric_column.lower())) - set(PLAN_TOKENS) - set(TOTAL_TOKENS)

        plan_cols: list[str] = []
        for column in raw_df.columns:
            column_lower = str(column).lower()
            if not any(token in column_lower for token in PLAN_TOKENS):
                continue
            if not pd.api.types.is_numeric_dtype(raw_df[column]):
                continue
            column_tokens = set(re.findall(r"[a-z]+", column_lower)) - set(PLAN_TOKENS)
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
