from datetime import date
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from app.excel.exporter import fill_workbook
from app.excel.importer import parse_workbook


def make_template(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "TDSheet"
    ws["A18"] = "Структурное подразделение"
    ws["B18"] = "Должность (специальность, профессия) по штатному расписанию"
    ws["C18"] = "Фамилия, имя, отчество"
    ws["D18"] = "Табельный номер"
    ws.merge_cells("E18:F18")
    ws["E18"] = "ОТПУСК"
    ws["E19"] = "Количество календарных дней"
    ws["G20"] = "запланированная"
    ws.merge_cells("E22:F22")
    ws["A22"] = "Отдел"
    ws["B22"] = "Специалист"
    ws["C22"] = "Иванов Иван Иванович"
    ws["D22"] = "001"
    ws["E22"] = 36
    ws["G22"] = "01.01.2026 (36)"
    ws.merge_cells("E23:F23")
    ws["A23"] = "Отдел"
    ws["B23"] = "Эксперт"
    ws["C23"] = "Иванов Иван Иванович"
    ws["D23"] = "001"
    ws["E23"] = 36
    ws["G23"] = "01.01.2026 (36)"
    wb.save(path)


def test_export_writes_all_periods_to_shared_t7_cells_and_preserves_original(tmp_path):
    source = tmp_path / "original.xlsx"
    output = tmp_path / "filled.xlsx"
    make_template(source)
    rows = [
        {"sheet_name": "TDSheet", "row_number": 22, "employee_id": "employee-1", "employee_name": "Иванов Иван Иванович"},
        {"sheet_name": "TDSheet", "row_number": 23, "employee_id": "employee-1", "employee_name": "Иванов Иван Иванович"},
    ]
    periods = {"employee-1": [
        {"start_date": date(2027, 3, 1), "duration_days": 14, "sort_order": 1},
        {"start_date": date(2027, 9, 1), "duration_days": 7, "sort_order": 2},
    ]}

    result = fill_workbook(source, output, rows, periods)

    assert result == {"filled_rows": 2, "filled_periods": 4}
    wb = load_workbook(output)
    ws = wb["TDSheet"]
    for row in (22, 23):
        assert ws[f"E{row}"].value == 21
        assert ws[f"G{row}"].value == "01.03.2027 (14) 01.09.2027 (7)"
    assert "E22:F22" in {str(item) for item in ws.merged_cells.ranges}
    original = load_workbook(source)
    assert original["TDSheet"]["E22"].value == 36
    assert original["TDSheet"]["G22"].value == "01.01.2026 (36)"
    wb.close()
    original.close()


def test_export_clears_stale_periods_when_employee_has_no_new_periods(tmp_path):
    source = tmp_path / "original.xlsx"
    output = tmp_path / "filled.xlsx"
    make_template(source)
    rows = [{"sheet_name": "TDSheet", "row_number": 22, "employee_id": "employee-1"}]

    fill_workbook(source, output, rows, {})

    wb = load_workbook(output)
    assert wb["TDSheet"]["E22"].value is None
    assert wb["TDSheet"]["G22"].value is None
    wb.close()


def test_reference_template_has_the_shared_t7_structure(tmp_path):
    template = Path(__file__).resolve().parents[2] / "ГРАФИК ОТПУСКОВ ООО  2026.xlsx"
    output = tmp_path / "reference-filled.xlsx"
    assert template.is_file(), "Reference T-7 workbook must remain in repository root"
    parsed = parse_workbook(template)
    assert parsed
    assert all(row["sheet_name"] == "TDSheet" for row in parsed)
    assert min(row["row_number"] for row in parsed) >= 22
    assert all(row["employee_name"] and row["personnel_number"] for row in parsed)

    first = parsed[0]
    employee_id = "reference-employee"
    fill_workbook(
        template,
        output,
        [{**first, "employee_id": employee_id}],
        {employee_id: [
            {"start_date": date(2027, 3, 1), "duration_days": 14},
            {"start_date": date(2027, 9, 1), "duration_days": 7},
        ]},
    )
    wb = load_workbook(output)
    ws = wb["TDSheet"]
    assert ws[f"E{first['row_number']}"].value == 21
    assert ws[f"G{first['row_number']}"].value == "01.03.2027 (14) 01.09.2027 (7)"
    wb.close()


def test_export_rejects_unexpected_t7_column_positions(tmp_path):
    source = tmp_path / "wrong.xlsx"
    output = tmp_path / "filled.xlsx"
    wb = Workbook()
    ws = wb.active
    ws["A18"] = "Структурное подразделение"
    ws["B18"] = "Другая колонка"
    ws["C18"] = "Фамилия, имя, отчество"
    ws["D18"] = "Табельный номер"
    ws["A22"] = "Отдел"
    ws["B22"] = "Специалист"
    ws["C22"] = "Иванов Иван Иванович"
    ws["D22"] = "001"
    ws["F22"] = "bad"
    wb.save(source)
    with pytest.raises(ValueError, match="общая структура Т-7"):
        fill_workbook(source, output, [{"sheet_name": "Sheet", "row_number": 22, "employee_id": "e"}], {"e": []})
    assert not output.exists()
