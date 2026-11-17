# PrepFreeX Assessment Engine Service

Reusable assessment evaluation engine supporting:
- 7 assessment types (Diagnostic, DPP, Chapter Test, Part Test, Full Mock, Revision Drill, Adaptive)
- Versioned immutable assessment configurations and fixed question snapshots
- Server-authoritative deterministic scoring with negative marking
- Idempotent attempt submission with state machine (in_progress, submitted, expired, interrupted, cancelled)
- Real-time learner mastery tracking & adaptive difficulty calibration

