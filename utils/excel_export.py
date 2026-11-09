"""Small XLSX exports that work with the core openpyxl dependency."""
from io import BytesIO
from openpyxl import Workbook


def single_sheet_xlsx(sheet_name, rows, columns):
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(list(columns))
    for row in rows:
        sheet.append([row.get(column) for column in columns])
    workbook.save(output)
    output.seek(0)
    return output
