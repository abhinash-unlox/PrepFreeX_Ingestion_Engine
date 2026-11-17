# PrepFreeX — Complete REST API Documentation

## Interactive API Documentation
- **Swagger UI**: Visit `http://127.0.0.1:8000/docs`
- **ReDoc**: Visit `http://127.0.0.1:8000/redoc`

## Headers
- `Content-Type: application/json`
- `Authorization: Bearer <token>` (Optional for demo exploration; defaults to Arjun Sharma session).

## Standard Marking Scheme
- **MCQ (Single Choice)**: +4 marks for correct, -1 mark for incorrect, 0 for unattempted.
- **Numerical Value**: +4 marks for correct within tolerance, 0 for incorrect or unattempted.

## Error Format
All 4xx and 5xx responses conform to standard RFC 7807 JSON error responses:
```json
{
  "detail": "Descriptive human-readable error message explaining the failure"
}
```

