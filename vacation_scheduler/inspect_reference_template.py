from pathlib import Path
from openpyxl import load_workbook

path = Path("../ГРАФИК ОТПУСКОВ ООО  2026.xlsx")
wb = load_workbook(path, read_only=False, data_only=False)
print("WORKBOOK_SHEETS", wb.sheetnames)
for ws in wb.worksheets:
    print("SHEET", repr(ws.title), "DIMENSIONS", ws.max_row, ws.max_column)
    print("MERGED", [str(r) for r in ws.merged_cells.ranges][:100])
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, values_only=False):
        values = [(c.coordinate, str(c.value)[:100]) for c in row if c.value is not None]
        if values:
            print("ROW", row[0].row, values)
wb.close()

    print("ROW_HEIGHTS", [(i, ws.row_dimensions[i].height, ws.row_dimensions[i].hidden) for i in range(1, ws.max_row + 1) if ws.row_dimensions[i].height or ws.row_dimensions[i].hidden])
    print("COLUMN_WIDTHS", [(k, v.width, v.hidden) for k, v in ws.column_dimensions.items()])
