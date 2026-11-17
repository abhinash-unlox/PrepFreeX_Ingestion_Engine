# PrepFreeX — Assessment Engine & API Delivery Specification
**Backend Framework:** FastAPI (Python 3.14 / Uvicorn)  
**Database:** PostgreSQL 18.6 (`jee_mains_assesment_work`)  
**Object Storage:** MinIO S3 (`127.0.0.1:9000`)  
**Frontend Framework:** Next.js 14 / TypeScript (`v0-prepfreex-frontend`)  
**Router Source:** `apps/api/routes/assessment_engine.py`  

---

## 1. Supported Assessment Modes

| Mode Name | Default Questions | Default Duration | Allocation Blueprint |
| :--- | :---: | :---: | :--- |
| **Topic Practice** | 5 | 15 mins | 5 questions targeted to one specific topic code (e.g. `PHYS_U01_T02`). |
| **Chapter Test** | 20 | 60 mins | Balanced distribution across all 4 canonical topics of the chosen chapter. |
| **Mixed-topic Test** | 20 – 60 | 60 – 150 mins | Custom multi-chapter / multi-topic selection (5 questions per selected topic). |
| **Sectional Assessment** | 25 | 60 mins | 25 questions in a single subject (Physics, Chemistry, or Mathematics) mimicking the JEE section. |
| **Full-length Mock** | 75 | 180 mins | Complete JEE Main Paper 1 simulation: 25 Physics, 25 Chemistry, 25 Mathematics. |
| **Image Test** | 47 | 60 mins | Specialized test targeting questions with diagrams and figures from MinIO object storage. |

---

## 2. Dynamic Safeguards & Quality Guarantees

### A. Anti-Repetition Exposure Cooldown
When a student initiates an assessment, the engine queries the student's past attempt responses:
```sql
SELECT DISTINCT ar.question_uid
FROM public.attempt_responses ar
JOIN public.assessment_attempts aa ON ar.attempt_id = aa.attempt_id
WHERE aa.user_id = %s
ORDER BY ar.question_uid
LIMIT 100;
```
Questions seen recently are deprioritized during question allocation using conditional ordering:
```sql
ORDER BY CASE WHEN q.question_uid = ANY(seen_uids) THEN 1 ELSE 0 END ASC, RANDOM()
```

### B. Automatic Chapter Backfill
If a student selects a sparse subtopic that contains fewer than 5 eligible questions, the engine automatically backfills the remaining slots from other topics within the **same canonical chapter**. This guarantees:
- The student is never presented with an incomplete test.
- The test always reaches the requested question count.

### C. Diagram Availability Check
Questions requiring diagrams are only served if the image file exists and is validated in MinIO object storage:
```sql
AND (q.has_diagram = false OR q.diagram_s3_key ~ '^question-assets/' OR EXISTS (
    SELECT 1 FROM public.question_image_links qil WHERE qil.question_id = q.id AND qil.is_active = true
))
```

---

## 3. Official NTA Scoring Rules

Evaluated through `engines/assessment/scoring.py`:
- **Single-Choice MCQ:**
  - Correct Answer: $+4$ marks
  - Incorrect Answer: $-1$ mark
  - Unattempted: $0$ marks
- **Numerical Value Question:**
  - Correct Answer (within $\pm 1\%$ floating point tolerance or integer match): $+4$ marks
  - Incorrect Answer: $-1$ mark (NTA revised pattern) or $0$ marks (configurable)
  - Unattempted: $0$ marks

---

## 4. Key API Endpoints

### 1. Authentication (`POST /api/v1/auth/login`)
- Validates user credentials and returns a Bearer JWT token.
- Default test user: `arjun.sharma@prepfreex.com` / `Password@123`.

### 2. Create Assessment (`POST /api/v1/assessments`)
- Request body:
```json
{
  "assessment_type": "Full-length Mock",
  "subject": "PHYSICS",
  "question_count": 75
}
```
- Returns `assessment_id`, `duration_minutes`, `deadline_at`.

### 3. Fetch Questions (`GET /api/v1/assessments/{assessment_id}/questions`)
- Returns the list of safe questions **without revealing answer keys or solutions**:
  - `question_number`, `id`, `text`, `question_type`, `options`, `has_diagram`, `diagram_url`.

### 4. Save Response (`POST /api/v1/assessments/{assessment_id}/questions/{question_number}/response`)
- Records student's selected option (`A`, `B`, `C`, `D`), numerical input, time spent, and review flags in real-time.

### 5. Submit Assessment (`POST /api/v1/assessments/{assessment_id}/submit`)
- Evaluates all student responses, computes final scores, subject percentiles, topic mastery levels, and unlocks detailed step-by-step solutions.

