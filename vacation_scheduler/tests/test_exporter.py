from datetime import date
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

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



def test_end_to_end_reference_template_groups_by_name_and_exports_all_positions(tmp_path):
    """Exercise the real T-7: parse rows, group by FIO (not personnel number),
    enter one set of periods per employee, and export to every linked position.
    """
    from collections import defaultdict

    from app.services.employee_matching import normalize_person_name

    template = Path(__file__).resolve().parents[2] / "ГРАФИК ОТПУСКОВ ООО  2026.xlsx"
    output = tmp_path / "reference-end-to-end.xlsx"
    parsed_rows = parse_workbook(template)

    grouped_rows = defaultdict(list)
    for row in parsed_rows:
        grouped_rows[normalize_person_name(row["employee_name"])].append(row)

    duplicate_groups = [
        (name, rows)
        for name, rows in grouped_rows.items()
        if name and len(rows) > 1
    ]
    assert duplicate_groups, "Reference template should contain employees with multiple positions"

    # Pick a real employee whose job rows carry different personnel numbers.
    different_number_groups = [
        (name, rows)
        for name, rows in duplicate_groups
        if len({row["personnel_number"] for row in rows}) > 1
    ]
    assert different_number_groups, (
        "Reference template should demonstrate that one employee can have "
        "different personnel numbers for different positions"
    )

    employee_periods = {}
    export_rows = []
    for normalized_name, employee_rows in grouped_rows.items():
        employee_id = f"employee:{normalized_name}"
        employee_periods[employee_id] = [
            {"start_date": date(2027, 3, 1), "duration_days": 14, "sort_order": 1},
            {"start_date": date(2027, 9, 1), "duration_days": 7, "sort_order": 2},
        ]
        for row in employee_rows:
            export_rows.append({**row, "employee_id": employee_id})

    result = fill_workbook(template, output, export_rows, employee_periods)
    assert result == {
        "filled_rows": len(parsed_rows),
        "filled_periods": len(parsed_rows) * 2,
    }

    wb = load_workbook(output, data_only=False)
    source_wb = load_workbook(template, data_only=False)
    try:
        output_ws = wb["TDSheet"]
        source_ws = source_wb["TDSheet"]
        for _, employee_rows in duplicate_groups:
            first_row = employee_rows[0]
            expected_employee_id = f"employee:{normalize_person_name(first_row['employee_name'])}"
            expected_rows = [
                row for row in employee_rows
                if f"employee:{normalize_person_name(row['employee_name'])}" == expected_employee_id
            ]
            for row in expected_rows:
                row_number = row["row_number"]
                assert output_ws[f"E{row_number}"].value == 21
                assert output_ws[f"G{row_number}"].value == (
                    "01.03.2027 (14) 01.09.2027 (7)"
                )
                # Position-specific personnel numbers must be preserved verbatim.
                assert output_ws[f"D{row_number}"].value == source_ws[f"D{row_number}"].value

        assert {str(r) for r in output_ws.merged_cells.ranges} == {
            str(r) for r in source_ws.merged_cells.ranges
        }
    finally:
        wb.close()
        source_wb.close()


def test_xlsm_export_preserves_vba_project_payload(tmp_path):
    xlsx_source = tmp_path / "macro-source.xlsx"
    source = tmp_path / "macro-source.xlsm"
    output = tmp_path / "macro-filled.xlsm"
    make_template(xlsx_source)
    macro_payload = b"test-vba-project-payload"
    with ZipFile(xlsx_source, "r") as original, ZipFile(source, "w", ZIP_DEFLATED) as macro_book:
        for item in original.infolist():
            macro_book.writestr(item, original.read(item.filename))
        macro_book.writestr("xl/vbaProject.bin", macro_payload)

    result = fill_workbook(
        source, output,
        [{"sheet_name": "TDSheet", "row_number": 22, "employee_id": "employee-1"}],
        {"employee-1": [{"start_date": date(2027, 3, 1), "duration_days": 14}]},
    )

    assert result == {"filled_rows": 1, "filled_periods": 1}
    with ZipFile(output, "r") as exported:
        assert exported.read("xl/vbaProject.bin") == macro_payload
    wb = load_workbook(output, keep_vba=True, data_only=False)
    try:
        assert wb["TDSheet"]["E22"].value == 14
        assert wb["TDSheet"]["G22"].value == "01.03.2027 (14)"
    finally:
        wb.close()
