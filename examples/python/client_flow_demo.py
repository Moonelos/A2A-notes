"""Local client-flow checks using SDK 1.1.2 types and scripted fake responses.

Run from the repository root:
  uv run --with 'a2a-sdk==1.1.2' python -m examples.python.client_flow_demo

No agent or network service is started. Scripted responses check application
branching and BaseClient normalization. A MockTransport scenario also exercises
the SDK's actual JSON-RPC/SSE parser and HTTP error wrapping. This does not prove
remote-server conformance, durable persistence or webhook delivery.
"""

import asyncio
import json
from collections import deque
from uuid import uuid4

import httpx
from google.protobuf.json_format import MessageToDict
from google.protobuf.struct_pb2 import Value

from a2a.client import ClientConfig
from a2a.client.base_client import BaseClient
from a2a.client.errors import A2AClientError
from a2a.client.transports.jsonrpc import JsonRpcTransport
from a2a.types import (
    AgentCapabilities, AgentCard, Artifact, Message, Part, Role, SendMessageRequest,
    SendMessageResponse, StreamResponse, Task, TaskArtifactUpdateEvent,
    TaskState, TaskStatus, TaskStatusUpdateEvent,
)
from a2a.utils.errors import TaskNotFoundError, UnsupportedOperationError

from .client_workflow import (
    ClientView, consume, poll_task, render_parts, subscribe_or_get,
)
from .report_client import send_and_observe


TASK_ID = "task-123"
CONTEXT_ID = "ctx-sales-001"


def request(text: str, *, task_id: str = "", context_id: str = "", references=()):
    return SendMessageRequest(message=Message(
        message_id=f"msg-{uuid4()}", role=Role.ROLE_USER,
        task_id=task_id, context_id=context_id,
        reference_task_ids=references, parts=[Part(text=text)],
    ))


def task(state, *, artifacts=(), question="", task_id=TASK_ID):
    status = TaskStatus(state=state)
    if question:
        status.message.CopyFrom(Message(
            message_id="msg-question-001", role=Role.ROLE_AGENT,
            task_id=task_id, context_id=CONTEXT_ID, parts=[Part(text=question)],
        ))
    return Task(id=task_id, context_id=CONTEXT_ID, status=status, artifacts=artifacts)


def artifact(artifact_id, *parts, name=""):
    return Artifact(artifact_id=artifact_id, name=name, parts=parts)


async def events(*items):
    for item in items:
        yield item


class ScriptedClient:
    """A deliberate test double at the typed client boundary."""

    def __init__(self, *, turns=(), snapshots=(), subscription=(), subscribe_error=None):
        self.turns = deque(turns)
        self.snapshots = deque(snapshots)
        self.subscription = subscription
        self.subscribe_error = subscribe_error
        self.requests = []
        self.read_ids = []

    async def send_message(self, *, request):
        self.requests.append(request)
        for event in self.turns.popleft():
            yield event

    async def get_task(self, *, request):
        self.read_ids.append(request.id)
        if len(self.snapshots) > 1:
            return self.snapshots.popleft()
        return self.snapshots[0]

    async def subscribe(self, *, request):
        assert request.id == TASK_ID
        if self.subscribe_error:
            raise self.subscribe_error
        for event in self.subscription:
            yield event


async def check_direct_reply():
    reply = Message(
        message_id="msg-math-002", role=Role.ROLE_AGENT,
        context_id="ctx-math-001", parts=[Part(text="2 + 2 = 4")],
    )
    client = ScriptedClient(turns=[
        [StreamResponse(message=reply)], [StreamResponse(message=reply)],
    ])
    view = ClientView()
    assert await consume(client.send_message(request=request("What is 2 + 2?")), view) == "message"
    assert not view.task_id and view.context_id == "ctx-math-001"
    followup = request("What about 3 + 3?", context_id=view.context_id)
    await consume(client.send_message(request=followup), ClientView())
    assert client.requests[-1].message.context_id == "ctx-math-001"
    assert not client.requests[-1].message.task_id
    assert not client.read_ids
    print("direct Message and context-only follow-up: PASS")


