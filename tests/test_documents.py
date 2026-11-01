from rag.documents import DocumentChunk, SUPPORTED_EXTENSIONS


def test_document_chunk():
    chunk = DocumentChunk("example", "document.pdf", 0, 3)
    assert (chunk.source, chunk.page_number) == ("document.pdf", 3)


def test_formats():
    assert {".pdf", ".docx", ".pptx", ".xlsx", ".eml"}.issubset(SUPPORTED_EXTENSIONS)
