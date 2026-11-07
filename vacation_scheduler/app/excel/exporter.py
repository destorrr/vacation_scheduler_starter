"""Export vacation periods into the shared Russian T-7 workbook layout."""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from openpyxl import load_workbook
from openpyxl.worksheet.worksheet import Worksheet


T7_HEADER_ALIASES = {
    "department_name": {"структурное подразделение"},
    "position_name": {"должность специальность профессия по штатному расписанию"},
    "employee_name": {"фамилия имя отчество"},
    "personnel_number": {"табельный номер"},
}


def normalize(value: object) -> str:
    import re
    if value is None:
        return ""
    value = str(value).strip().lower().replace("ё", "е")
    return re.sub(r"[^а-яa-z0-9]+", " ", value).strip()


def find_t7_layout(ws: Worksheet) -> tuple[int, dict[str, int]]:
    """Find the common T-7 header; employee fields occupy columns A:D."""
    for row_no in range(1, min(ws.max_row, 40) + 1):
        found: dict[str, int] = {}
        for cell in ws[row_no]:
            value = normalize(cell.value)
            for field, aliases in T7_HEADER_ALIASES.items():
                if value in aliases:
                    found[field] = cell.column
        if set(found) == set(T7_HEADER_ALIASES):
            expected = {
                "department_name": 1,
                "position_name": 2,
                "employee_name": 3,
                "personnel_number": 4,
            }
            if found != expected:
                raise ValueError(
                    f"Неожиданное расположение столбцов Т-7 на листе «{ws.title}»: {found}."
                )
            # In the shared form E is total calendar days and G is the
            # planned-date cell containing all periods as one text value.
            return row_no, found
    raise ValueError(
        f"На листе «{ws.title}» не найдена общая структура Т-7 "
        "с колонками A:D (подразделение, должность, ФИО, табельный номер)."
    )


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
    layouts: dict[str, int] = {}
    try:
        for sheet_name in {key[0] for key in row_lookup}:
            if sheet_name not in workbook.sheetnames:
                raise ValueError(f"В оригинале отсутствует лист «{sheet_name}».")
            header_row, _ = find_t7_layout(workbook[sheet_name])
            layouts[sheet_name] = header_row

        filled_rows = 0
        filled_periods = 0
        for (sheet_name, row_number), row in row_lookup.items():
            employee_id = row.get("employee_id")
            if not employee_id:
                continue
            header_row = layouts[sheet_name]
            if row_number <= header_row + 3:
                raise ValueError(
                    f"Строка {row_number} листа «{sheet_name}» находится в области заголовков Т-7."
                )
            ws = workbook[sheet_name]
            duration_cell = ws.cell(row=row_number, column=5)  # E: total days
            planned_cell = ws.cell(row=row_number, column=7)    # G: planned dates
            if duration_cell.__class__.__name__ == "MergedCell" or planned_cell.__class__.__name__ == "MergedCell":
                raise ValueError(
                    f"Ячейки E{row_number} или G{row_number} листа «{sheet_name}» "
                    "не являются верхними левыми ячейками объединения."
                )

            periods = sorted(
                periods_by_employee.get(str(employee_id), []),
                key=lambda item: (item["start_date"], item.get("sort_order", 0)),
            )
            # The original workbook may contain a previous year's/example
            # plan. Clear these two output fields before applying the new plan.
            if not periods:
                duration_cell.value = None
                planned_cell.value = None
                continue

            total_days = sum(int(period["duration_days"]) for period in periods)
            planned_text = " ".join(
                f"{period['start_date'].strftime('%d.%m.%Y')} ({int(period['duration_days'])})"
                for period in periods
            )
            duration_cell.value = total_days
            planned_cell.value = planned_text
            filled_rows += 1
            filled_periods += len(periods)

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        workbook.save(destination_path)
        return {"filled_rows": filled_rows, "filled_periods": filled_periods}
    finally:
        workbook.close()
