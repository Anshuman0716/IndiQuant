import subprocess
import json
import uuid
import time
import os

def mcp_request(method, params=None, is_notif=False):
    req = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {}
    }
    if not is_notif:
        req["id"] = str(uuid.uuid4())
    return req

def run_mcp_client():
    node_path = os.path.abspath(os.path.join("mcp-server", "node-v20.11.1-win-x64", "node.exe"))
    os.environ["PATH"] = os.path.dirname(node_path) + os.pathsep + os.environ.get("PATH", "")
    
    proc = subprocess.Popen(
        [node_path, "--import", "tsx", "src/index.ts"],
        cwd="mcp-server",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    def send(req_dict):
        proc.stdin.write(json.dumps(req_dict) + "\n")
        proc.stdin.flush()
        
    def read_resp(expected_id=None):
        while True:
            line = proc.stdout.readline()
            if not line: return None
            resp = json.loads(line.strip())
            if expected_id is None or resp.get("id") == expected_id:
                return resp
        
    # Init
    init_req = mcp_request("initialize", {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-client", "version": "1.0"}
    })
    send(init_req)
    print("Init response:", read_resp(init_req["id"]))
    
    send(mcp_request("notifications/initialized", is_notif=True))
    time.sleep(1)
    
    print("\n\n=== DELIBERATE FAILURE PATH (Nifty 500 midcap, since 2012) ===")
    req1 = mcp_request("tools/call", {
        "name": "run_backtest",
        "arguments": {
            "name": "test_failure",
            "capital": 1000000.0,
            "start_date": "2012-01-01",
            "end_date": "2012-12-31",
            "factors": ["momentum"],
            "weights": [1.0]
        }
    })
    send(req1)
    print("Response:")
    print(json.dumps(read_resp(req1["id"]), indent=2))
    
    print("\n\n=== APRIL 2017 MOMENTUM SCENARIO (Success) ===")
    req2 = mcp_request("tools/call", {
        "name": "run_backtest",
        "arguments": {
            "name": "momentum_2017",
            "capital": 1000000.0,
            "start_date": "2017-04-01",
            "end_date": "2018-04-01",
            "factors": ["momentum"],
            "weights": [1.0]
        }
    })
    send(req2)
    resp2 = read_resp(req2["id"])
    print("Response:")
    print(json.dumps(resp2, indent=2))
    
    if not resp2.get("error"):
        content = json.loads(resp2["result"]["content"][0]["text"])
        if content.get("error"):
            print("Server returned shaped error:", content)
            proc.kill()
            return
            
        run_id = content["run_id"]
        
        print(f"\n\n=== FETCHING REPORT FOR RUN ID: {run_id} ===")
        req3 = mcp_request("tools/call", {
            "name": "get_backtest_report",
            "arguments": {"run_id": run_id}
        })
        send(req3)
        print("Report Response:")
        print(json.dumps(read_resp(req3["id"]), indent=2))
        
        print(f"\n\n=== FETCHING VALIDATION FOR RUN ID: {run_id} ===")
        req4 = mcp_request("tools/call", {
            "name": "get_validation_report",
            "arguments": {"run_id": run_id}
        })
        send(req4)
        print("Validation Response:")
        print(json.dumps(read_resp(req4["id"]), indent=2))

    proc.kill()

if __name__ == "__main__":
    run_mcp_client()
    req2 = mcp_request("tools/call", {
        "name": "run_backtest",
        "arguments": {
            "name": "momentum_2017",
            "capital": 1000000.0,
            "start_date": "2017-04-01",
            "end_date": "2018-04-01",
            "factors": ["momentum"],
            "weights": [1.0]
        }
    })
    send(req2)
    resp2 = read_resp()
    print("Response:")
    print(json.dumps(resp2, indent=2))
    
    if not resp2.get("error"):
        content = json.loads(resp2["result"]["content"][0]["text"])
        run_id = content["run_id"]
        
        print(f"\n\n=== FETCHING REPORT FOR RUN ID: {run_id} ===")
        req3 = mcp_request("tools/call", {
            "name": "get_backtest_report",
            "arguments": {"run_id": run_id}
        })
        send(req3)
        print("Report Response:")
        print(json.dumps(read_resp(), indent=2))
        
        print(f"\n\n=== FETCHING VALIDATION FOR RUN ID: {run_id} ===")
        req4 = mcp_request("tools/call", {
            "name": "get_validation_report",
            "arguments": {"run_id": run_id}
        })
        send(req4)
        print("Validation Response:")
        print(json.dumps(read_resp(), indent=2))

    proc.kill()

if __name__ == "__main__":
    run_mcp_client()
