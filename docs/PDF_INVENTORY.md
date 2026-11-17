# PrepFreeX — PDF Inventory & Duplicate Audit Report

## 1. Executive Summary

A comprehensive, recursive inspection was conducted on all local PDF documents within the PrepFreeX repository using the offline, zero-LLM inventory utility (`qbank inventory-pdfs`).

### Aggregate Inventory Metrics
- **Total PDF Files**: 5
- **Total Storage Size**: 32.56 MB
- **Total Pages Scanned**: 93
- **Pure Text-Layer Pages**: 17
- **Scanned (Raster Image) Pages**: 76
- **Figure-Heavy Pages**: 7
- **Unique Files (by SHA-256)**: 3
- **Duplicate Groups**: 2
- **Duplicate Redundant Files**: 2
- **Manifest Location**: `data/manifests/pdf_inventory.csv`

---

## 2. File-by-File Inventory Details

| File Name | SHA-256 | Size (MB) | Pages | Text Layer | Scanned Pages | Figures | Status | Duplicate Role |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `1. Alternating Current.pdf` | `88a07af43190ed0b...` | 0.54 | 3 | full | 0 | 3 | db_indexed | Primary |
| `10. PART TEST - 01 (04-12-2025).pdf` | `3a98bd06f3b64719...` | 15.18 | 38 | none (scanned) | 38 | 0 | unindexed | Primary |
| `Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf` | `88a07af43190ed0b...` | 0.54 | 3 | full | 0 | 3 | db_indexed | **Duplicate of `1. Alternating Current.pdf`** |
| `JEE Main Part Test-1_.pdf` | `3a98bd06f3b64719...` | 15.18 | 38 | none (scanned) | 38 | 0 | unindexed | **Duplicate of `10. PART TEST - 01...`** |
| `SYLLABUS.PDF` | `4ce0c562d245af95...` | 1.12 | 11 | full | 0 | 1 | unindexed | Unique |

---

## 3. Duplicate Detection & Provenance Findings

### Group 1: MathonGo Alternating Current Pilot
- **Primary**: `data/input/1. Alternating Current.pdf`
- **Duplicate**: `data/input/Alternating Current - JEE Main 2026 (Jan) - MathonGo.pdf`
- **Identical Hash**: `88a07af43190ed0b862483a159615dbc8e74bcaaadd8a2c9090a9fd36aa663ca`
- **Audit Recommendation**: Retain the canonical document entry for the primary file in `source_documents`. Map the second filename as a secondary entry in `question_sources` or purge the redundant file from disk.

### Group 2: ALLEN JEE Main Part Test 1
- **Primary**: `data/input/10. PART TEST - 01 (04-12-2025).pdf`
- **Duplicate**: `data/input/JEE Main Part Test-1_.pdf`
- **Identical Hash**: `3a98bd06f3b647192320be3e35eed52d8028b077fd0bdca86e9b181d0965ac3f`
- **Audit Recommendation**: The file is a 38-page scanned coaching test paper. Ingest once under the primary filename.

---

## 4. Ingestion Readiness & OCR Strategy

1. **Native Text PDFs**: `1. Alternating Current.pdf` and `SYLLABUS.PDF` contain complete digital font text layers, enabling sub-second extraction via PyMuPDF without visual OCR fallback.
2. **Scanned PDFs**: `10. PART TEST - 01 (04-12-2025).pdf` has no digital text layer (all 38 pages are scanned raster images). It requires page rendering to 200 DPI PNGs followed by multimodal extraction or OCR assisted text layout extraction.

