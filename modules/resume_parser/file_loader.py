import pymupdf
import docx


def extract_text_from_pdf(pdf_path):
    """Extract text from a PDF resume."""

    doc = pymupdf.open(pdf_path)

    text = ""

    for page in doc:
        text += page.get_text()

    doc.close()

    return text


def extract_text_from_docx(docx_path):
    """Extract text from a DOCX resume."""

    doc = docx.Document(docx_path)

    text = "\n".join(
        paragraph.text
        for paragraph in doc.paragraphs
        if paragraph.text.strip()
    )

    return text


def extract_text(file_path):
    """Extract text based on the resume file format."""

    file_path = str(file_path).lower()

    if file_path.endswith(".pdf"):
        return extract_text_from_pdf(file_path)

    elif file_path.endswith(".docx"):
        return extract_text_from_docx(file_path)

    else:
        raise ValueError(
            "Unsupported file format. Please upload a PDF or DOCX file."
        )