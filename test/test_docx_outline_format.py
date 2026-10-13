import io
import zipfile

from docx_exporter import markdown_to_docx_bytes
from report_agents.report_style import sanitize_nested_report_chapter_headings


def _document_xml(payload: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return archive.read("word/document.xml").decode("utf-8")


def test_docx_exporter_restores_two_level_word_navigation():
    payload = markdown_to_docx_bytes(
        "# Report\n\n"
        "## 1. Summary\n\n"
        "### Overview\n\n"
        "#### Evidence notes\n\n"
        "## 2. Next\n\n"
        "### Follow-up",
        title="Delivery",
    )
    document = _document_xml(payload)

    assert document.count('w:pStyle w:val="Heading1"') == 2
    assert document.count('w:pStyle w:val="Heading2"') == 3
    assert 'w:pStyle w:val="Heading3"' not in document
    assert 'w:pStyle w:val="ToCTitle"' in document


def test_docx_exporter_does_not_promote_decimal_subsections_to_chapters():
    payload = markdown_to_docx_bytes(
        "# Report\n\n"
        "## 5. Industry Position\n\n"
        "## 5.1 Employee Feedback\n\n"
        "### 5.2 Competitor Feedback\n\n"
        "## 6. Business Verification\n\n",
        title="Delivery",
    )
    document = _document_xml(payload)

    assert document.count('w:pStyle w:val="Heading1"') == 2
    assert document.count('w:pStyle w:val="Heading2"') == 2
    assert 'w:t xml:space="preserve">5.1 Employee Feedback</w:t>' in document
    assert 'w:t xml:space="preserve">5.2 Competitor Feedback</w:t>' in document


def test_docx_exporter_filters_navigation_subheadings_by_report_outline():
    outline = [
        ("Summary", ["Overview", "Key findings"]),
        ("Business Verification", ["Operations table"]),
    ]
    payload = markdown_to_docx_bytes(
        "# Report\n\n"
        "## 1. Summary\n\n"
        "### Overview\n\n"
        "### Fact sorting\n\n"
        "### Key findings\n\n"
        "## 2. Business Verification\n\n"
        "### 2.1 Operations table\n\n"
        "### Analysis notes\n\n",
        title="Delivery",
        outline=outline,
    )
    document = _document_xml(payload)

    assert document.count('w:pStyle w:val="Heading1"') == 2
    assert document.count('w:pStyle w:val="Heading2"') == 3
    assert document.count('w:pStyle w:val="SectionHeading"') == 2
    assert 'w:t xml:space="preserve">Fact sorting</w:t>' in document
    assert 'w:t xml:space="preserve">Analysis notes</w:t>' in document
    assert 'w:t xml:space="preserve">2.1 Operations table</w:t>' not in document
    assert 'w:t xml:space="preserve">Operations table</w:t>' in document


def test_nested_duplicate_report_chapters_are_demoted():
    expected = {
        1: "Summary",
        2: "Market Definition",
        10: "Outlook",
        11: "Benchmark",
    }
    report = "\n".join(
        [
            "## 1. Summary",
            "summary",
            "## 2. Market Definition",
            "definition",
            "## 10. Outlook",
            "### Five-year trend",
            "## 1. Summary",
            "nested point",
            "## 2. Market Definition",
            "nested point",
            "## 11. Benchmark",
            "benchmark",
        ]
    )

    cleaned = sanitize_nested_report_chapter_headings(report, expected)

    assert cleaned.count("## 1. Summary") == 1
    assert cleaned.count("## 2. Market Definition") == 1
    assert "### Summary" in cleaned
    assert "### Market Definition" in cleaned
    assert "## 11. Benchmark" in cleaned
