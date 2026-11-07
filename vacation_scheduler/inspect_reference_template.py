from pathlib import Path
from openpyxl import load_workbook

path = Path("../ГРАФИК ОТПУСКОВ ООО  2026.xlsx")
wb = load_workbook(path, read_only=False, data_only=False)
print("WORKBOOK_SHEETS", wb.sheetnames)
for ws in wb.worksheets:
    print("SHEET", repr(ws.title), "DIMENSIONS", ws.max_row, ws.max_column)
    print("MERGED", [str(r) for r in ws.merged_cells.ranges][:100])
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 35), values_only=False):
        values = [(c.coordinate, str(c.value)[:100]) for c in row if c.value is not None]
        if values:
            print("ROW", row[0].row, values)
wb.close()
