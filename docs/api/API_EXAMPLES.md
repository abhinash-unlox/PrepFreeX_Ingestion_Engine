# PrepFreeX — REST API Request & Response Examples

### 1. Fetch Taxonomy Subjects
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/taxonomy/subjects"
```
```json
[
  {"code": "PHYSICS", "name": "Physics", "total_chapters": 20, "total_topics": 80},
  {"code": "CHEMISTRY", "name": "Chemistry", "total_chapters": 28, "total_topics": 112},
  {"code": "MATHEMATICS", "name": "Mathematics", "total_chapters": 16, "total_topics": 64}
]
```

### 2. Create Topic Practice Assessment
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/assessments" \
  -H "Content-Type: application/json" \
  -d '{
    "assessment_type": "Topic Practice",
    "subject": "PHYSICS",
    "chapter_code": "PHYS_U01",
    "topic_code": "PHYS_U01_T01",
    "question_count": 5
  }'
```

### 3. Save Question Response
```bash
curl -X PUT "http://127.0.0.1:8000/api/v1/assessments/att_96780c502c9ad156b8cb8c02/responses/0" \
  -H "Content-Type: application/json" \
  -d '{
    "selected_option": "A",
    "time_spent_seconds": 30,
    "is_marked_review": false
  }'
```

### 4. Submit Assessment & View Results
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/assessments/att_96780c502c9ad156b8cb8c02/submit"
```
```json
{
  "status": "SUBMITTED",
  "assessment_id": "att_96780c502c9ad156b8cb8c02",
  "total_score": 16.0,
  "max_marks": 20.0,
  "accuracy_percentage": 100.0,
  "correct_questions": 4,
  "incorrect_questions": 0,
  "unattempted_questions": 1
}
```

