# Legacy Database Audit Format

The auditor (`tools/audit_legacy_db.py`) produces aggregate-only JSON output.
No user-level row values (QQ numbers, game IDs, OCR text) are ever emitted.

## Output Schema

```json
{
  "source_sha256": "<hex>",
  "tables": {"users": 123, "scores": 456, ...},
  "columns": {"users": ["qq_id", "game_id", ...], ...},
  "integrity": {
    "duplicate_game_ids": 0,
    "orphan_scores": 0,
    "null_identity_count": 0,
    "invalid_scores": 0
  },
  "timestamp_range": {"min": 1234567890, "max": 1234567899},
  "unrecognized_tables": []
}
```

## Usage

```bash
python -m tools.audit_legacy_db <path_to_snapshot.db>
```

## Privacy Guarantees

- Opens with `SQLITE_OPEN_READONLY` (`mode=ro`) — no writes.
- Never SELECTs row values from identity columns (qq_id, game_id, ocr_lines content).
- Column names (schema metadata) are reported; actual data is not.
- SHA-256 of the snapshot file is recorded for audit trail verification.
