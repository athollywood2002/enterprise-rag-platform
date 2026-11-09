"""Small genuine Office files for offline/container checks, never inference fixtures."""

from io import BytesIO


def office_files(formats, marker="original"):
    result = {}
    text = f"The recovery code is ORION. The owner is NetworkOps. {marker}"
    if ".docx" in formats:
        from docx import Document

        doc = Document()
        doc.add_heading("Office fixture", 1)
        doc.add_paragraph(text)
        table = doc.add_table(rows=1, cols=2)
        table.cell(0, 0).text = "Name"
        table.cell(0, 1).text = "Budget USD"
        out = BytesIO()
        doc.save(out)
        result["docx"] = out.getvalue()
    if ".rtf" in formats:
        result["rtf"] = ("{\\rtf1\\ansi " + text + "}").encode()
    if ".pptx" in formats:
        from pptx import Presentation

        deck = Presentation()
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = text
        out = BytesIO()
        deck.save(out)
        result["pptx"] = out.getvalue()
    if ".xlsx" in formats:
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "Assets"
        sheet.append(["ID", "Details"])
        sheet.append(["R1", text])
        out = BytesIO()
        book.save(out)
        result["xlsx"] = out.getvalue()
    return result
