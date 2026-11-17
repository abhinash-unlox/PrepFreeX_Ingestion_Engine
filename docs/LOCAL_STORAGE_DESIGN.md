# PrepFreeX — Local Object Storage Design

## 1. Architectural Motivation

PostgreSQL is optimized for relational indexing, transactional consistency, and complex SQL joins. Storing multi-megabyte PDFs and uncompressed raster images as database bytea columns rapidly leads to:
1. Table and WAL bloat, degrading cache hit rates.
2. Significant memory pressure during concurrent reads.
3. Complex, high-overhead database backup and restore cycles.

PrepFreeX enforces strict externalization:
- **Relational Metadata**: Stored in PostgreSQL (`source_documents`, `document_pages`, `question_assets`).
- **Binary Payloads**: Stored in an S3-compatible object store (`LocalObjectStorage` locally, `S3ObjectStorage` in cloud environments).

---

## 2. Bucket and Key Hierarchy

PrepFreeX defines standard S3-style bucket names:

| Bucket Name | Purpose | Example Key Pattern | Stored Mime Types |
| :--- | :--- | :--- | :--- |
| `source-pdfs` | Raw immutable source PDF files | `full_tests/{sha256}.pdf` | `application/pdf` |
| `page-snapshots` | Rendered 200 DPI PNG images of PDF pages | `{job_id}/page_{page_num:03d}.png` | `image/png` |
| `question-diagrams` | Extracted circuit, optics, and geometry figures | `figures/{sha256}.png` | `image/png`, `image/webp` |
| `job-bundles` | Exported question JSON bundles and manifests | `jobs/{job_id}/question_import.json` | `application/json` |

---

## 3. `LocalObjectStorage` Implementation

The local object storage provider maps buckets to filesystem subdirectories under `data/object_store/local/`:

```
data/object_store/local/
├── source-pdfs/
│   ├── 88a07af43190ed0b862483a159615dbc8e74bcaaadd8a2c9090a9fd36aa663ca.pdf
│   └── 88a07af43190ed0b862483a159615dbc8e74bcaaadd8a2c9090a9fd36aa663ca.pdf.meta.json
├── question-diagrams/
│   ├── figures/
│   │   ├── c9a2d8...png
│   │   └── c9a2d8...png.meta.json
└── page-snapshots/
```

### Key Technical Properties:
1. **Directory Traversal Defense**: All input paths are normalized and resolved; keys attempting to break out of the bucket root raise a `ValueError`.
2. **Atomic Writes**: Incoming binary streams are written to a process-isolated `.tmp_{pid}` file and renamed in a single filesystem atomic operation upon completion.
3. **Streaming Transfers**: `get_object_stream` yields 64 KB chunks, allowing 500 MB+ PDFs to be inspected and transferred without unbounded RAM consumption.
4. **Metadata Sidecars**: Every stored object has a companion `.meta.json` containing SHA-256 hash, byte size, detected MIME type, and custom tags.

---

## 4. Cloud Migration Interface (`S3ObjectStorage`)

The common abstract interface `BaseObjectStorage` allows switching between local storage and cloud S3/R2 with a single environment variable (`STORAGE_BACKEND=s3`):

```python
from packages.shared.storage import get_storage

# Local development (default)
storage = get_storage("local", root_dir="data/object_store/local")

# Cloud production
storage = get_storage("s3")
```
No application code changes are required when promoting from local Windows environments to AWS S3 or Cloudflare R2.