async def check_snapshots():
    mixed = [
        Part(text=""), Part(data=Value(bool_value=False)),
        Part(url="https://example.com/chart.png", media_type="image/png"),
        Part(raw=b"bytes", filename="report.bin", media_type="application/octet-stream"),
    ]
    outputs = [
        artifact("art-summary", Part(text="October total sales: $150,000"), name="report"),
        artifact("art-chart", *mixed, name="report"),
        artifact("art-extra", Part(text="No display name")),
    ]
    for expected in ([], outputs[:1], outputs):
        view = ClientView()
        outcome = await consume(events(StreamResponse(task=task(
            TaskState.TASK_STATE_COMPLETED, artifacts=expected,
        ))), view)
        assert outcome == "completed" and len(view.artifacts) == len(expected)
    assert set(view.artifacts) == {"art-summary", "art-chart", "art-extra"}
    rendered = render_parts(view.artifacts["art-chart"].parts)
    assert rendered[0] == "" and rendered[1] == "false"
    assert "https://example.com/chart.png" in rendered[2]
    assert "Ynl0ZXM=" in rendered[3]
    for state, expected in (
        (TaskState.TASK_STATE_FAILED, "failed"),
        (TaskState.TASK_STATE_CANCELED, "canceled"),
        (TaskState.TASK_STATE_REJECTED, "rejected"),
    ):
        assert await consume(events(StreamResponse(task=task(state))), ClientView()) == expected
    print("Task snapshots (zero/one/multiple outputs, mixed Parts): PASS")


async def check_followup():
    completed = task(TaskState.TASK_STATE_COMPLETED, artifacts=[
        artifact("art-summary", Part(text="October total sales: $150,000")),
    ])
    client = ScriptedClient(turns=[
        [StreamResponse(task=task(TaskState.TASK_STATE_INPUT_REQUIRED,
                                  question="For which month?"))],
        [StreamResponse(task=completed)],
        [StreamResponse(task=task(TaskState.TASK_STATE_COMPLETED, task_id="task-456"))],
    ])
    waiting = ClientView()
    assert await consume(client.send_message(request=request("Generate a report")), waiting) == "needs_input"
    assert render_parts(waiting.status_parts) == ["For which month?"]
    answer = request("October 2026", task_id=waiting.task_id)
    result = ClientView()
    assert await consume(client.send_message(request=answer), result) == "completed"
    assert result.task_id == TASK_ID and result.context_id == CONTEXT_ID
    assert answer.message.task_id == TASK_ID and not answer.message.context_id
    assert client.requests[0].message.message_id != answer.message.message_id
    print("INPUT_REQUIRED -> answer same Task -> COMPLETED: PASS")

    next_request = request("Now November", context_id=result.context_id, references=[result.task_id])
    next_view = ClientView()
    await consume(client.send_message(request=next_request), next_view)
    assert not next_request.message.task_id
    assert list(next_request.message.reference_task_ids) == [TASK_ID]
    assert next_view.task_id == "task-456" and next_view.context_id == CONTEXT_ID
    print("completed Task -> new interaction in same context: PASS")


