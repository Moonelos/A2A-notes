"""Run the streaming lab against a real temporary loopback HTTP server.

  uv run --with 'a2a-sdk[http-server]==1.1.2' --with uvicorn python -m examples.python.streaming_lab_check

The check chooses an unused local port, starts the lab server, tests JSON-RPC
and SSE plus all three SDK client modes, and stops only the process it started.
It does not use the manual server at port 9998 or any external service.
"""

import asyncio
import json
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx


PROGRESS_KEY = "com.example.reportProgress.v1"


def message(message_id, text, **identity):
    return {"messageId": message_id, "role": "ROLE_USER", "parts": [{"text": text}], **identity}


def rpc(rpc_id, method, params):
    return {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}


def artifact_text(task):
    outputs = {artifact["artifactId"]: artifact for artifact in task.get("artifacts", [])}
    return "".join(part["text"] for part in outputs["art-report"]["parts"] if "text" in part)


async def call(http, url, payload):
    response = await http.post(url, json=payload, headers={"A2A-Version": "1.0"})
    response.raise_for_status()
    body = response.json()
    assert body["id"] == payload["id"] and "error" not in body, body
    return body["result"]


async def check_wire(http, url):
    direct_input = message("msg-direct-001", "What is 2 + 2?")
    direct = await call(http, url, rpc("req-direct-001", "SendMessage", {"message": direct_input}))
    assert set(direct) == {"message"}
    reply = direct["message"]
    assert reply["role"] == "ROLE_AGENT" and reply["contextId"] and reply["messageId"]
    assert not reply.get("taskId") and reply["parts"] == [{"text": "2 + 2 = 4"}]
    assert not direct_input.get("taskId") and not direct_input.get("contextId")
    print("real unary direct Message has server context and no Task: PASS", flush=True)

    initial = message("msg-report-001", "Generate a sales report")
    waiting = (await call(http, url, rpc("req-report-001", "SendMessage", {"message": initial})))["task"]
    task_id, context_id = waiting["id"], waiting["contextId"]
    assert waiting["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    question = waiting["status"]["message"]
    assert question["taskId"] == task_id and question["contextId"] == context_id
    assert "For which month" in question["parts"][0]["text"]
    answer = message("msg-report-002", "October 2026", taskId=task_id)
    assert answer["messageId"] != initial["messageId"] and "contextId" not in answer
    completed = (await call(http, url, rpc("req-report-002", "SendMessage", {"message": answer})))["task"]
    assert completed["id"] == task_id and completed["contextId"] == context_id
    assert completed["status"]["state"] == "TASK_STATE_COMPLETED"
    assert artifact_text(completed) == "October sales: $150,000."
    print("real clarification with task-only answer resumes the same Task: PASS", flush=True)

    next_turn = message(
        "msg-report-003", "Generate a sales report for November 2026",
        contextId=context_id, referenceTaskIds=[task_id],
    )
    assert "taskId" not in next_turn
    next_task = (await call(http, url, rpc("req-report-003", "SendMessage", {"message": next_turn})))["task"]
    assert next_task["id"] != task_id and next_task["contextId"] == context_id
    assert artifact_text(next_task) == "November sales: $150,000."
    print("real context-only follow-up creates separate report work: PASS", flush=True)

    payload = rpc("req-stream-001", "SendStreamingMessage", {"message": message(
        "msg-stream-001", "Generate a sales report for October 2026",
    )})
    envelopes = []
    async with http.stream("POST", url, json=payload, headers={
        "A2A-Version": "1.0", "Accept": "text/event-stream",
    }) as response:
        response.raise_for_status()
        assert "text/event-stream" in response.headers["content-type"]
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                assert line.removeprefix("event:").strip() == "message", line
            if line.startswith("data:"):
                envelopes.append(json.loads(line.removeprefix("data:").strip()))
    assert envelopes and all(envelope["id"] == "req-stream-001" for envelope in envelopes)
    assert all("error" not in envelope for envelope in envelopes), envelopes
    results = [envelope["result"] for envelope in envelopes]
    assert all(len(result) == 1 and set(result) <= {"task", "message", "statusUpdate", "artifactUpdate"}
               for result in results)
    assert "task" in results[0]
    streamed_task = results[0]["task"]
    assert streamed_task["id"] != task_id
    statuses = [result["statusUpdate"] for result in results if "statusUpdate" in result]
    progress = [update["metadata"][PROGRESS_KEY] for update in statuses
                if PROGRESS_KEY in update.get("metadata", {})]
    assert [(event["event"], event["step"], event["completed"], event["total"]) for event in progress] == [
        ("step_completed", "fetch_sales", 1, 2), ("step_completed", "build_report", 2, 2),
    ]
    assert statuses[-1]["status"]["state"] == "TASK_STATE_COMPLETED"
    chunks = [result["artifactUpdate"] for result in results if "artifactUpdate" in result]
    assert len(chunks) == 2 and all(chunk["artifact"]["artifactId"] == "art-report" for chunk in chunks)
    assert not chunks[0].get("append", False) and not chunks[0].get("lastChunk", False)
    assert chunks[1]["append"] is True and chunks[1]["lastChunk"] is True
    assert "".join(part["text"] for chunk in chunks for part in chunk["artifact"]["parts"]) == "October sales: $150,000."
    assert all(update["taskId"] == streamed_task["id"] for update in statuses + chunks)
    # Generic parsing ignores unknown application metadata and still sees completion.
    assert results[-1]["statusUpdate"]["status"]["state"] == "TASK_STATE_COMPLETED"
    print("real SSE carries standard progress events and two same-ID text chunks: PASS", flush=True)

    final = await call(http, url, rpc("req-get-001", "GetTask", {"id": streamed_task["id"]}))
    assert final["status"]["state"] == "TASK_STATE_COMPLETED"
    assert artifact_text(final) == "October sales: $150,000."
    print("GetTask retrieves the persisted completed report: PASS", flush=True)

    # Each metadata map has its own producer and object scope.
    client_annotation = {"com.example.reportRequest.v1": {"requestTag": "ui-17"}}
    operation_annotation = {"com.example.rpc.v1": {"traceTag": "rpc-demo-17"}}
    annotated = message("msg-meta-001", "Generate a sales report for October 2026")
    annotated["metadata"] = client_annotation
    annotated_task = (await call(http, url, rpc("req-meta-001", "SendMessage", {
        "message": annotated, "metadata": operation_annotation,
    })))["task"]
    result_metadata = {"com.example.reportResult.v1": {
        "generator": "demo-report-v1", "requestTag": "ui-17",
    }}
    # SDK1.1.2 TaskManager merges server status-event metadata into Task.metadata.
    result_metadata[PROGRESS_KEY] = {
        "event": "step_completed", "step": "build_report", "completed": 2, "total": 2,
    }
    assert annotated_task["metadata"] == result_metadata, annotated_task["metadata"]
    assert "com.example.reportRequest.v1" not in annotated_task["metadata"]
    assert "com.example.rpc.v1" not in annotated_task["metadata"]
    assert annotated_task["artifacts"][0]["metadata"] == {
        "com.example.reportArtifact.v1": {"format": "plain-text"},
    }
    restored = await call(http, url, rpc("req-meta-get-001", "GetTask", {
        "id": annotated_task["id"], "historyLength": 10,
    }))
    assert restored["metadata"] == result_metadata
    assert restored["artifacts"][0]["metadata"] == annotated_task["artifacts"][0]["metadata"]
    original = next(item for item in restored["history"] if item["messageId"] == "msg-meta-001")
    assert original["metadata"] == client_annotation
    # Earlier unannotated requests work; no implicit requestTag is fabricated.
    assert "requestTag" not in final["metadata"]["com.example.reportResult.v1"]
    # Event metadata is the server's progress convention, not merged request metadata.
    assert all("com.example.rpc.v1" not in update.get("metadata", {}) for update in statuses)
    assert all("com.example.reportResult.v1" not in update.get("metadata", {}) for update in statuses)
    assert reply["metadata"] == {"com.example.reply.v1": {"source": "calculator"}}
    print("metadata ownership, explicit selection and GetTask persistence: PASS", flush=True)


async def check_clients(url):
    for scenario in ("stream", "conversation", "direct"):
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "examples.python.streaming_client", "--url", url,
            "--scenario", scenario, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise
        output = stdout.decode()
        assert process.returncode == 0, stderr.decode() + output
        sent = [json.loads(line.removeprefix("SEND Message ")) for line in output.splitlines()
                if line.startswith("SEND Message ")]
        assert len({item["messageId"] for item in sent}) == len(sent)
        sent_requests = [json.loads(line.removeprefix("SEND Request ")) for line in output.splitlines()
                         if line.startswith("SEND Request ")]
        assert len(sent_requests) == len(sent)
        assert all(item["metadata"] == {"com.example.rpc.v1": {"traceTag": "rpc-demo-17"}}
                   for item in sent_requests)
        assert all(item["metadata"] == {"com.example.reportRequest.v1": {"requestTag": "ui-17"}}
                   for item in sent)
        if scenario == "stream":
            assert "RECEIVED status_update" in output and "PROGRESS " in output
            assert "ACCUMULATED art-report: October sales: \n" in output
            assert "ACCUMULATED art-report: October sales: $150,000." in output
            assert "OUTCOME completed" in output
        elif scenario == "conversation":
            assert len(sent) == 3 and "taskId" in sent[1] and "contextId" not in sent[1]
            assert "taskId" not in sent[2] and sent[2]["contextId"] and sent[2]["referenceTaskIds"]
            assert "OUTCOME needs_input" in output and output.count("OUTCOME completed") == 2
        else:
            assert "OUTCOME message" in output and "CONTENT 2 + 2 = 4" in output
        print(f"SDK client --scenario {scenario}: PASS", flush=True)


async def run_checks(url, process):
    async with httpx.AsyncClient(timeout=5) as http:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Lab server exited before becoming ready")
            try:
                response = await http.get(url + "/.well-known/agent-card.json")
                if response.status_code == 200:
                    break
            except httpx.RequestError:
                pass
            await asyncio.sleep(0.05)
        else:
            raise TimeoutError("Lab server did not become ready")
        await asyncio.wait_for(check_wire(http, url), timeout=20)
        await asyncio.wait_for(check_clients(url), timeout=60)


def main():
    with socket.socket() as socket_reservation:
        socket_reservation.bind(("127.0.0.1", 0))
        port = socket_reservation.getsockname()[1]
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryFile(mode="w+t") as log:
        process = subprocess.Popen([
            sys.executable, "-m", "examples.python.streaming_server",
            "--port", str(port), "--delay", "0.01",
        ], cwd=root, stdout=log, stderr=log)
        try:
            asyncio.run(run_checks(f"http://127.0.0.1:{port}", process))
        except BaseException:
            log.seek(0)
            print(log.read(), file=sys.stderr)
            raise
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    print("All real-network streaming lab checks passed; temporary server stopped.")


if __name__ == "__main__":
    main()
