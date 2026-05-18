# Building an A2A Server with the Python SDK

> **Who this is for**: Python engineers who have completed [SDK Setup](01_sdk_setup.md) and want to expose an agent over the A2A protocol. You should understand the [Task Lifecycle](../02_protocol/03_task_lifecycle.md) — this file shows how the executor *drives* that lifecycle. Targets `a2a-sdk` **v1.0.3** (May 2026).

---

## 1. The server in four pieces

An A2A server is not a framework you subclass — it is four objects you wire together:

```
┌──────────────────────────────────────────────────────────────┐
│  AgentCard          describes the agent (skills, transports)  │
│       │             served at /.well-known/agent-card.json    │
│       ▼                                                        │
│  AgentExecutor      YOUR code — runs the agent, emits events  │
│       │                                                        │
│       ▼                                                        │
│  DefaultRequestHandler   wires executor ⇄ TaskStore,          │
│       │                  manages event queues per request     │
│       ▼                                                        │
│  Starlette / FastAPI app   route factories turn JSON-RPC      │
│                            calls into executor invocations    │
└──────────────────────────────────────────────────────────────┘
```

> **Rule**: You implement exactly one thing — the `AgentExecutor`. Everything else is SDK plumbing you assemble.

⚠️ **v1.0 breaking change**: SDK 0.3 shipped wrapper classes `A2AStarletteApplication` / `A2AFastAPIApplication` with a `.build()` method. **These were removed in v1.0.** Server setup now uses route factory functions (`create_jsonrpc_routes`, `create_agent_card_routes`, `create_rest_routes`) composed directly into a plain Starlette or FastAPI app. Any tutorial showing `A2AStarletteApplication` is pre-1.0 and will not import.

Install the HTTP server extra (from [SDK Setup](01_sdk_setup.md)):

```bash
uv add "a2a-sdk[http-server]"   # pulls in starlette + uvicorn
```

---

## 2. Defining the Agent Card in code

The **Agent Card** is the agent's public manifest. The SDK serves it automatically at `/.well-known/agent-card.json` so clients can discover capabilities before sending a message.

```python
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
)

# A skill is one named capability the agent advertises.
convert_skill = AgentSkill(
    id='convert_currency',
    name='Convert currency',
    description='Converts an amount between two ISO-4217 currency codes '
                'using live mid-market exchange rates.',
    tags=['finance', 'currency', 'fx'],
    # `examples` lives on the skill in v1.0 (it moved off AgentCard).
    examples=['convert 100 USD to EUR', 'how much is 50 GBP in JPY'],
)

agent_card = AgentCard(
    name='Currency Converter Agent',
    description='Converts amounts between currencies at live rates.',
    version='1.0.0',
    default_input_modes=['text/plain'],
    default_output_modes=['text/plain'],
    capabilities=AgentCapabilities(
        streaming=True,            # enables SSE for send-streaming-message
        extended_agent_card=True,  # supports an authenticated extended card
    ),
    # v1.0: transports are declared as `supported_interfaces`, NOT a single `url`.
    supported_interfaces=[
        AgentInterface(
            protocol_binding='JSONRPC',
            protocol_version='1.0',
            url='http://127.0.0.1:9999',
        ),
    ],
    skills=[convert_skill],
)
```

⚠️ **v1.0 Agent Card changes** versus 0.3 — verify these or your card will fail validation:

| 0.3 field | v1.0 replacement |
|---|---|
| `url='http://...'` (single string) | `supported_interfaces=[AgentInterface(protocol_binding=..., protocol_version='1.0', url=...)]` |
| `AgentCard.examples=[...]` | moved onto each `AgentSkill.examples` |
| `capabilities` mixed input/output modes | modes live on `AgentCard.default_input_modes` / `default_output_modes` |
| `supports_authenticated_extended_card=True` | `AgentCapabilities(extended_agent_card=True)` |

> **Rule**: The `url` inside each `AgentInterface` must be the externally reachable base URL — clients fetch the card, read this URL, and send messages there. Localhost only works for local dev.

💡 The card is also where you declare auth requirements (`security_schemes` / `security_requirements` fields). That is covered in [Authentication](../05_production/01_authentication.md); the executor itself stays auth-agnostic.

---

## 3. Implementing the AgentExecutor

