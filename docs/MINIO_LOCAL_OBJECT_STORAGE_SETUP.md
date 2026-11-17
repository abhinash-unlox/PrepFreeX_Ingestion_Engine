# PrepFreeX — MinIO AIStor Local Object Storage Setup Guide

**Architecture Version:** 1.0.0 (MinIO AIStor Free & S3-Compatible Storage Layer)  
**Host Platform:** Windows 11 (AMD64 64-bit)  
**Binary Location:** `C:\tools\prepfreex-minio\minio.exe` | Client: `C:\tools\prepfreex-minio\mc.exe`  
**License File:** `C:\tools\prepfreex-minio\minio.license` (AIStor Free Tier)  
**Data Storage Root:** `C:\PrepFreeX\minio-data` (Git-ignored, independent of PostgreSQL)

---

## 1. Overview & Architecture

PrepFreeX uses an S3-compatible object storage architecture for managing extracted JEE question diagrams, circuit schematics, chemical reaction figures, coordinate plots, and generated question variant images.

```
┌───────────────────────────────────────────────────────────┐
│               PrepFreeX Application Engine                │
│ (FastAPI / Streamlit / Ingestion & Variation Pipelines)    │
└─────────────────────────────┬─────────────────────────────┘
                              │
                    engines/shared/storage.py
                   (get_storage() Abstraction)
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
[ Local MinIO AIStor Free ]              [ AWS S3 Production ]
Endpoint: http://127.0.0.1:9000         Standard AWS Regional Endpoint
Bucket: prepfreex-question-assets       Bucket: prepfreex-question-assets-prod
Addressing: Path-style                  Addressing: Virtual-hosted / Auto
Auth: Restricted App User               Auth: IAM Role / AWS Credentials
```

---

## 2. Installation Details

1. **Binaries:**
   - Server: MinIO AIStor AMD64 Windows release (`RELEASE.2026-09-19T17-05-25Z`).
   - Client: MinIO Client `mc.exe` (`RELEASE.2026-09-19T15-24-59Z`).
   - Dedicated tools directory: `C:\tools\prepfreex-minio\`.
2. **License Handling:**
   - AIStor requires an official license file passed via `--license`.
   - The verified Free Tier license token is stored locally at `C:\tools\prepfreex-minio\minio.license` and mirrored to `C:\PrepFreeX\minio-data\minio.license`.
   - **Crucial:** License files and credentials are git-ignored and never committed to source control.
3. **Data Directory:**
   - Stored at `C:\PrepFreeX\minio-data`.
   - Completely decoupled from PostgreSQL cluster files and repository working directories.

---

## 3. Server Startup & Management

### Automated Startup Script:
A pre-configured PowerShell startup script is provided at `C:\tools\prepfreex-minio\start-minio.ps1`:

```powershell
# C:\tools\prepfreex-minio\start-minio.ps1
$creds = Get-Content -Raw "C:\tools\prepfreex-minio\credentials.json" | ConvertFrom-Json
$env:MINIO_ROOT_USER = $creds.root_user
$env:MINIO_ROOT_PASSWORD = $creds.root_pwd

& "C:\tools\prepfreex-minio\minio.exe" server "C:\PrepFreeX\minio-data" `
    --address "127.0.0.1:9000" `
    --console-address "127.0.0.1:9001" `
    --license "C:\tools\prepfreex-minio\minio.license"
```

### Endpoints:
- **S3 API Endpoint:** `http://127.0.0.1:9000` (used by FastAPI and Boto3).
- **Web Console UI:** `http://127.0.0.1:9001` (for administrative browser inspection).

---

## 4. Security & Credential Management

In strict adherence to least-privilege security standards:

1. **Root Administrator:**
   - Username: `prepfreex_root_admin`
   - Role: Cluster administration and bucket provisioning only. Never used for application data traffic.
2. **Restricted Application Identity:**
   - Access Key: `prepfreex_app_user`
   - Attached Policy: `prepfreex_assets_policy` (`C:\tools\prepfreex-minio\prepfreex-assets-policy.json`)
   - Permissions: `s3:GetBucketLocation`, `s3:ListBucket`, `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject` limited exclusively to `arn:aws:s3:::prepfreex-question-assets/*`.
   - Cannot create/delete buckets or view other server resources.
3. **Bucket Access Policy:**
   - `prepfreex-question-assets` is strictly **private**.
   - Anonymous access is disabled (`Access permission is private`).
   - All retrieval operations require either authenticated Boto3 sessions or signed presigned URLs.

---

## 5. Storage Hierarchy & Object Key Conventions

Asset identifiers follow immutable, deterministic paths that do not break if questions are re-categorized in the academic taxonomy:

- **Canonical Question Stem Diagram:**
  `question-assets/{question_public_id}/{asset_id}/original.png`
- **Context Crop / Sub-figure:**
  `question-assets/{question_public_id}/{asset_id}/context-crop.png`
- **Web Optimization Thumbnail:**
  `question-assets/{question_public_id}/{asset_id}/thumbnail.webp`
- **Ingestion Candidate Asset:**
  `question-assets/candidates/{candidate_id}/{asset_id}/original.png`
- **Generated Variant Asset:**
  `question-assets/variants/{variant_public_id}/{asset_id}/original.png`

---

## 6. Application Configuration (`.env`)

```ini
# Object Storage Configuration (MinIO AIStor Free)
OBJECT_STORAGE_BACKEND=minio
MINIO_ENDPOINT=http://127.0.0.1:9000
MINIO_BUCKET=prepfreex-question-assets
MINIO_REGION=us-east-1
MINIO_ACCESS_KEY=prepfreex_app_user
MINIO_SECRET_KEY=App_575S-XRda41bhsZH1KnwSA0x2Q_5fPeV
MINIO_USE_SSL=false
MINIO_DATA_DIR=C:\PrepFreeX\minio-data

# AWS S3 Production (Switching requires zero code changes)
# OBJECT_STORAGE_BACKEND=aws_s3
# AWS_S3_BUCKET=prepfreex-question-assets-prod
# AWS_DEFAULT_REGION=us-east-1
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
```

---

## 7. Migration to AWS S3 (Production Zero-Code Switch)

The `engines/shared/storage.py` layer is built on `boto3` and `botocore`. To transition from local MinIO AIStor to AWS S3 in production:

1. Create the production S3 bucket: `prepfreex-question-assets-prod`.
2. Configure AWS IAM with the equivalent policy.
3. In the production `.env` (or ECS / Lambda environment variables), simply update:
   ```ini
   OBJECT_STORAGE_BACKEND=aws_s3
   AWS_S3_BUCKET=prepfreex-question-assets-prod
   AWS_DEFAULT_REGION=us-east-1
   ```
4. `get_storage()` will automatically initialize `S3ObjectStorage` using standard AWS endpoints and IAM instance profile/role credentials without modifying any application code.

---

## 8. Backup & Disaster Recovery

1. **MinIO Client Sync:**
   To synchronize local assets to an external backup disk or mirror:
   ```powershell
   & "C:\tools\prepfreex-minio\mc.exe" mirror localminio/prepfreex-question-assets "E:\PrepFreeX_Backups\question-assets"
   ```
2. **Filesystem Snapshot:**
   Because MinIO AIStor stores objects directly in standard directory structures under `C:\PrepFreeX\minio-data`, standard Windows VSS / volume backups can snapshot the object pool safely while the service is running.

