"""Fill planned vacation periods into a copy of the organization's original workbook."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


ALIASES = {
    "employee_name": {
        "фио", "ф и о", "фамилия имя отчество", "фамилия имя",
        "фамилия инициалы", "фамилия и инициалы", "работник", "сотрудник",
    },
    "duration": {
        "количество календарных дней", "кол во календарных дней",
        "количество дней", "кол во дней", "число календарных дней",
        "продолжительность отпуска",
    },
    "start_date": {
        "запланированная дата", "планируемая дата", "предполагаемая дата",
        "плановая дата начала отпуска", "дата начала отпуска",
        "запланированная дата начала отпуска",
    },
}


def normalize(value: object) -> str:
    import re
    if value is None:
        return ""
    value = str(value).strip().lower().replace("ё", "е")
    return re.sub(r"[^а-яa-z0-9]+", " ", value).strip()


def find_layout(ws: Worksheet, scan_rows: int = 40):
    for row_no in range(1, min(ws.max_row, scan_rows) + 1):
        columns = {"employee_name": [], "duration": [], "start_date": []}
        for cell in ws[row_no]:
            value = normalize(cell.value)
            for field, aliases in ALIASES.items():
                if value in aliases:
                    columns[field].append(cell.column)
        if columns["employee_name"] and columns["duration"] and columns["start_date"]:
            return row_no, columns
    return None


def fill_workbook(
    source_path: str | Path,
    destination_path: str | Path,
    rows: Iterable[dict],
    periods_by_employee: dict[str, list[dict]],
) -> dict:
    source_path = Path(source_path)
    destination_path = Path(destination_path)
    keep_vba = source_path.suffix.lower() == ".xlsm"
    workbook = load_workbook(
        source_path, data_only=False, keep_vba=keep_vba, keep_links=True
    )
    row_lookup = {(r["sheet_name"], int(r["row_number"])): r for r in rows}
    layouts = {}
    try:
        for sheet_name in {key[0] for key in row_lookup}:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"В оригинале отсутствует лист «{sheet_name}».")
            layout = find_layout(workbook[sheet_name])
            if not layout:
                raise ValueError(
                    f"На листе «{sheet_name}» не найдены заголовки ФИО, "
                    "количества календарных дней и запланированной даты."
                )
            header_row, columns = layout
            if len(columns["duration"]) != len(columns["start_date"]):
                raise ValueError(
                    f"На листе «{sheet_name}» число столбцов длительности "
                    "не совпадает с числом столбцов запланированной даты."
                )
            layouts[sheet_name] = (header_row, columns)

        filled_rows = 0
        filled_periods = 0
        for (sheet_name, row_number), row in row_lookup.items():
            if not row.get("employee_id"):
                continue
            periods = periods_by_employee.get(str(row["employee_id"]), [])
            if not periods:
                continue
            header_row, columns = layouts[sheet_name]
            if row_number <= header_row:
                raise ValueError(
                    f"Строка {row_number} листа «{sheet_name}» находится выше заголовка."
                )
            slots = min(len(columns["duration"]), len(columns["start_date"]))
            if len(periods) > slots:
                raise ValueError(
                    f"Для сотрудника «{row.get('employee_name') or row['employee_id']}» "
                    f"на листе «{sheet_name}» указано периодов: {len(periods)}, "
                    f"а в шаблоне предусмотрено пар столбцов: {slots}. "
                    "Экспорт остановлен, чтобы не потерять периоды."
                )
            ws = workbook[sheet_name]
            for index, period in enumerate(periods):
                duration_col = columns["duration"][index]
                start_col = columns["start_date"][index]
                duration_cell = ws.cell(row=row_number, column=duration_col)
                start_cell = ws.cell(row=row_number, column=start_col)
                if duration_cell.__class__.__name__ == "MergedCell" or start_cell.__class__.__name__ == "MergedCell":
                    raise ValueError(
                        f"Ячейки периода в строке {row_number} листа «{sheet_name}» "
                        "являются частью объединения. Требуется настройка шаблона."
                    )
                duration_cell.value = int(period["duration_days"])
                start_cell.value = period["start_date"]
                filled_periods += 1
            filled_rows += 1

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(destination_path)
        return {"filled_rows": filled_rows, "filled_periods": filled_periods}
    finally:
        workbook.close()
