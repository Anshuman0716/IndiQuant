#!/usr/bin/env bash
set -e

echo "Checking for strict Polars boundary (Polars is allowed ONLY in ingest/, store/, config/)"

# Find files importing polars outside allowed directories
VIOLATIONS=$(grep -rn "^import polars\|from polars import" src/indiquant/universe/ src/indiquant/factors/ src/indiquant/engine/ src/indiquant/validation/ src/indiquant/api/ 2>/dev/null || true)

if [ -n "$VIOLATIONS" ]; then
    echo "ERROR: Polars boundary violation detected!"
    echo "The following files outside of ingest/ and store/ import Polars:"
    echo "$VIOLATIONS"
    echo "Polars is confined strictly to ingestion and validation. Use pandas downstream."
    exit 1
else
    echo "SUCCESS: No Polars boundary violations."
    exit 0
fi
