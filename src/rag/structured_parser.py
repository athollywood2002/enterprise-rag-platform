"""Bounded text-only Office extraction. Never executes embedded content."""

import io
import re
import zipfile
from pathlib import Path

from .folder_parser import DocumentError

MAX_PARTS = 4096
MAX_EXPANDED = 64 * 1024**2
MAX_BLOCKS = 10000


def package(data, expected):
    if data.startswith(b"\xd0\xcf\x11\xe0"):
        raise DocumentError(
            "encrypted_or_legacy",
            "Encrypted Office or legacy binary file. Export an unencrypted modern Office file.",
        )
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        parts = archive.infolist()
        if len(parts) > MAX_PARTS or sum(p.file_size for p in parts) > MAX_EXPANDED:
            raise DocumentError(
                "expansion_limit", "Office package exceeds part/expanded-byte limits."
            )
        if len({p.filename for p in parts}) != len(parts):
            raise DocumentError("malformed_office", "Office package contains duplicate parts.")
        for p in parts:
            if p.flag_bits & 1:
                raise DocumentError("encrypted", "Encrypted Office packages are unsupported.")
            if p.file_size > 32 * 1024**2 or p.file_size > max(p.compress_size, 1) * 200:
                raise DocumentError(
                    "expansion_limit", "Office package expansion exceeds safe limits."
                )
            if p.filename.endswith((".xml", ".rels")):
                xml = archive.read(p).replace(b"\x00", b"")
                if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                    raise DocumentError("unsafe_xml", "DTD/entity declarations are unsupported.")
            if "vbaproject" in p.filename.lower():
                raise DocumentError(
                    "macros", "Macro-enabled content is unsupported. Export a macro-free file."
                )
        if expected not in archive.namelist():
            raise DocumentError(
                "malformed_office", "File contents do not match its Office extension."
            )
        return archive
    except DocumentError:
        raise
    except (zipfile.BadZipFile, OSError, RuntimeError, ValueError) as error:
        raise DocumentError(
            "malformed_office", "Invalid Office package. Export a fresh unencrypted file."
        ) from error


class Blocks:
    def __init__(self, max_chars):
        self.items = []
        self.warnings = set()
        self.count = 0
        self.max_chars = max_chars

    def add(self, text, location, **metadata):
        if not text.strip():
            return
        self.count += len(text)
        if self.count > self.max_chars or len(self.items) >= MAX_BLOCKS:
            raise DocumentError("text_limit", "Document exceeds extracted text/block limits.")
        self.items.append({"text": text, "page_number": None, "location": location, **metadata})

    def result(self):
        if not self.items:
            raise DocumentError(
                "empty",
                "No usable text found; image-only content requires OCR, which is not provided.",
            )
        return {"blocks": self.items, "warnings": sorted(self.warnings)}