`AgentExecutor` is an abstract base class with two coroutines you must implement. This is the only file where you write agent logic.

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
```

- **`execute(context, event_queue)`** — runs the agent for one request. Reads input from `context`, pushes results onto `event_queue`.
- **`cancel(context, event_queue)`** — asked to stop an in-flight task.

### What `RequestContext` exposes

`RequestContext` is read-only-ish input. The fields you actually use:

| Member | Type | Purpose |
|---|---|---|
| `context.message` | `Message \| None` | the incoming user message |
| `context.get_user_input()` | `str` | concatenated text of all text parts — the fast path |
| `context.current_task` | `Task \| None` | the existing task if this is a follow-up; `None` on first turn |
| `context.task_id` | `str \| None` | task id (generated by the SDK if absent) |
| `context.context_id` | `str \| None` | conversation/context id, stable across turns |
| `context.call_context` | `ServerCallContext` | auth/user/tenant info from the transport layer |

### What the executor pushes to `EventQueue`

The executor never *returns* a result — it **enqueues events**. The SDK drains the queue, persists task state, and (for streaming) emits SSE frames. There are two legal event shapes:

| Event | Meaning |
|---|---|
| `Message` | a one-shot reply, no task tracking |
| `Task` | the task object — **must be the first event** in task mode |
| `TaskStatusUpdateEvent` | a state transition (`TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, ...) |
| `TaskArtifactUpdateEvent` | an output artifact (or a chunk of one) |

> **Rule**: A stream must follow **exactly one** pattern. Either enqueue a single `Message` and stop, **or** enqueue a `Task` first and then status/artifact events. Mixing them, or sending a status event before the `Task`, raises `InvalidAgentResponseError` at runtime in v1.0 (the spec rule is now strictly enforced — it was silently tolerated in 0.3).

### A complete task-based executor

```python
from a2a.helpers import new_task_from_user_message, new_text_artifact, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types.a2a_pb2 import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)


class CurrencyConverterExecutor(AgentExecutor):
    """Converts an amount between two currencies using a live-rate service."""

    def __init__(self, fx_client):
        # `fx_client` is your async domain object (an httpx client, repository,
        # LLM wrapper, ...). Injecting it keeps the executor testable.
        self._fx = fx_client

    async def execute(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        # 1. Establish the Task. Reuse the existing one on a follow-up turn,
        #    otherwise create one from the incoming user message.
        task = context.current_task or new_task_from_user_message(context.message)
        # ✅ The Task object MUST be the first event enqueued in task mode.
        await event_queue.enqueue_event(task)

        # 2. Signal that work has started (task -> WORKING).
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task.id,
                context_id=task.context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=new_text_message('Fetching exchange rate...'),
                ),
            )
        )

        # 3. Parse input and do the actual work.
        amount, src, dst = _parse_request(context.get_user_input())
        rate = await self._fx.get_rate(src, dst)   # async I/O — never block
        converted = round(amount * rate, 2)

        # 4. Emit the result as an artifact.
        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task.id,
                context_id=task.context_id,
                artifact=new_text_artifact(
                    name='conversion_result',
                    text=f'{amount} {src} = {converted} {dst} (rate {rate})',
                ),
            )
        )

        # 5. Mark the task terminal. WITHOUT this the task hangs forever.
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task.id,
                context_id=task.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            )
        )

    async def cancel(
        self, context: RequestContext, event_queue: EventQueue
    ) -> None:
        # Long-running agents stop their work here and report CANCELED.
        # If cancellation is genuinely unsupported, raise
        # UnsupportedOperationError rather than failing silently.
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )
```

⚠️ **v1.0 type system**: the wire types (`Task`, `Message`, `TaskStatusUpdateEvent`, `TaskState`, `Part`, ...) are **protobuf-generated** classes living in `a2a.types.a2a_pb2`, re-exported via `a2a.types`. Construct them with keyword arguments as shown — they are not plain Pydantic models. `TaskState` is an enum: `TASK_STATE_SUBMITTED`, `TASK_STATE_WORKING`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED`, `TASK_STATE_REJECTED`, `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_AUTH_REQUIRED`.

### TaskUpdater — the ergonomic alternative

Hand-building `TaskStatusUpdateEvent` objects is verbose. `a2a.server.tasks.TaskUpdater` wraps the event queue with named helpers:

```python
from a2a.helpers import new_task_from_user_message
from a2a.server.tasks import TaskUpdater

