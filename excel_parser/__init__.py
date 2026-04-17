"""Excel parsing layer.

This package turns workbooks into logical tables instead of treating sheets
as raw text blobs. The downstream schema builder, relationship graph, and
agent all consume these structured table objects.
"""

from excel_parser.models import Column, Formula, Table, WorkbookTables
from excel_parser.parser import ExcelWorkbookParser

__all__ = [
    "Column",
    "Formula",
    "Table",
    "WorkbookTables",
    "ExcelWorkbookParser",
]