async def check_chunks():
    def chunk(artifact_id, text, *, append=False, last=False):
        return StreamResponse(artifact_update=TaskArtifactUpdateEvent(
            task_id=TASK_ID, context_id=CONTEXT_ID,
            artifact=artifact(artifact_id, Part(text=text)), append=append, last_chunk=last,
        ))

    view = ClientView()
    await consume(events(
        StreamResponse(task=task(TaskState.TASK_STATE_WORKING)),
        chunk("art-summary", "Sales "), chunk("art-chart", "chart"),
        chunk("art-summary", "increased.", append=True, last=True),
    ), view)
    assert view.outcome == "active"  # last_chunk does not complete the Task.
    assert render_parts(view.artifacts["art-summary"].parts) == ["Sales ", "increased."]
    assert render_parts(view.artifacts["art-chart"].parts) == ["chart"]
    persisted = task(TaskState.TASK_STATE_COMPLETED, artifacts=[
        artifact("art-summary", Part(text="Sales increased.")),
        artifact("art-chart", Part(text="chart")),
    ])
    view.apply(StreamResponse(task=persisted))
    assert render_parts(view.artifacts["art-summary"].parts) == ["Sales increased."]
    assert len(view.artifacts) == 2
    for malformed in (StreamResponse(), StreamResponse(task=task(
        TaskState.TASK_STATE_WORKING, task_id="different-task",
    ))):
        try:
            view.apply(malformed)
        except ValueError:
            pass
        else:
            raise AssertionError("missing payload and mixed Task identity must fail")
    print("artifact append and snapshot reconciliation: PASS")


async def check_subscription():
    view = ClientView()
    view.apply(StreamResponse(task=task(TaskState.TASK_STATE_WORKING)))
    client = ScriptedClient(subscription=[
        StreamResponse(task=task(TaskState.TASK_STATE_WORKING)),
        StreamResponse(status_update=TaskStatusUpdateEvent(
            task_id=TASK_ID, context_id=CONTEXT_ID,
            status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
        )),
    ])
    assert await subscribe_or_get(client, view) == "completed"
    assert not client.read_ids

    final = task(TaskState.TASK_STATE_COMPLETED, artifacts=[
        artifact("art-summary", Part(text="Final report")),
    ])
    client = ScriptedClient(snapshots=[final], subscribe_error=UnsupportedOperationError("terminal Task"))
    view = ClientView()
    view.apply(StreamResponse(task=task(TaskState.TASK_STATE_WORKING)))
    assert await subscribe_or_get(client, view) == "completed"
    assert client.read_ids == [TASK_ID]
    assert render_parts(view.artifacts["art-summary"].parts) == ["Final report"]

    unsupported = ScriptedClient(
        snapshots=[task(TaskState.TASK_STATE_WORKING)],
        subscribe_error=UnsupportedOperationError("streaming unavailable"),
    )
    try:
        await subscribe_or_get(unsupported, view)
    except UnsupportedOperationError:
        pass
    else:
        raise AssertionError("unrelated unsupported operation must propagate")

    inaccessible = ScriptedClient(subscribe_error=TaskNotFoundError("not accessible"))
    try:
        await subscribe_or_get(inaccessible, view)
    except TaskNotFoundError:
        assert not inaccessible.read_ids
    else:
        raise AssertionError("not-found must propagate")
    print("subscription and completed-before-subscribe recovery: PASS")


async def check_polling():
    client = ScriptedClient(snapshots=[
        task(TaskState.TASK_STATE_WORKING),
        task(TaskState.TASK_STATE_AUTH_REQUIRED, question="Authorize the provider externally."),
    ])
    snapshot = await poll_task(client, TASK_ID, max_wait=1, interval=0.001)
    view = ClientView()
    view.apply(StreamResponse(task=snapshot))
    assert view.outcome == "needs_auth" and len(client.read_ids) == 2

    client = ScriptedClient(snapshots=[task(TaskState.TASK_STATE_INPUT_REQUIRED, question="Which month?")])
    assert (await poll_task(client, TASK_ID, max_wait=1)).status.state == TaskState.TASK_STATE_INPUT_REQUIRED
    client = ScriptedClient(snapshots=[task(TaskState.TASK_STATE_WORKING)])
    try:
        await poll_task(client, TASK_ID, max_wait=0.01, interval=0.005)
    except TimeoutError:
        pass
    else:
        raise AssertionError("active wait must be bounded")

    class SlowClient:
        async def get_task(self, *, request):
            await asyncio.sleep(1)
            return task(TaskState.TASK_STATE_WORKING)

    try:
        await poll_task(SlowClient(), TASK_ID, max_wait=0.01)
    except TimeoutError:
        pass
    else:
        raise AssertionError("RPC time must count against the wait budget")
    print("AUTH_REQUIRED polling and bounded active wait: PASS")