async def execute(self, context, event_queue):
    task = context.current_task or new_task_from_user_message(context.message)
    await event_queue.enqueue_event(task)          # still required: Task first

    updater = TaskUpdater(event_queue, task.id, task.context_id)
    await updater.start_work()                     # -> WORKING

    rate = await self._fx.get_rate('USD', 'EUR')
    await updater.add_artifact(
        [new_text_part(f'rate = {rate}')], name='conversion_result',
    )
    await updater.complete()                       # -> COMPLETED  (terminal)
```

`TaskUpdater` methods: `submit()`, `start_work()`, `complete()`, `failed()`, `cancel()`, `reject()`, `requires_input()`, `requires_auth()`, plus `update_status(...)` and `add_artifact(...)`.

> **Rule**: `TaskUpdater` does **not** enqueue the initial `Task` for you — you still call `event_queue.enqueue_event(task)` first. `TaskUpdater` also tracks terminal state internally: calling `complete()`/`failed()`/`cancel()` twice raises `RuntimeError`.

---

## 4. The request handler and task store

`DefaultRequestHandler` connects your executor to a `TaskStore` (where task state is persisted between turns) and manages a per-request event queue.

```python
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore

request_handler = DefaultRequestHandler(
    agent_executor=CurrencyConverterExecutor(fx_client),
    task_store=InMemoryTaskStore(),   # dev only — see note below
    agent_card=agent_card,            # required in v1.0 (was on the wrapper in 0.3)
)
```

⚠️ Two v1.0 details that trip people up:

- `DefaultRequestHandler` is an **alias for `DefaultRequestHandlerV2`** — both names import from `a2a.server.request_handlers`. Use `DefaultRequestHandler`.
- `agent_card` is now a **required constructor argument**. In 0.3 it was passed to the (now-deleted) application wrapper.

> **Rule**: `InMemoryTaskStore` loses all task state on restart and does not share state across processes. It is for local development and tests only. Production needs `DatabaseTaskStore` (Postgres/MySQL/SQLite) so tasks survive restarts and are visible to every worker — see [Scaling & Deployment](../05_production/03_scaling_deployment.md).

---

## 5. Serving over HTTP

Compose route factories into a plain Starlette (or FastAPI) app and run it with uvicorn.

```python
import uvicorn
from starlette.applications import Starlette

from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes

routes: list = []
# Serves GET /.well-known/agent-card.json automatically.
routes.extend(create_agent_card_routes(agent_card))
# Serves the JSON-RPC endpoint (send-message, send-streaming-message, etc.).
routes.extend(create_jsonrpc_routes(request_handler, rpc_url='/'))

app = Starlette(routes=routes)
```

The route factories:

| Factory | Serves |
|---|---|
| `create_agent_card_routes(agent_card)` | `GET /.well-known/agent-card.json` (override path with `card_url=`) |
| `create_jsonrpc_routes(handler, rpc_url=...)` | the JSON-RPC transport endpoint |
| `create_rest_routes(handler, path_prefix=...)` | the optional HTTP+JSON/REST transport |

> **Rule**: `rpc_url` must match the path component of the `AgentInterface.url` you put in the Agent Card. If the card advertises `http://host:9999` and you mount JSON-RPC at `/api`, clients posting to `/` get 404s.

**FastAPI** works identically — useful when the agent shares a process with other HTTP endpoints:

```python
from fastapi import FastAPI
app = FastAPI(routes=routes)   # then add your own @app.get(...) routes
```

💡 Because there is no wrapper class, you control middleware directly: add `starlette.middleware.Middleware` for CORS, auth, request logging, or OpenTelemetry exactly as in any Starlette/FastAPI app.

---

## 6. Complete runnable example

`agent_executor.py` plus a `__main__` entry point — a full currency-converter server.

