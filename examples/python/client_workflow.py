"""Small application-owned response adapter for a2a-sdk==1.1.2.

One ClientView tracks one interaction/Task, not an entire conversation. Persist
conversation identity separately. This example stores outputs in memory and
does not implement durable execution, event replay or a frontend schema.
"""

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Iterable

from google.protobuf.json_format import MessageToDict

from a2a.types import Artifact, GetTaskRequest, Part, StreamResponse, SubscribeToTaskRequest, Task, TaskState
from a2a.utils.errors import UnsupportedOperationError


TERMINAL = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
}
INTERRUPTED = {
    TaskState.TASK_STATE_INPUT_REQUIRED,
    TaskState.TASK_STATE_AUTH_REQUIRED,
}
STOP_STATES = TERMINAL | INTERRUPTED
OUTCOMES = {
    TaskState.TASK_STATE_SUBMITTED: "active",
    TaskState.TASK_STATE_WORKING: "active",
    TaskState.TASK_STATE_INPUT_REQUIRED: "needs_input",
    TaskState.TASK_STATE_AUTH_REQUIRED: "needs_auth",
    TaskState.TASK_STATE_COMPLETED: "completed",
    TaskState.TASK_STATE_FAILED: "failed",
    TaskState.TASK_STATE_CANCELED: "canceled",
    TaskState.TASK_STATE_REJECTED: "rejected",
}


def copy_parts(parts: Iterable[Part]) -> list[Part]:
    """Own the content rather than keeping mutable references into an event."""
    return [Part.FromString(part.SerializeToString()) for part in parts]


class ClientView:
    def __init__(self) -> None:
        self.task_id = ""
        self.context_id = ""
        self.state = TaskState.TASK_STATE_UNSPECIFIED
        self.status_parts: list[Part] = []
        self.message_parts: list[Part] = []
        self.artifacts: dict[str, Artifact] = {}
        self._direct_reply = False

    @property
    def outcome(self) -> str:
        return "message" if self._direct_reply else OUTCOMES.get(self.state, "unknown")

    def _identity(self, task_id: str, context_id: str) -> None:
        if not task_id:
            raise ValueError("Task event has no task identity")
        if self.task_id and self.task_id != task_id:
            raise ValueError("Use a separate ClientView for a different Task")
        if self.context_id and context_id and self.context_id != context_id:
            raise ValueError("The existing Task's context changed")
        self.task_id = task_id
        if context_id:
            self.context_id = context_id

    def _status(self, status) -> None:
        self.state = status.state
        self.status_parts = copy_parts(status.message.parts) if status.HasField("message") else []

    def apply(self, event: StreamResponse) -> None:
        payload = event.WhichOneof("payload")
        if payload == "message":
            message = event.message
            self.context_id = message.context_id
            self.message_parts = copy_parts(message.parts)
            self._direct_reply = True
        elif payload == "task":
            task = event.task
            self._identity(task.id, task.context_id)
            self._status(task.status)
            # A fresh snapshot replaces accumulated deltas; do not append it again.
            self.artifacts = {
                artifact.artifact_id: Artifact.FromString(artifact.SerializeToString())
                for artifact in task.artifacts
            }
        elif payload == "status_update":
            update = event.status_update
            self._identity(update.task_id, update.context_id)
            self._status(update.status)
        elif payload == "artifact_update":
            update = event.artifact_update
            self._identity(update.task_id, update.context_id)
            incoming = update.artifact
            if update.append:
                if incoming.artifact_id not in self.artifacts:
                    raise ValueError("Append without a base artifact; reconcile with GetTask")
                self.artifacts[incoming.artifact_id].parts.extend(incoming.parts)
            else:
                self.artifacts[incoming.artifact_id] = Artifact.FromString(incoming.SerializeToString())
            # last_chunk finishes this artifact, not the Task's lifecycle.
        else:
            raise ValueError("Response has no recognized payload")


def render_parts(parts: Iterable[Part]) -> list[str]:
    """Generic text fallback; preserve every Part and never fetch a file URL."""
    rendered = []
    for part in parts:
        content = part.WhichOneof("content")
        if content == "text":
            rendered.append(part.text)
        elif content == "data":
            rendered.append(json.dumps(MessageToDict(part.data), ensure_ascii=False, sort_keys=True))
        elif content == "url":
            rendered.append(f"file URL ({part.media_type or 'unspecified'}): {part.url}")
        elif content == "raw":
            encoded = base64.b64encode(part.raw).decode("ascii")
            rendered.append(f"inline file {part.filename!r} ({part.media_type or 'unspecified'}, base64): {encoded}")
        else:
            raise ValueError("Part has no content")
    return rendered


async def consume(
    stream: AsyncIterator[StreamResponse], view: ClientView, *, stop_on_interrupted: bool = False,
) -> str:
    """Drain through closure, or deliberately close when user action is needed.

    Terminal status alone does not stop this drain: output may still follow it.
    A live UI can instead call view.apply(event) and update its display per event.
    """
    try:
        async for event in stream:
            view.apply(event)
            if stop_on_interrupted and view.outcome in {"needs_input", "needs_auth"}:
                return view.outcome
        return view.outcome
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


async def poll_task(client, task_id: str, *, max_wait: float = 300, interval: float = 2) -> Task:
    """Bound total wait, including RPC time; pause for BOTH interrupted states."""
    if max_wait <= 0 or interval <= 0:
        raise ValueError("max_wait and interval must be positive")
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max_wait
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"Task {task_id} did not reach a stop state in {max_wait}s")
        try:
            task = await asyncio.wait_for(client.get_task(request=GetTaskRequest(id=task_id)), remaining)
        except asyncio.TimeoutError as error:
            # Before Python 3.11 asyncio.TimeoutError was a distinct exception.
            raise TimeoutError(f"Task {task_id} exceeded its {max_wait}s wait budget") from error
        if task.status.state in STOP_STATES:
            return task
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise TimeoutError(f"Task {task_id} did not reach a stop state in {max_wait}s")
        await asyncio.sleep(min(interval, remaining))


async def subscribe_or_get(client, view: ClientView, *, stop_on_interrupted: bool = False) -> str:
    """Subscribe to known work; reconcile the already-finished-Task race.

    The caller configures stream timeouts/reconnect budgets. Authentication,
    not-found and transport errors propagate; this is not a universal retry loop.
    """
    if not view.task_id:
        raise ValueError("No known Task to subscribe to")
    try:
        return await consume(
            client.subscribe(request=SubscribeToTaskRequest(id=view.task_id)), view,
            stop_on_interrupted=stop_on_interrupted,
        )
    except UnsupportedOperationError:
        task = await client.get_task(request=GetTaskRequest(id=view.task_id))
        if task.status.state not in STOP_STATES:
            raise
        view.apply(StreamResponse(task=task))
        return view.outcome
