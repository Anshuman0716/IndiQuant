import time
import subprocess
import requests
import json
import os

import sys

print("Starting Uvicorn server...")
env = os.environ.copy()
env["PYTHONPATH"] = os.path.abspath("src")
server = subprocess.Popen(["uv", "run", "python", "-m", "uvicorn", "indiquant.api.app:app", "--host", "127.0.0.1", "--port", "8000"], env=env)

time.sleep(4)

TOKEN = "tapetide-secret-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
URL = "http://127.0.0.1:8000"

try:
    print("\n=== 1. LIST FACTORS ===")
    r = requests.get(f"{URL}/v1/factors", headers=HEADERS)
    print(json.dumps(r.json(), indent=2))
    
    print("\n=== 2. SUBMIT BACKTEST ===")
    payload = {
        "name": "tapetide_composite",
        "capital": 100000,
        "start_date": "2024-01-01",
        "end_date": "2024-01-31",
        "factors": ["value"],
        "weights": [1.0],
        "top_n": 20
    }
    r = requests.post(f"{URL}/v1/backtest", headers=HEADERS, json=payload)
    print(f"Status Code: {r.status_code}")
    print(json.dumps(r.json(), indent=2))
    run_id = r.json()["run_id"]
    
    print("\n=== 3. POLL UNTIL COMPLETE ===")
    for _ in range(10):
        r = requests.get(f"{URL}/v1/backtest/{run_id}", headers=HEADERS)
        status = r.json()["status"]
        print(f"Status: {status}")
        if status == "completed":
            break
        time.sleep(1)
        
    print("\n=== 4. FETCH REPORT ===")
    r = requests.get(f"{URL}/v1/backtest/{run_id}/report", headers=HEADERS)
    print(json.dumps(r.json(), indent=2))
    
    print("\n=== 5. FETCH VALIDATION SUMMARY ===")
    r = requests.get(f"{URL}/v1/backtest/{run_id}/validation", headers=HEADERS)
    print(json.dumps(r.json(), indent=2))
    
    print("\n=== 6. FII-DII UNAVAILABLE ENDPOINT ===")
    r = requests.get(f"{URL}/v1/flows/fii-dii?days=30", headers=HEADERS)
    print(f"Status Code: {r.status_code}")
    print(json.dumps(r.json(), indent=2))
    
    print("\n=== 7. OI-BUILDUP ENDPOINT (ABFRL) ===")
    r = requests.get(f"{URL}/v1/derivatives/oi-buildup?symbol=ABFRL&days=30", headers=HEADERS)
    print(f"Status Code: {r.status_code}")
    print(json.dumps(r.json(), indent=2))
    
    print("\n=== 8. OI-BUILDUP ENDPOINT (RELIANCE) ===")
    r = requests.get(f"{URL}/v1/derivatives/oi-buildup?symbol=RELIANCE&days=30", headers=HEADERS)
    print(f"Status Code: {r.status_code}")
    print(json.dumps(r.json(), indent=2))

finally:
    print("\nShutting down server...")
    server.terminate()
    server.wait()