```python
"""Currency Converter A2A server — a2a-sdk 1.0.3. Run: python -m currency_agent"""
import re

import httpx
import uvicorn
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message, new_text_artifact, new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.types.a2a_pb2 import (
    TaskArtifactUpdateEvent,
    TaskState,
    TaskStatus,
    TaskStatusUpdateEvent,
)

_REQUEST = re.compile(r'(?P<amt>[\d.]+)\s*(?P<src>[A-Za-z]{3}).*?(?P<dst>[A-Za-z]{3})')


class FxClient:
    """Thin async wrapper over a public exchange-rate API."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url='https://api.frankfurter.app', timeout=10)

    async def get_rate(self, src: str, dst: str) -> float:
        resp = await self._http.get('/latest', params={'from': src, 'to': dst})
        resp.raise_for_status()
        return resp.json()['rates'][dst]

    async def aclose(self) -> None:
        await self._http.aclose()


class CurrencyConverterExecutor(AgentExecutor):
    def __init__(self, fx_client: FxClient) -> None:
        self._fx = fx_client

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)

        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task.id, context_id=task.context_id,
                status=TaskStatus(
                    state=TaskState.TASK_STATE_WORKING,
                    message=new_text_message('Fetching live rate...'),
                ),
            )
        )

        match = _REQUEST.search(context.get_user_input())
        if not match:
            # ✅ Bad input is an expected outcome — report it as FAILED, with a
            #    human-readable message. Do not raise; raising works too (see §8)
            #    but an explicit message is friendlier to the caller.
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task.id, context_id=task.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=new_text_message(
                            "Could not parse request. Try: 'convert 100 USD to EUR'."
                        ),
                    ),
                )
            )
            return

        amount = float(match['amt'])
        src, dst = match['src'].upper(), match['dst'].upper()
        rate = await self._fx.get_rate(src, dst)
        converted = round(amount * rate, 2)

        await event_queue.enqueue_event(
            TaskArtifactUpdateEvent(
                task_id=task.id, context_id=task.context_id,
                artifact=new_text_artifact(
                    name='conversion_result',
                    text=f'{amount} {src} = {converted} {dst} (rate {rate})',
                ),
            )
        )
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=task.id, context_id=task.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_COMPLETED),
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(
            TaskStatusUpdateEvent(
                task_id=context.task_id, context_id=context.context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_CANCELED),
            )
        )


def build_app() -> Starlette:
    skill = AgentSkill(
        id='convert_currency',
        name='Convert currency',
        description='Converts an amount between two ISO-4217 currency codes.',
        tags=['finance', 'currency', 'fx'],
        examples=['convert 100 USD to EUR', 'how much is 50 GBP in JPY'],
    )
    agent_card = AgentCard(
        name='Currency Converter Agent',
        description='Converts amounts between currencies at live rates.',
        version='1.0.0',
        default_input_modes=['text/plain'],
        default_output_modes=['text/plain'],
        capabilities=AgentCapabilities(streaming=True, extended_agent_card=True),
        supported_interfaces=[
            AgentInterface(
                protocol_binding='JSONRPC',
                protocol_version='1.0',
                url='http://127.0.0.1:9999',
            ),
        ],
        skills=[skill],
    )

    handler = DefaultRequestHandler(
        agent_executor=CurrencyConverterExecutor(FxClient()),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    routes: list = []
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url='/'))
    return Starlette(routes=routes)


if __name__ == '__main__':
    uvicorn.run(build_app(), host='127.0.0.1', port=9999)
```

Verify it is live:

```bash
python -m currency_agent &
curl -s http://127.0.0.1:9999/.well-known/agent-card.json | head
```

Sending messages and consuming the stream is covered in [Part 3: Building a Client](03_building_a_client.md).

---

## 7. How streaming works on the server

A client calls `SendMessage` (buffered) or `SendStreamingMessage` (streaming). The server side is **the same executor** — you do not write a separate streaming path.

```
executor enqueues:   Task ──► WORKING ──► Artifact ──► Artifact ──► COMPLETED
                       │        │           │            │            │
SDK drains queue:      ▼        ▼           ▼            ▼            ▼
SendStreamingMessage: SSE      SSE         SSE          SSE          SSE   (then close)
SendMessage:          (buffered — client gets the final Task once COMPLETED)
```

Every `enqueue_event` call becomes one SSE frame for a streaming client. The implications:

- **Granularity is yours.** Want a progress bar? Emit several `TaskStatusUpdateEvent`s with `WORKING` and descriptive messages. Want token-by-token output? Emit many `TaskArtifactUpdateEvent`s with `append=True` and `last_chunk=True` on the final one.
- **`AgentCapabilities(streaming=True)`** must be set in the Agent Card or clients will not attempt `SendStreamingMessage`.
- **The first event is what unblocks the client.** For a non-streaming `SendMessage` with `return_immediately=True`, the SDK waits only until the first `Task` or `Message` is enqueued.

