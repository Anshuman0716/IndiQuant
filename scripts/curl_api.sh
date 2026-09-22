#!/bin/bash
set -e

# Run FastAPI Server in background
export PYTHONPATH=$(pwd)/src:$PYTHONPATH
uv run uvicorn indiquant.api.app:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!
sleep 3

# Bearer token
# "tapetide-secret-token" hashes to 3b680190538a719c8d35f47029cb256b7f339f4a86f2b2e88a0b0d367f1b7425
TOKEN="tapetide-secret-token"

echo -e "\n=== 1. LIST FACTORS ==="
curl -s -X GET "http://127.0.0.1:8000/v1/factors" \
     -H "Authorization: Bearer $TOKEN"

echo -e "\n\n=== 2. SUBMIT BACKTEST ==="
RESPONSE=$(curl -s -X POST "http://127.0.0.1:8000/v1/backtest" \
     -H "Authorization: Bearer $TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "name": "API Backtest",
           "capital": 100000,
           "start_date": "2024-01-01",
           "end_date": "2024-01-31",
           "factors": ["value"],
           "weights": [1.0],
           "top_n": 20
         }')
echo $RESPONSE
RUN_ID=$(echo $RESPONSE | jq -r .run_id)

echo -e "\n\n=== 3. POLL UNTIL COMPLETE ==="
for i in {1..10}; do
    STATUS_RESP=$(curl -s -X GET "http://127.0.0.1:8000/v1/backtest/$RUN_ID" -H "Authorization: Bearer $TOKEN")
    STATUS=$(echo $STATUS_RESP | jq -r .status)
    echo "Status: $STATUS"
    if [ "$STATUS" = "completed" ]; then
        break
    fi
    sleep 1
done

echo -e "\n=== 4. FETCH REPORT ==="
curl -s -X GET "http://127.0.0.1:8000/v1/backtest/$RUN_ID/report" \
     -H "Authorization: Bearer $TOKEN"

echo -e "\n\n=== 5. FETCH VALIDATION SUMMARY ==="
curl -s -X GET "http://127.0.0.1:8000/v1/backtest/$RUN_ID/validation" \
     -H "Authorization: Bearer $TOKEN"

echo -e "\n\n=== 6. FII-DII UNAVAILABLE ENDPOINT ==="
curl -s -X GET "http://127.0.0.1:8000/v1/flows/fii-dii?days=30" \
     -H "Authorization: Bearer $TOKEN"

echo -e "\n\n=== 7. OI-BUILDUP ENDPOINT ==="
curl -s -X GET "http://127.0.0.1:8000/v1/derivatives/oi-buildup?isin=ABFRL&days=30" \
     -H "Authorization: Bearer $TOKEN"

echo -e "\n\nShutting down server..."
kill $SERVER_PID
