from datetime import date

import pytest
from openpyxl import Workbook, load_workbook

from app.excel.exporter import fill_workbook


def make_template(path, period_slots=2):
    wb = Workbook()
    ws = wb.active
    ws.title = "График"
    headers = ["Подразделение", "Должность", "ФИО", "Табельный номер"]
    for _ in range(period_slots):
        headers.extend(["Количество календарных дней", "Запланированная дата"])
    ws.append(headers)
    ws.append(["Отдел", "Специалист", "Иванов Иван Иванович", "001"])
    ws.merge_cells(start_row=3, start_column=1, end_row=4, end_column=1)
    ws["A3"] = "Другой отдел"
    ws.append(["Отдел", "Эксперт", "Петров Пётр Петрович", "002"])
    wb.save(path)


def test_export_fills_periods_and_preserves_original(tmp_path):
    source = tmp_path / "original.xlsx"
    output = tmp_path / "filled.xlsx"
    make_template(source)
    rows = [{
        "sheet_name": "График", "row_number": 2, "employee_id": "employee-1",
        "employee_name": "Иванов Иван Иванович",
    }]
    periods = {"employee-1": [
        {"start_date": date(2027, 3, 1), "duration_days": 14},
        {"start_date": date(2027, 9, 1), "duration_days": 7},
    ]}

    result = fill_workbook(source, output, rows, periods)

    assert result == {"filled_rows": 1, "filled_periods": 2}
    wb = load_workbook(output)
    ws = wb["График"]
    assert ws["E2"].value == 14
    assert ws["F2"].value == date(2027, 3, 1)
    assert ws["G2"].value == 7
    assert ws["H2"].value == date(2027, 9, 1)
    assert "A3:A4" in {str(item) for item in ws.merged_cells.ranges}
    original = load_workbook(source)
    assert original["График"]["E2"].value is None
    wb.close()
    original.close()


def test_export_fails_instead_of_dropping_extra_periods(tmp_path):
    source = tmp_path / "original.xlsx"
    output = tmp_path / "filled.xlsx"
    make_template(source, period_slots=1)
    rows = [{
        "sheet_name": "График", "row_number": 2, "employee_id": "employee-1",
        "employee_name": "Иванов Иван Иванович",
    }]
    periods = {"employee-1": [
        {"start_date": date(2027, 3, 1), "duration_days": 14},
        {"start_date": date(2027, 9, 1), "duration_days": 7},
    ]}
    with pytest.raises(ValueError, match="не предусмотрено пар столбцов"):
        fill_workbook(source, output, rows, periods)
    assert not output.exists()