```python
# Streaming progress: emit chunks as they are produced.
async for chunk in self._llm.stream(prompt):
    await event_queue.enqueue_event(
        TaskArtifactUpdateEvent(
            task_id=task.id, context_id=task.context_id,
            artifact=new_text_artifact(name='answer', text=chunk),
            append=True,          # this chunk appends to the named artifact
        )
    )
await event_queue.enqueue_event(
    TaskArtifactUpdateEvent(
        task_id=task.id, context_id=task.context_id,
        artifact=new_text_artifact(name='answer', text=''),
        append=True, last_chunk=True,      # signal end of the artifact stream
    )
)
```

> **Key insight**: There is no "streaming mode" to opt into. The executor always emits a sequence of events; the transport decides whether to relay them as SSE or buffer them into one final response.

---

## 8. Failure modes

The mistakes that cost the most debugging time, and how to avoid them.

### Forgetting to mark the task terminal

```python
# ❌ Task never reaches a terminal state — clients poll/stream forever.
async def execute(self, context, event_queue):
    task = new_task_from_user_message(context.message)
    await event_queue.enqueue_event(task)
    result = await self._agent.run(...)
    await event_queue.enqueue_event(TaskArtifactUpdateEvent(...))
    # missing: a COMPLETED / FAILED status update
```

> **Rule**: Every `execute()` path — success, handled error, early return — must end the task in a terminal state: `COMPLETED`, `FAILED`, `CANCELED`, or `REJECTED`. The exceptions are `INPUT_REQUIRED` / `AUTH_REQUIRED`, which intentionally pause the task and yield control. A task with no terminal event is a resource leak.

### Blocking the event loop with sync code

```python
# ❌ Synchronous I/O freezes the entire server — every concurrent request stalls.
import time, requests
async def execute(self, context, event_queue):
    time.sleep(2)                          # blocks the loop
    data = requests.get('https://...')     # blocks the loop
```

```python
# ✅ Use async I/O. For unavoidable sync/CPU-bound work, offload it.
import asyncio
async def execute(self, context, event_queue):
    data = await self._httpx.get('https://...')          # async client
    result = await asyncio.to_thread(cpu_bound_parse, data)  # thread offload
```

> **Rule**: The executor runs on the server's asyncio event loop. Any blocking call (`time.sleep`, `requests`, sync DB drivers, heavy CPU loops) stalls *all* in-flight requests. Use async libraries, or push blocking work to `asyncio.to_thread` / a process pool.

### Executor exceptions and the `FAILED` state

An **unhandled** exception in `execute()` is caught by the SDK and the task is transitioned to a terminal error state automatically — the server does not crash.

```python
# This is acceptable: the SDK catches it and marks the task terminal-error.
async def execute(self, context, event_queue):
    task = new_task_from_user_message(context.message)
    await event_queue.enqueue_event(task)
    rate = await self._fx.get_rate('USD', 'EUR')   # may raise httpx.HTTPError
    ...
```

But relying on that has two downsides: the client gets a generic error with no useful message, and any cleanup you needed is skipped. Prefer catching expected failures and emitting an explicit `FAILED` status with a human-readable message (as in §6):

```python
try:
    rate = await self._fx.get_rate(src, dst)
except httpx.HTTPError as exc:
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            task_id=task.id, context_id=task.context_id,
            status=TaskStatus(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message(f'Rate service unavailable: {exc}'),
            ),
        )
    )
    return
```

⚠️ Other common breakage:

- **Mixing event modes** — enqueuing a `Message` after a `Task`, or a status event before the `Task` — raises `InvalidAgentResponseError` in v1.0. Pick message-mode or task-mode and stay in it.
- **`cancel()` that does nothing** — if cancellation is genuinely unsupported, raise `UnsupportedOperationError()` so the client gets a clear signal, rather than silently returning.
- **`InMemoryTaskStore` behind multiple workers** — each worker has its own store, so a follow-up turn routed to a different worker cannot find the task. Use a shared `DatabaseTaskStore` once you scale out ([Scaling & Deployment](../05_production/03_scaling_deployment.md)).

> **Key insight**: The executor's job is not just "produce a result" — it is to *correctly drive the task lifecycle*. A result with no terminal state, or an exception with no `FAILED` event, is a broken task even if the computation succeeded.

---

**Next**: [Part 3: Building a Client](03_building_a_client.md)