def docx_blocks(data, max_chars):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    archive = package(data, "word/document.xml")
    body = archive.read("word/document.xml")
    # Reject revisions rather than silently choosing between inserted/deleted text.
    if re.search(rb"<w:(?:ins|del|moveFrom|moveTo)\b", body):
        raise DocumentError(
            "tracked_changes", "Accept or reject tracked changes in Word, then save and reimport."
        )
    doc = Document(io.BytesIO(data))
    local_names = {element.tag.rsplit("}", 1)[-1] for element in doc.element.body.iter()}
    if local_names & {"ins", "del", "moveFrom", "moveTo"} or any(
        n.endswith("PrChange") for n in local_names
    ):
        raise DocumentError(
            "tracked_changes", "Accept or reject tracked changes in Word, then save and reimport."
        )
    if local_names & {"txbxContent", "altChunk", "sdt", "fldSimple", "instrText"}:
        raise DocumentError(
            "unsupported_word_content",
            "Text boxes, content controls, linked content or fields require text/PDF export.",
        )
    out = Blocks(max_chars)
    names = archive.namelist()
    for marker, warning in [
        ("word/comments", "Comments are excluded."),
        ("word/header", "Headers are excluded."),
        ("word/footer", "Footers are excluded."),
        ("word/footnotes", "Footnotes are excluded."),
        ("word/endnotes", "Endnotes are excluded."),
        ("word/embeddings/", "Embedded objects are excluded; no object is executed."),
        ("word/media/", "Images are excluded; no OCR."),
    ]:
        if any(n.startswith(marker) for n in names):
            out.warnings.add(warning)
    if re.search(rb"<w:(?:txbxContent|altChunk|sdt|fldSimple)\b", body) or b"<w:instrText" in body:
        raise DocumentError(
            "unsupported_word_content",
            "Text boxes, content controls, linked content or fields require export to plain text/PDF for complete extraction.",
        )
    section = ""
    paragraph = 0
    table = 0
    for element in doc.iter_inner_content():
        if isinstance(element, Paragraph):
            paragraph += 1
            text = element.text
            if element.style and element.style.name.startswith("Heading"):
                section = text
            out.add(
                text,
                f"Section {section or '(untitled)'} · paragraph {paragraph}",
                section=section,
                paragraph=paragraph,
            )
        elif isinstance(element, Table):
            table += 1
            # Nested tables require explicit export rather than silently dropping their values.
            if any(cell.tables for row in element.rows for cell in row.cells):
                raise DocumentError(
                    "nested_table", "Nested Word tables require flattening or text/PDF export."
                )
            headers = [cell.text for cell in element.rows[0].cells] if element.rows else []
            for rn, row in enumerate(element.rows, 1):
                cells, seen = [], set()
                for cn, cell in enumerate(row.cells, 1):
                    if cell._tc in seen:
                        continue
                    seen.add(cell._tc)
                    texts = [p.text for p in cell.paragraphs]
                    label = f"Column {cn}"
                    if rn > 1 and cn <= len(headers) and headers[cn - 1]:
                        label += f" ({headers[cn - 1]})"
                    cells.append(label + ": " + "\n".join(texts))
                out.add(
                    " | ".join(cells),
                    f"Section {section or '(untitled)'} · table {table} · row {rn}",
                    section=section,
                    table=table,
                    row=rn,
                )
    return out.result()


def rtf_blocks(data, max_chars):
    from striprtf.striprtf import rtf_to_text

    raw = data.decode("latin-1")
    if not re.match(r"\s*\{\\rtf1\b", raw):
        raise DocumentError("malformed_rtf", "Not a valid RTF document. Export a fresh RTF file.")
    # Fail closed for content the text converter cannot represent completely.
    if re.search(
        r"\\(?:object|pict|field|annotation|header\w*|footer\w*|revised|deleted|trowd|footnote|bin)\b",
        raw,
    ):
        raise DocumentError(
            "unsupported_rtf_content",
            "RTF objects, images, fields, comments, headers/footers, revisions and tables require plain text or DOCX export.",
        )
    depth = 0
    for token in re.finditer(r"\\[\\{}]|[{}]", raw):
        if token.group() == "{":
            depth += 1
        if token.group() == "}":
            depth -= 1
        if depth < 0 or depth > 256:
            raise DocumentError("malformed_rtf", "RTF group nesting is invalid or too deep.")
    if depth:
        raise DocumentError("malformed_rtf", "RTF contains unclosed groups.")
    try:
        text = rtf_to_text(raw, errors="strict")
        # striprtf emits signed UTF-16 code units; join valid surrogate pairs.
        text = text.encode("utf-16-le", "surrogatepass").decode("utf-16-le")
    except (UnicodeError, ValueError, LookupError) as error:
        raise DocumentError("malformed_rtf", "RTF text encoding is invalid.") from error
    out = Blocks(max_chars)
    for number, paragraph in enumerate(text.splitlines(), 1):
        out.add(paragraph, f"Paragraph {number}", paragraph=number)
    return out.result()


