"""Small shared parser for the folder API and its n8n clients; no OCR/downloads."""

import csv
import io
import json
import re
import sys
from pathlib import Path

PARSER_VERSION = "folder-v4-structured-rows"
COMPATIBLE_PARSERS = (
    "folder-v1-pypdf-text-csv-labels",
    "folder-v2-docx-rtf-locations",
    "folder-v3-pptx-locations",
    PARSER_VERSION,
)
FORMATS = {".txt", ".csv", ".pdf", ".docx", ".rtf", ".pptx", ".xlsx"}


class DocumentError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def parse_pages(data: bytes, name: str, max_pages=200, max_chars=2_000_000):
    """Return (text, physical PDF page or None), without crossing PDF pages."""
    suffix = Path(name).suffix.lower()
    if suffix not in FORMATS:
        raise DocumentError("unsupported", "Use TXT, CSV, text PDF, DOCX, RTF, PPTX or XLSX.")
    if not data:
        raise DocumentError("empty", "The file is empty.")
    pages = []
    if suffix == ".pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise DocumentError("encrypted", "Encrypted PDFs are not supported.")
            if len(reader.pages) > max_pages:
                raise DocumentError("page_limit", "PDF exceeds the configured page limit.")
            for number, page in enumerate(reader.pages, 1):
                text = page.extract_text() or ""
                if not text.strip():
                    raise DocumentError(
                        "textless_pdf",
                        "PDF has a scanned or empty page. Text on every page is required; OCR is not provided.",
                    )
                pages.append((text, number))
                if sum(len(t) for t, _ in pages) > max_chars:
                    raise DocumentError(
                        "text_limit", "Extracted text exceeds the configured limit."
                    )
        except DocumentError:
            raise
        except Exception as error:
            raise DocumentError(
                "malformed_pdf", "PDF could not be parsed. Export a valid text PDF."
            ) from error
    else:
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise DocumentError("encoding", "Save text and CSV files as UTF-8.") from error
        if "\x00" in text:
            raise DocumentError("binary_text", "The file contains binary data, not UTF-8 text.")
        if suffix == ".csv":
            try:
                rows = csv.reader(io.StringIO(text, newline=""), strict=True)
                headers = next(rows, [])
                if (
                    not headers
                    or any(not h.strip() for h in headers)
                    or len(set(headers)) != len(headers)
                ):
                    raise DocumentError("csv_header", "CSV needs nonempty, unique column headers.")
                labeled = []
                for i, row in enumerate(rows, 1):
                    if not row:
                        continue
                    if len(row) != len(headers):
                        raise DocumentError(
                            "csv_columns", f"CSV data row {i} has the wrong number of fields."
                        )
                    # JSON quoting keeps delimiters/newlines in values unambiguous.
                    labeled.append(
                        "Row "
                        + str(i)
                        + ": "
                        + "; ".join(
                            f"{json.dumps(k, ensure_ascii=False)}: {json.dumps(v, ensure_ascii=False)}"
                            for k, v in zip(headers, row, strict=True)
                        )
                    )
                text = "\n".join(labeled)
            except csv.Error as error:
                raise DocumentError(
                    "malformed_csv", "CSV quoting or field size is invalid."
                ) from error
        pages = [(text, None)]
    if not pages or not any(t.strip() for t, _ in pages):
        raise DocumentError("empty", "No usable text or CSV data rows were found.")
    if sum(len(t) for t, _ in pages) > max_chars:
        raise DocumentError("text_limit", "Extracted text exceeds the configured limit.")
    return pages


def chunks_from_pages(pages, size=900, overlap=150, max_chunks=3000):
    if isinstance(pages, dict):
        from .structured_parser import chunks_from_blocks

        return chunks_from_blocks(pages, size, overlap, max_chunks)
    chunks = []
    for text, page in pages:
        text = re.sub(r"\s+", " ", text).strip()
        for start in range(0, len(text), size - overlap):
            chunks.append(
                {"text": text[start : start + size], "page_number": page, "chunk": len(chunks)}
            )
            if len(chunks) > max_chunks:
                raise DocumentError("chunk_limit", "Document exceeds the configured chunk limit.")
            if start + size >= len(text):
                break
    return chunks


def parse_managed(data, name, max_pages=200, max_chars=2_000_000):
    if Path(name).suffix.lower() in {".docx", ".rtf", ".pptx", ".xlsx"}:
        from .structured_parser import parse_structured

        return parse_structured(data, name, max_chars, max_pages)
    if Path(name).suffix.lower() == ".csv":
        from .tabular_parser import csv_blocks

        return csv_blocks(data, max_chars)
    pages = parse_pages(data, name, max_pages, max_chars)
    if Path(name).suffix.lower() == ".txt":
        from .structured_parser import Blocks

        out = Blocks(max_chars)
        section = ""
        # Keep paragraphs and Markdown headings intact instead of flattening first.
        for number, paragraph in enumerate(
            re.split(r"\n\s*\n|(?=^#{1,6} )", pages[0][0], flags=re.MULTILINE), 1
        ):
            lines = paragraph.strip().splitlines()
            if lines and re.match(r"^#{1,6} ", lines[0]):
                section = re.sub(r"^#{1,6} +", "", lines[0])
            out.add(
                paragraph,
                f"Section {section or '(untitled)'} · paragraph {number}",
                section=section,
                paragraph=number,
            )
        return out.result()
    return pages


def main():
    # The worker starts this child with a wall deadline. OS limits bound hostile PDF expansion.
    if sys.platform != "linux":
        raise SystemExit("Resource-isolated ingestion requires Linux; use the Docker workspace.")
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024**2, 512 * 1024**2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (32 * 1024**2, 32 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    path, name, output, max_pages, max_chars, max_chunks = sys.argv[1:]
    try:
        pages = parse_managed(Path(path).read_bytes(), name, int(max_pages), int(max_chars))
        result = {
            "chunks": chunks_from_pages(pages, max_chunks=int(max_chunks)),
            "warnings": pages.get("warnings", []) if isinstance(pages, dict) else [],
        }
    except DocumentError as error:
        result = {"error": error.code, "message": str(error)}
    except Exception:  # noqa: BLE001 - isolated parser returns sanitized error only
        result = {"error": "parser_failed", "message": "Parser failed within its resource limits."}
    Path(output).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