async def check_interrupted_subscription():
    for payload in (
        StreamResponse(task=task(TaskState.TASK_STATE_INPUT_REQUIRED, question="Which month?")),
        StreamResponse(status_update=TaskStatusUpdateEvent(
            task_id=TASK_ID, context_id=CONTEXT_ID,
            status=TaskStatus(state=TaskState.TASK_STATE_INPUT_REQUIRED),
        )),
    ):
        closed = False

        async def stays_open():
            nonlocal closed
            try:
                yield payload
                await asyncio.Event().wait()
            finally:
                closed = True

        view = ClientView()
        outcome = await asyncio.wait_for(
            consume(stays_open(), view, stop_on_interrupted=True), timeout=0.2,
        )
        assert outcome == "needs_input" and closed
    print("interrupted subscription returns control and closes: PASS")


async def check_base_client():
    class ReplyTransport:
        def __init__(self, response):
            self.response = response

        async def send_message(self, request, *, context=None):
            return self.response

    replies = [
        SendMessageResponse(message=Message(
            message_id="m1", context_id=CONTEXT_ID, role=Role.ROLE_AGENT,
            parts=[Part(text="Direct reply")],
        )),
        SendMessageResponse(task=task(TaskState.TASK_STATE_INPUT_REQUIRED, question="Which month?")),
        SendMessageResponse(task=task(TaskState.TASK_STATE_COMPLETED, artifacts=[
            artifact("art-summary", Part(text="Final report")),
        ])),
    ]
    for reply, expected in zip(replies, ["message", "needs_input", "completed"]):
        client = BaseClient(
            AgentCard(), ClientConfig(streaming=False), ReplyTransport(reply), [],
        )
        view = ClientView()
        assert await consume(client.send_message(request("Report")), view) == expected
    # Reading an inactive protobuf submessage yields defaults, not AttributeError.
    direct = StreamResponse(message=replies[0].message)
    assert not direct.HasField("task") and direct.task.id == ""
    print("SDK BaseClient non-streaming normalization: PASS")


async def check_http_stream_recovery():
    """Exercise actual SDK wrapping of a connection lost after Task identity."""
    class Frames(httpx.AsyncByteStream):
        def __init__(self, frames, *, broken=False):
            self.frames, self.broken = frames, broken

        async def __aiter__(self):
            for frame in self.frames:
                yield frame
            if self.broken:
                raise httpx.ReadError("scripted SSE connection loss")

    def frame(rpc_id, event):
        payload = {"jsonrpc": "2.0", "id": rpc_id, "result": MessageToDict(event)}
        return ("data: " + json.dumps(payload) + "\n\n").encode()

    for finished_before_subscribe in (False, True):
        methods = []
        final = task(TaskState.TASK_STATE_COMPLETED, artifacts=[
            artifact("art-summary", Part(text="Recovered final report")),
        ])

        def handler(http_request):
            payload = json.loads(http_request.content)
            method, rpc_id = payload["method"], payload["id"]
            methods.append(method)
            if method == "SendStreamingMessage":
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Frames([
                    frame(rpc_id, StreamResponse(task=task(TaskState.TASK_STATE_WORKING))),
                ], broken=True))
            if method == "SubscribeToTask":
                assert payload["params"]["id"] == TASK_ID
                if finished_before_subscribe:
                    return httpx.Response(200, json={
                        "jsonrpc": "2.0", "id": rpc_id,
                        "error": {"code": -32004, "message": "Task already completed"},
                    })
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Frames([
                    frame(rpc_id, StreamResponse(task=task(TaskState.TASK_STATE_WORKING))),
                    frame(rpc_id, StreamResponse(artifact_update=TaskArtifactUpdateEvent(
                        task_id=TASK_ID, context_id=CONTEXT_ID, artifact=final.artifacts[0],
                    ))),
                    frame(rpc_id, StreamResponse(status_update=TaskStatusUpdateEvent(
                        task_id=TASK_ID, context_id=CONTEXT_ID, status=final.status,
                    ))),
                ]))
            assert method == "GetTask" and payload["params"]["id"] == TASK_ID
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": rpc_id, "result": MessageToDict(final),
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            card = AgentCard(capabilities=AgentCapabilities(streaming=True))
            client = BaseClient(card, ClientConfig(streaming=True), JsonRpcTransport(
                http, card, "https://agent.example.com/a2a",
            ), [])
            # Observe the actual SDK exception shape, independently of the runner.
            try:
                await consume(client.send_message(request("Report")), ClientView())
            except A2AClientError as error:
                assert isinstance(error.__cause__, httpx.ReadError)
            else:
                raise AssertionError("broken SSE must surface as a wrapped network error")
            methods.clear()
            view = ClientView()
            assert await send_and_observe(client, request("Report"), view, streaming=True) == "completed"
            assert methods.count("SendStreamingMessage") == 1  # Never resend original content.
            expected = ["SendStreamingMessage", "SubscribeToTask"]
            if finished_before_subscribe:
                expected.append("GetTask")
            assert methods == expected
            assert render_parts(view.artifacts["art-summary"].parts) == ["Recovered final report"]
    print("real JSON-RPC/SSE wrapped drop reconnects without resend: PASS")


