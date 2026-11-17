from engines.ingestion.segmenter import _split_generic
from engines.ingestion.pdf_reader import DocumentRecord, PageRecord


def test_generic_segmenter_tracks_subject_and_section_headers():
    pages = [
        PageRecord(1, "PART-1 : MATHEMATICS\nSECTION-I\n1) Matrix question stem with enough words to be parsed.\n(A) 1\n(B) 2\n2) Another mathematics question with enough words to be parsed.", "ocr", 150, 1, False),
        PageRecord(2, "SECTION-II\n1) Numerical mathematics question with enough words to be parsed.\nPART-2 : PHYSICS\nSECTION-I\n1) Physics question with enough words to be parsed.", "ocr", 150, 1, False),
    ]
    doc = DocumentRecord("paper.pdf", "0"*64, 2, "paper", {}, pages)
    from pathlib import Path
    result = _split_generic(doc)
    assert len(result) == 4
    assert result[0].subject == "mathematics" and result[0].source_section == "I"
    assert result[2].subject == "mathematics" and result[2].source_section == "II"
    assert result[3].subject == "physics" and result[3].source_section == "I"
