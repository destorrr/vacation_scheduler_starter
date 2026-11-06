from openpyxl import Workbook

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
