# PostgreSQL Setup with Docker for PrepFreeX Ingestion Engine

This guide walks through setting up the local PostgreSQL database using Docker, inspecting data, performing backups/restores, and troubleshooting common connection issues.

---

## 1. Prerequisites and Docker Installation

### Windows Installation
1. Download and install **Docker Desktop for Windows** from [docker.com](https://www.docker.com/products/docker-desktop/).
2. **WSL2 Note**: Ensure the **WSL 2 backend** is enabled during Docker Desktop installation:
   - In Docker Desktop, go to **Settings > General > Use the WSL 2 based engine**.
   - If prompted, update your Linux kernel with:
     ```powershell
     wsl --update
     ```
3. Start Docker Desktop and wait until the whale icon in your system tray shows **"Docker Desktop running"**.

---

## 2. Configuration (`.env`)

Copy the template configuration file:
```bash
cp .env.example .env
```
Ensure your database credentials match:
```ini
POSTGRES_USER=prepfreex
POSTGRES_PASSWORD=prepfreex_dev
POSTGRES_DB=prepfreex_qbank
POSTGRES_PORT=5432
DATABASE_URL=postgresql://prepfreex:prepfreex_dev@127.0.0.1:5432/prepfreex_qbank
```

---

## 3. Starting and Checking the Database

Start the PostgreSQL container:
```bash
qbank db-up
```
This runs `docker compose up -d` using `pgvector/pgvector:pg16` bound to `127.0.0.1:5432` and waits until the container is healthy.

Verify database availability and required extensions:
```bash
qbank db-check
```
Expected output:
```text
Database connection successful!
PostgreSQL Version: 16.x
pgcrypto extension: Available/Installed
pg_trgm extension:  Available/Installed
```

Run schema migrations:
```bash
qbank migrate
```

Seed the taxonomy:
```bash
qbank seed-taxonomy --file db/seeds/jee_main_2027_taxonomy_v2.json --persist
```

---

## 4. Looking at the Data (`qbank db-shell`)

Open an interactive `psql` console inside the container:
```bash
qbank db-shell
```

### 5 Useful Example SQL Queries:

#### 1. Question counts by status and verification state
```sql
SELECT
    status,
    answer_key_verified,
    explanation_verified,
    count(*) AS total_questions
FROM questions
GROUP BY status, answer_key_verified, explanation_verified;
```

#### 2. Check student test-eligible questions
```sql
SELECT
    id,
    public_id,
    source_question_key,
    subject,
    question_type,
    status
FROM v_test_eligible_questions;
```

#### 3. Distribution of questions across subjects and units
```sql
SELECT
    q.subject,
    t.code AS unit_code,
    t.name AS unit_name,
    count(q.id) AS question_count
FROM questions q
JOIN question_tags qt ON qt.question_id = q.id AND qt.is_primary = true
JOIN taxonomy t ON t.id = qt.taxonomy_id
GROUP BY q.subject, t.code, t.name
ORDER BY q.subject, t.code;
```

#### 4. Flagged questions (key mismatches or figures pending)
```sql
SELECT
    public_id,
    source_question_key,
    figure_status,
    answer_verification_notes,
    flags
FROM questions
WHERE figure_status = 'pending'
   OR flags ? 'key_mismatch';
```

#### 5. Open taxonomy proposals waiting for SME resolution
```sql
SELECT
    id,
    parent_code,
    proposed_name,
    rationale,
    example_question_keys,
    created_at
FROM taxonomy_proposals
WHERE status = 'open';
```

---

## 5. Backup, Restore, and Reset

### Backup
Create a timestamped SQL dump in `backups/`:
```bash
qbank db-backup
```
Outputs to `backups/YYYYMMDD_HHMM.sql`.

### Restore
Restore from an existing backup:
```bash
qbank db-restore backups/20261110_1200.sql
```

### Stop Database (Keep Data)
```bash
qbank db-down
```
Data survives in the named Docker volume `prepfreex_pgdata`.

### Complete Reset (Delete Data)
```bash
qbank db-reset --yes
```
Stops the container and removes the named volume.

---

## 6. Troubleshooting Common Errors

| Error Message | Cause | Resolution |
| :--- | :--- | :--- |
| `Docker not running: Docker Desktop or daemon is not active` | Docker engine is stopped | Launch Docker Desktop and wait until the status is green/running. |
| `Container not started: Container 'prepfreex-postgres' is not running` | Compose service is not active | Run `qbank db-up` to launch and wait for the healthcheck. |
| `Connection refused: Port 5432 may be in use` | Another PostgreSQL instance or process is using port 5432 | Stop local PostgreSQL services or change `POSTGRES_PORT` in `.env`. |
| `Wrong password: Authentication failed for user` | Mismatch between `.env` and initialized volume | Check `POSTGRES_PASSWORD` in `.env`. If changed, run `qbank db-reset --yes` to re-initialize. |
| `Database missing: The target database does not exist` | Database name mismatch | Ensure `POSTGRES_DB` in `.env` is `prepfreex_qbank`. |