def pptx_blocks(data, max_chars, max_slides):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    package(data, "ppt/presentation.xml")
    deck = Presentation(io.BytesIO(data))
    if len(deck.slides) > max_slides:
        raise DocumentError("slide_limit", "Presentation exceeds the configured slide limit.")
    out = Blocks(max_chars)
    for sn, slide in enumerate(deck.slides, 1):
        title = slide.shapes.title.text if slide.shapes.title is not None else ""
        if slide._element.get("show") == "0":
            out.warnings.add(f"Slide {sn}: hidden slide text is included.")
        if (
            slide.has_notes_slide
            and slide.notes_slide.notes_text_frame is not None
            and slide.notes_slide.notes_text_frame.text.strip()
        ):
            out.warnings.add(f"Slide {sn}: speaker notes are excluded.")

        def shapes(items, path="", sn=sn, title=title):
            for number, shape in enumerate(items, 1):
                identifier = path + str(number)
                location = f"Slide {sn} · shape {identifier}"
                if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
                    shapes(shape.shapes, identifier + ".")
                elif shape.has_table:
                    table = shape.table
                    header = " | ".join(cell.text for cell in table.rows[0].cells)
                    for rn, row in enumerate(table.rows, 1):
                        cells = [
                            f"Column {cn} ({table.cell(0, cn - 1).text}): {cell.text}"
                            for cn, cell in enumerate(row.cells, 1)
                            if not cell.is_spanned
                        ]
                        out.add(
                            " | ".join(cells),
                            location + f" · table row {rn}",
                            slide_number=sn,
                            section=title,
                            table=identifier,
                            row=rn,
                            table_header=header,
                        )
                elif shape.has_text_frame:
                    out.add(shape.text, location, slide_number=sn, section=title)
                else:
                    out.warnings.add(
                        f"{location}: non-text content (image/chart/object) is excluded; no OCR."
                    )

        before = len(out.items)
        shapes(slide.shapes)
        if len(out.items) == before:
            out.warnings.add(f"Slide {sn}: no extractable text.")
    return out.result()


def parse_structured(data, name, max_chars, max_pages=200):
    try:
        suffix = Path(name).suffix.lower()
        if suffix == ".docx":
            return docx_blocks(data, max_chars)
        if suffix == ".rtf":
            return rtf_blocks(data, max_chars)
        if suffix == ".pptx":
            return pptx_blocks(data, max_chars, max_pages)
        if suffix == ".xlsx":
            from .tabular_parser import xlsx_blocks

            return xlsx_blocks(data, max_chars)
        raise DocumentError("unsupported", "Unsupported structured format.")
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError(
            "malformed_office", "Document could not be parsed. Export a valid unencrypted file."
        ) from error


def chunks_from_blocks(document, size=900, overlap=150, max_chunks=3000):
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > overlap >= 0")
    chunks = []
    for block in document["blocks"]:
        if "cells" in block:
            from .tabular_parser import row_chunks

            for chunk in row_chunks(block, document.get("warnings", []), size):
                chunks.append({**chunk, "chunk": len(chunks)})
                if len(chunks) > max_chunks:
                    raise DocumentError(
                        "chunk_limit", "Document exceeds the configured chunk limit."
                    )
            continue
        text = block["text"].strip()
        context = block.get("section", "")
        if block.get("table_header") and len(block["table_header"]) <= 150:
            context += "\nTable headers: " + block["table_header"]
        # Long headings remain indexed as text, but are not repeated without bound.
        prefix = (context + "\n") if context and len(context) <= 200 and text != context else ""
        width = size - len(prefix)
        for start in range(0, len(text), width - min(overlap, width - 1)):
            part = text[start : start + width]
            chunk = {
                **block,
                "text": prefix + part,
                "chunk": len(chunks),
                "warnings": document.get("warnings", []),
            }
            if len(text) > width:
                chunk["continuation"] = start > 0
                chunk["location"] += f" · characters {start + 1}–{start + len(part)}"
            chunks.append(chunk)
            if len(chunks) > max_chunks:
                raise DocumentError("chunk_limit", "Document exceeds the configured chunk limit.")
            if start + width >= len(text):
                break
    return chunks
