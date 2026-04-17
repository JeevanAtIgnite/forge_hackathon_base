from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

from agent.service import ExcelReasoningAgent


def build_intelligence_workbook(path: Path) -> None:
    workbook = Workbook()
    sales = workbook.active
    sales.title = "Sales"
    sales.append(["Dealer", "Region", "Leads", "Appointments", "ConversionRate", "Category"])
    sales.append(["Danbury", "East", 120, 24, "=D2/C2", '=IF(C2>100,"High","Low")'])
    sales.append(["North Motors", "East", 150, 52, "=D3/C3", '=IF(C3>100,"High","Low")'])
    sales.append(["City Auto", "West", 90, 34, "=D4/C4", '=IF(C4>100,"High","Low")'])
    sales.append(["Summit Cars", "West", 180, 70, "=D5/C5", '=IF(C5>100,"High","Low")'])

    staffing = workbook.create_sheet("Staffing")
    staffing.append(["Dealer", "StaffCount", "StaffingCost"])
    staffing.append(["Danbury", 10, 110000])
    staffing.append(["North Motors", 12, 125000])
    staffing.append(["City Auto", None, -5000])
    staffing.append(["Summit Cars", 16, 155000])

    workbook.save(path)


def test_bundle_includes_semantic_quality_and_kpi_layers(tmp_path: Path) -> None:
    workbook_path = tmp_path / "intelligence.xlsx"
    build_intelligence_workbook(workbook_path)

    agent = ExcelReasoningAgent()
    bundle = agent.load_bundle(str(workbook_path))

    assert "Dealer" in bundle.semantic_model.entities
    assert "Conversion Rate" in bundle.semantic_model.metrics
    assert bundle.data_quality_report.issues
    assert any(kpi.name == "Conversion Rate" for kpi in bundle.kpi_recommendations)


def test_agent_supports_insight_simulation_kpi_and_quality_queries(tmp_path: Path) -> None:
    workbook_path = tmp_path / "intelligence.xlsx"
    build_intelligence_workbook(workbook_path)

    agent = ExcelReasoningAgent()

    insight = agent.answer_query(str(workbook_path), "Why is Danbury underperforming?")
    assert insight.verification.valid
    assert insight.insight_report is not None
    assert "Danbury" in insight.answer_text
    assert insight.query_translation.intent == "insight"

    simulation = agent.answer_query(str(workbook_path), "What if staffing increases by 20%?")
    assert simulation.verification.valid
    assert simulation.simulation_result is not None
    assert simulation.simulation_result.scenario is not None
    assert simulation.simulation_result.scenario.column_name == "StaffCount"

    kpis = agent.answer_query(str(workbook_path), "What KPIs should I track?")
    assert kpis.verification.valid
    assert kpis.kpi_recommendations
    assert kpis.query_translation.intent == "kpi_recommendation"

    quality = agent.answer_query(str(workbook_path), "Are there issues in this dataset?")
    assert quality.verification.valid
    assert quality.data_quality_report is not None
    assert quality.data_quality_report.issues
