"""Run the real LangGraph/A2A pause-and-restart fixture on loopback.

Run from repository root with the pinned environment described in
langgraph_a2a_app.py. Uses temporary SQLite files and no model credentials.
"""

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

URL = "http://127.0.0.1:10081"
APP = Path(__file__).with_name("langgraph_a2a_app.py")


def request(path: str, body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body).encode()
    headers = {} if body is None else {
        "Content-Type": "application/json", "A2A-Version": "1.0"
    }
    with urllib.request.urlopen(
        urllib.request.Request(URL + path, data=data, headers=headers), timeout=5
    ) as response:
        return json.load(response)


def start(db: str) -> subprocess.Popen:
    env = os.environ.copy()
    env["FRAMEWORK_FIXTURE_DB"] = db
    process = subprocess.Popen(
        [sys.executable, str(APP)], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError("server exited: " + process.stderr.read())
        try:
            request("/.well-known/agent-card.json")
            return process
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.1)
    process.terminate()
    raise RuntimeError("server did not start")


def stop(process: subprocess.Popen) -> None:
    process.terminate()
    try:
        process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()


def send(message_id: str, text: str, task: dict | None = None) -> dict:
    message = {
        "messageId": message_id, "role": "ROLE_USER", "parts": [{"text": text}]
    }
    if task is not None:
        message["taskId"] = task["id"]
        message["contextId"] = task["contextId"]
    response = request("/", {
        "jsonrpc": "2.0", "id": message_id, "method": "SendMessage",
        "params": {"message": message},
    })
    if "error" in response:
        raise RuntimeError(str(response["error"]))
    return response["result"]["task"]


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="a2a-langgraph-") as folder:
        db = str(Path(folder) / "fixture.sqlite")
        server = start(db)
        try:
            card = request("/.well-known/agent-card.json")
            assert card["name"] == "LangGraph Approval Fixture"
            first = send("m-1", "expense-42")
            assert first["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
            print("card=LangGraph Approval Fixture; first=TASK_STATE_INPUT_REQUIRED")
        finally:
            stop(server)
        server = start(db)
        try:
            final = send("m-2", "yes", first)
            assert final["id"] == first["id"]
            assert final["contextId"] == first["contextId"]
            assert final["status"]["state"] == "TASK_STATE_COMPLETED"
            assert final["artifacts"][0]["parts"][0]["text"] == "approved=yes"
            print("server restarted; same Task/context; final=TASK_STATE_COMPLETED; artifact=approved=yes")
        finally:
            stop(server)


if __name__ == "__main__":
    main()