async def check_non_transient_errors():
    class ErrorClient:
        def __init__(self):
            self.send_count = 0

        async def send_message(self, *, request):
            self.send_count += 1
            raise A2AClientError("malformed response, no transient cause")
            yield  # This method models an async stream.

        async def subscribe(self, *, request):
            raise AssertionError("non-transient errors must not reconnect")
            yield

    client = ErrorClient()
    view = ClientView()
    view.apply(StreamResponse(task=task(TaskState.TASK_STATE_WORKING)))
    try:
        await send_and_observe(client, request("Report"), view, streaming=True)
    except A2AClientError:
        assert client.send_count == 1
    else:
        raise AssertionError("generic client error must propagate")

    for failure in ("auth", "notfound"):
        methods = []

        def handler(http_request):
            payload = json.loads(http_request.content)
            methods.append(payload["method"])
            if failure == "auth":
                return httpx.Response(401, json={"detail": "unauthorized"})
            return httpx.Response(200, json={
                "jsonrpc": "2.0", "id": payload["id"],
                "error": {"code": -32001, "message": "Task not accessible"},
            })

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            card = AgentCard(capabilities=AgentCapabilities(streaming=True))
            client = BaseClient(card, ClientConfig(streaming=True), JsonRpcTransport(
                http, card, "https://agent.example.com/a2a",
            ), [])
            view = ClientView()
            view.apply(StreamResponse(task=task(TaskState.TASK_STATE_WORKING)))
            try:
                await send_and_observe(client, request("Report"), view, streaming=True)
            except (A2AClientError, TaskNotFoundError) as error:
                if failure == "auth":
                    assert isinstance(error.__cause__, httpx.HTTPStatusError)
                else:
                    assert isinstance(error, TaskNotFoundError)
                assert methods == ["SendStreamingMessage"]
            else:
                raise AssertionError("authentication and not-found errors must propagate")
    print("non-transient client, authentication and not-found errors propagate: PASS")


async def main():
    await check_direct_reply()
    await check_snapshots()
    await check_followup()
    await check_chunks()
    await check_subscription()
    await check_polling()
    await check_interrupted_subscription()
    await check_base_client()
    await check_http_stream_recovery()
    await check_non_transient_errors()
    print("All client workflow checks passed (local fake client; no remote server).")


if __name__ == "__main__":
    asyncio.run(main())
