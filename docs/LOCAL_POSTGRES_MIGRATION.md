# Local Native PostgreSQL 18 Migration Guide

## 1. Overview
This document details the configuration and architecture migration of the PrepFreeX Ingestion Engine from a Docker-centric setup to a native local PostgreSQL 18.6 installation on Windows.

## 2. Environment Specifications
- **Operating System**: Windows 11
- **PostgreSQL Version**: PostgreSQL 18.6 (x86_64-windows)
- **Host**: `127.0.0.1` (localhost)
- **Port**: `5432`
- **Database**: `prepfreex`
- **Application User**: `prepfreex_user`
- **Extensions Installed**: `plpgsql`, `pgcrypto`, `pg_trgm`

## 3. Configuration & Credentials Management
Native PostgreSQL settings are configured in `.env` and consumed via `prepfreex_ingest.config.Settings`:

| Environment Variable | Description | Value in Production / Local |
| :--- | :--- | :--- |
| `POSTGRES_HOST` | Database Host address | `127.0.0.1` |
| `POSTGRES_PORT` | Database Port | `5432` |
| `POSTGRES_DB` | Target Database name | `prepfreex` |
| `POSTGRES_USER` | Least-privilege application user | `prepfreex_user` |
| `POSTGRES_PASSWORD` | User password | Loaded from `.env` (never committed/logged) |
| `DATABASE_URL` | Complete connection URI | `postgresql://prepfreex_user:<escaped_pw>@127.0.0.1:5432/prepfreex` |

> [!IMPORTANT]
> The application user `prepfreex_user` is strictly used for all schema migrations, seeding, and ingestion runs. The `postgres` superuser is never used by the application runtime.
> When passwords contain reserved URL characters (such as `@`, `:`, `/`), `DATABASE_URL` is safely escaped using `urllib.parse.quote_plus`.

## 4. Docker Assumptions Identified & Remediations

| Component | Previous Docker Assumption | Native PostgreSQL Adaptation |
| :--- | :--- | :--- |
| **Connection Check (`qbank db-check`)** | Inspected `docker info` and container status `prepfreex-postgres` on connection failure. | Directly tests psycopg connection to native host:port, tests `server_version`, extension availability, and table creation privileges. Docker checks removed from primary path. |
| **Migrations (`qbank migrate`)** | Assumed Docker volume container port binding. | Runs against `DATABASE_URL` with idempotent `CREATE TABLE IF NOT EXISTS schema_migrations` and transaction-scoped execution. |
| **Seed Taxonomy (`qbank seed-taxonomy`)** | Connected via container network. | Connects directly to local native instance via `DATABASE_URL`. |
| **Docker CLI Helpers (`db-up`, `db-down`, etc.)** | Documented as the only way to manage the database. | Native PostgreSQL runs as a standard Windows service (`postgresql-x64-18`). Docker helper commands remain available as optional utilities for container users, but are not required for native execution. |
| **Ingestion Pipeline Persistence** | Assumed Docker daemon availability for jobs. | Ingestion persistence connects natively via `DATABASE_URL` and records jobs, pages, candidates, and canonical questions. |

## 5. Verification Commands

### Check native database connection and extensions
```powershell
python -m prepfreex_ingest.cli db-check
```
Expected output:
```
Database connection successful!
PostgreSQL Version: 18.6
pgcrypto extension: Available/Installed
pg_trgm extension:  Available/Installed
Table privileges:  Verified
```

### Apply schema migrations
```powershell
python -m prepfreex_ingest.cli migrate
```

### Seed JEE Main 2027 Taxonomy
```powershell
python -m prepfreex_ingest.cli seed-taxonomy --file db/seeds/jee_main_2027_taxonomy_v2.json --persist
```

### Run Ingestion against Native PostgreSQL
```powershell
python -m prepfreex_ingest.cli ingest-pdf "data/input/1. Alternating Current.pdf"
```

