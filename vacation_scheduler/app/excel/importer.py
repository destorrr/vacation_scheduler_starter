import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


HEADER_ALIASES = {
    "employee_name": {
        "фио", "ф и о", "фамилия имя отчество", "фамилия имя", "работник",
        "фамилия имя отчество работника", "фамилия инициалы", "сотрудник",
        "ф и о работника", "фамилия и инициалы",
    },
    "personnel_number": {
        "табельный номер", "табельный", "таб номер", "табельный номер работника",
        "номер по табелю", "табельный номер сотрудника",
    },
    "department_name": {
        "структурное подразделение", "подразделение", "отдел", "служба",
        "наименование структурного подразделения",
    },
    "position_name": {
        "должность", "профессия должность", "наименование должности",
        "должность специальность профессия", "должность специальность профессия по штатному расписанию",
    },
}


def normalize_header(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().lower().replace("ё", "е")
    return re.sub(r"[^а-яa-z0-9]+", " ", text).strip()


def clean_cell(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = " ".join(str(value).replace("\u00a0", " ").split()).strip()
    return text or None


def detect_header(ws, scan_rows: int = 30) -> tuple[int, dict[str, int]] | None:
    for row_idx in range(1, min(ws.max_row, scan_rows) + 1):
        found: dict[str, int] = {}
        for cell in ws[row_idx]:
            normalized = normalize_header(cell.value)
            for field, aliases in HEADER_ALIASES.items():
                if normalized in aliases and field not in found:
                    found[field] = cell.column
        if "employee_name" in found:
            return row_idx, found
    return None


def parse_workbook(source: str | Path) -> list[dict]:
    try:
        workbook = load_workbook(source, read_only=False, data_only=True)
    except Exception as exc:
        raise ValueError(
            "Файл не удалось прочитать как книгу Excel. Проверьте, что файл не повреждён и не защищён паролем."
        ) from exc

    parsed: list[dict] = []
    detected_sheets = 0
    try:
        for ws in workbook.worksheets:
            # Hidden and very-hidden worksheets are not part of the visible T-7 input.
            if ws.sheet_state != "visible":
                continue
            header = detect_header(ws)
            if not header:
                continue
            detected_sheets += 1
            header_row, columns = header
            previous_department: str | None = None
            previous_position: str | None = None

            for row_idx in range(header_row + 1, ws.max_row + 1):
                def value(field: str):
                    col = columns.get(field)
                    return clean_cell(ws.cell(row=row_idx, column=col).value) if col else None

                employee_name = value("employee_name")
                department = value("department_name") or previous_department
                position = value("position_name") or previous_position
                personnel_number = value("personnel_number")

                if department:
                    previous_department = department
                if position:
                    previous_position = position
                if not employee_name:
                    continue

                normalized_name = normalize_header(employee_name)
                if normalized_name in HEADER_ALIASES["employee_name"]:
                    continue
                if len(employee_name) < 5 or not re.search(r"[А-Яа-яЁё]", employee_name):
                    continue

                parsed.append({
                    "sheet_name": ws.title[:100],
                    "row_number": row_idx,
                    "department_name": department[:255] if department else None,
                    "position_name": position[:255] if position else None,
                    "employee_name": employee_name[:255],
                    "personnel_number": personnel_number[:50] if personnel_number else None,
                })
    finally:
        workbook.close()

    if not detected_sheets:
        raise ValueError(
            "Не удалось найти столбец ФИО. Поддерживаются заголовки «ФИО», "
            "«Фамилия, имя, отчество», «Сотрудник» и аналогичные. "
            "Проверьте строку заголовков и структуру шаблона."
        )
    if not parsed:
        raise ValueError("Заголовки найдены, но строки сотрудников не обнаружены.")
    return parsed
