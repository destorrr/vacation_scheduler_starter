from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.excel.importer import detect_header, parse_workbook


def test_parse_workbook_with_t7_style_headers(tmp_path):
    path = tmp_path / "template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "График"
    ws.append(["№", "Структурное подразделение", "Должность (специальность, профессия)", "Фамилия, имя, отчество", "Табельный номер"])
    ws.append([1, "Бухгалтерия", "Бухгалтер", "Иванов Иван Иванович", "00125"])
    ws.append([2, None, "Ведущий бухгалтер", "Петров Пётр Петрович", "00126"])
    wb.save(path)

    rows = parse_workbook(path)

    assert len(rows) == 2
    assert rows[0]["sheet_name"] == "График"
    assert rows[0]["row_number"] == 2
    assert rows[0]["department_name"] == "Бухгалтерия"
    assert rows[0]["position_name"] == "Бухгалтер"
    assert rows[0]["personnel_number"] == "00125"
    assert rows[1]["department_name"] == "Бухгалтерия"
    assert rows[1]["position_name"] == "Ведущий бухгалтер"


def test_header_detection_skips_non_data_sheets(tmp_path):
    path = tmp_path / "template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Титульный"
    ws["A1"] = "График отпусков"
    ws2 = wb.create_sheet("Лист1")
    ws2.append(["ФИО", "Подразделение"])
    ws2.append(["Сидоров Сидор Сидорович", "Отдел"])
    wb.save(path)

    rows = parse_workbook(path)
    assert len(rows) == 1
    assert rows[0]["sheet_name"] == "Лист1"


def test_detect_header_returns_none_for_unrelated_sheet(tmp_path):
    path = tmp_path / "template.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(["Название", "Дата", "Сумма"])
    wb.save(path)
    assert detect_header(ws) is None


def test_import_keeps_duplicate_fio_rows_and_position_specific_personnel_numbers(tmp_path):
    path = tmp_path / "duplicate-fio.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Т-7"
    ws.append(["№", "Структурное подразделение", "Должность", "ФИО", "Табельный номер"])
    ws.append([1, "Бухгалтерия", "Бухгалтер", "Смирнова Марина Викторовна", "00125"])
    ws.append([2, None, "Главный бухгалтер", "СМИРНОВА, Марина Викторовна", "00987"])
    ws.merge_cells("B2:B3")
    ws["B2"].font = Font(bold=True)
    ws["B2"].fill = PatternFill("solid", fgColor="FFFF00")
    ws.append([None, None, None, None, None])
    ws.append([3, "Кадровая служба", "Специалист", "Иванов Иван Иванович", "00126"])
    wb.save(path)

    rows = parse_workbook(path)

    assert len(rows) == 3
    assert [row["row_number"] for row in rows] == [2, 3, 5]
    assert rows[0]["employee_name"] == "Смирнова Марина Викторовна"
    assert rows[1]["employee_name"] == "СМИРНОВА, Марина Викторовна"
    assert rows[0]["department_name"] == rows[1]["department_name"] == "Бухгалтерия"
    assert [row["position_name"] for row in rows[:2]] == [
        "Бухгалтер", "Главный бухгалтер"
    ]
    assert [row["personnel_number"] for row in rows[:2]] == ["00125", "00987"]
    assert rows[2]["department_name"] == "Кадровая служба"


def test_import_ignores_fully_empty_rows_and_preserves_sheet_names(tmp_path):
    path = tmp_path / "empty-rows.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Основной лист"
    ws.append(["ФИО", "Подразделение"])
    ws.append(["Петров Пётр Петрович", "Отдел продаж"])
    ws.append([None, None])
    ws.append([None, None])
    ws.append(["Сидоров Сидор Сидорович", "Отдел закупок"])
    wb.save(path)

    rows = parse_workbook(path)

    assert [(row["row_number"], row["employee_name"]) for row in rows] == [
        (2, "Петров Пётр Петрович"),
        (5, "Сидоров Сидор Сидорович"),
    ]
    assert all(row["sheet_name"] == "Основной лист" for row in rows)


def test_import_skips_hidden_and_very_hidden_worksheets(tmp_path):
    path = tmp_path / "hidden-sheets.xlsx"
    wb = Workbook()
    visible = wb.active
    visible.title = "Т-7"
    visible.append(["ФИО", "Должность"])
    visible.append(["Иванов Иван Иванович", "Специалист"])
    hidden = wb.create_sheet("Архив")
    hidden.append(["ФИО", "Должность"])
    hidden.append(["Петров Пётр Петрович", "Архивная должность"])
    hidden.sheet_state = "hidden"
    very_hidden = wb.create_sheet("Служебный")
    very_hidden.append(["ФИО", "Должность"])
    very_hidden.append(["Сидоров Сидор Сидорович", "Служебная должность"])
    very_hidden.sheet_state = "veryHidden"
    wb.save(path)
    wb.close()

    rows = parse_workbook(path)

    assert [(row["sheet_name"], row["employee_name"]) for row in rows] == [
        ("Т-7", "Иванов Иван Иванович"),
    ]


def test_formula_cells_without_cached_values_are_not_imported_as_employee_names(tmp_path):
    path = tmp_path / "formula-names.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Т-7"
    ws.append(["ФИО", "Должность"])
    ws.append(['="Иванов Иван Иванович"', "Специалист"])
    ws.append(["Петров Пётр Петрович", "Бухгалтер"])
    wb.save(path)
    wb.close()

    rows = parse_workbook(path)

    # openpyxl does not calculate formulas; with data_only=True an uncached formula is blank.
    assert [row["employee_name"] for row in rows] == ["Петров Пётр Петрович"]



def test_import_preserves_original_fio_with_employment_annotation():
    path = Path(__file__).parent / "annotated-fio-test.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.title = "Т-7"
    ws.append(["ФИО", "Должность"])
    ws.append(["Смирнова Марина Викторовна (внутр.совм.)", "Бухгалтер"])
    ws.append(["Виноградова Наталья Михайловна (внешн.совм.)", "Специалист"])
    wb.save(path)
    try:
        rows = parse_workbook(path)
        assert [row["employee_name"] for row in rows] == [
            "Смирнова Марина Викторовна (внутр.совм.)",
            "Виноградова Наталья Михайловна (внешн.совм.)",
        ]
    finally:
        path.unlink(missing_ok=True)
