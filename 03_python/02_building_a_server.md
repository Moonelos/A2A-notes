# Building an A2A Server with the Python SDK

<!-- length-justification: This implementation note keeps the runnable baseline and the same server's executor, streaming, shutdown, and failure paths together so readers can trace one lifecycle end to end. -->

> **Who this is for**: Python engineers who have completed [SDK Setup](01_sdk_setup.md) and want to expose an agent over the A2A protocol. Run the echo baseline first; [Task Lifecycle](../02_protocol/03_task_lifecycle.md) explains the states before you change executor behavior. Targets `a2a-sdk` **1.1.2**.

---

For a runnable executor that asks a question, emits custom stage metadata and streams an Artifact in chunks, use the [report streaming lab](../02_protocol/00_client_server_walkthrough.md#5-run-the-same-interaction-and-watch-it-arrive) alongside this server reference.

## 1. The server in four pieces

An A2A server has separate discovery and task routes. The echo exchange below follows both routes; the card is served by the app and never passes through the executor.

```mermaid
sequenceDiagram
  participant C as Echo client
  participant App as Starlette routes
  participant H as DefaultRequestHandler
  participant E as EchoExecutor
  participant Q as EventQueue / TaskStore
  C->>App: GET /.well-known/agent-card.json
  App-->>C: Echo Agent card
  C->>App: SendMessage("hello")
  App->>H: dispatch message
  H->>E: execute(context, event_queue)
  E->>Q: enqueue Task(id, SUBMITTED)
  E->>Q: WORKING, echo Artifact, COMPLETED
  Q-->>H: terminal Task state
  H-->>C: Task COMPLETED; echo: hello
```

The handler owns dispatch and task persistence; the executor only emits lifecycle events. The initial Task establishes identity before later status and Artifact events. A streaming request receives those events in order as SSE; the synchronous `SendMessage` call shown here returns the terminal Task.

> **Rule**: You implement exactly one thing — the `AgentExecutor`. Everything else is SDK plumbing you assemble.

### Run the four pieces as one server

This baseline accepts one text Message and returns a completed Task with an echo Artifact. Save it as `echo_server.py` after installing `a2a-sdk[http-server]==1.1.2` and `uvicorn`:

```python
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill


class EchoExecutor(AgentExecutor):
    async def execute(self, context, event_queue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        await updater.add_artifact(
            [new_text_part(f"echo: {context.get_user_input()}")], name="echo"
        )
        await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        task = context.current_task
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.cancel()


card = AgentCard(
    name="Echo Agent",
    description="Returns the text it receives.",
    version="0.1.0",
    supported_interfaces=[AgentInterface(
        url="http://127.0.0.1:9999",
        protocol_binding="JSONRPC",
        protocol_version="1.0",
    )],
    capabilities=AgentCapabilities(),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(
        id="echo", name="Echo", description="Echo text.", tags=["demo"]
    )],
)
handler = DefaultRequestHandler(
    agent_executor=EchoExecutor(),
    task_store=InMemoryTaskStore(),
    agent_card=card,
)


@asynccontextmanager
async def lifespan(app):
    yield
    await handler.aclose()  # drain ActiveTask background work before shutdown


routes = [*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")]
app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9999)
```

Run it and send one request from another shell:

```bash
python echo_server.py
curl -s http://127.0.0.1:9999/ \
  -H 'Content-Type: application/json' \
  -H 'A2A-Version: 1.0' \
  -d '{"jsonrpc":"2.0","id":"demo-1","method":"SendMessage","params":{"message":{"messageId":"msg-1","role":"ROLE_USER","parts":[{"text":"hello"}]}}}'
```

The first client Message supplies `messageId` but no Task/context IDs. In this baseline, `new_task_from_user_message(context.message)` allocates the Task ID and a context when absent; `TaskUpdater` emits its state and output events. On an existing-Task continuation, the handler resolves `context.current_task`, so the executor reuses that object. The server handler must reject unknown Task references before execution: a low-level helper accepting an ID is not permission for a client to create remote work under an invented Task ID. The executor chooses Task output here; a direct Message response is also possible in A2A. See the [identity walkthrough](../01_fundamentals/02_core_concepts.md#who-creates-each-id).

Success is a response whose `result.task.status.state` is `TASK_STATE_COMPLETED` and whose Artifact text is `echo: hello`. A `404` means `rpc_url` and the advertised interface path disagree; an import failure naming Starlette means the `http-server` extra is missing.

> **Production:** this baseline uses process-local task state and no authentication. The rest of this note explains the pieces; [Authentication](../05_production/01_authentication.md), [Security Hardening](../05_production/02_security_hardening.md), and [Scaling & Deployment](../05_production/03_scaling_deployment.md) own the production boundary.

⚠️ **v1.0 breaking change**: SDK 0.3 shipped wrapper classes `A2AStarletteApplication` / `A2AFastAPIApplication` with a `.build()` method. **These were removed in v1.0.** Server setup now uses route factory functions (`create_jsonrpc_routes`, `create_agent_card_routes`, `create_rest_routes`) composed directly into a plain Starlette or FastAPI app. Any tutorial showing `A2AStarletteApplication` is pre-1.0 and will not import.

Install the HTTP server extra (from [SDK Setup](01_sdk_setup.md)):

```bash
uv add "a2a-sdk[http-server]==1.1.2"   # keep the teaching baseline pinned
```

---

For incoming annotations, SDK1.1.2 exposes request `params.metadata` as `context.metadata` (a plain dict). The separate client Message annotations are in `context.message.metadata` (a protobuf Struct). Neither is automatically Task metadata. If you need a validated request label on returned work, explicitly assign it to `task.metadata` before publishing/persisting the Task. `TaskUpdater.update_status(metadata=...)` annotates the status **event**, while `TaskUpdater.add_artifact(metadata=...)` annotates the **Artifact**. The pinned server TaskManager additionally merges status-event metadata into stored Task metadata; this is SDK behavior, not automatic copying of client annotations or a durable event history. See the [ownership and propagation example](../01_fundamentals/02_core_concepts.md#metadata-who-writes-it-and-what-it-belongs-to) and the [live lab](../02_protocol/00_client_server_walkthrough.md#who-sets-the-metadata-in-these-examples).

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

The executor never *returns* a result — it **enqueues events**. The SDK drains the queue, persists task state, and, for streaming, emits **Server-Sent Events (SSE)** frames. There are two legal event shapes:

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
from a2a.helpers import new_task_from_user_message, new_text_part
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

The observable result is a Task in `TASK_STATE_COMPLETED` with a `conversion_result` Artifact containing `rate = ...`. A `NameError: new_text_part` means the helper import was omitted.

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
"""Currency Converter A2A server — a2a-sdk 1.1.2. Run: python -m currency_agent"""
from contextlib import asynccontextmanager
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
        try:
            rate = await self._fx.get_rate(src, dst)
        except (httpx.HTTPError, KeyError, ValueError):
            # URLs and upstream response bodies may contain sensitive data.
            await event_queue.enqueue_event(
                TaskStatusUpdateEvent(
                    task_id=task.id, context_id=task.context_id,
                    status=TaskStatus(
                        state=TaskState.TASK_STATE_FAILED,
                        message=new_text_message('Rate service temporarily unavailable'),
                    ),
                )
            )
            return
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

    fx_client = FxClient()
    handler = DefaultRequestHandler(
        agent_executor=CurrencyConverterExecutor(fx_client),
        task_store=InMemoryTaskStore(),
        agent_card=agent_card,
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await handler.aclose()  # drain ActiveTask work before dependencies close
        await fx_client.aclose()  # release the owned HTTP connection pool

    routes: list = []
    routes.extend(create_agent_card_routes(agent_card))
    routes.extend(create_jsonrpc_routes(handler, rpc_url='/'))
    return Starlette(routes=routes, lifespan=lifespan)


if __name__ == '__main__':
    uvicorn.run(build_app(), host='127.0.0.1', port=9999)
```

First verify discovery only:

```bash
python -m currency_agent &
curl -s http://127.0.0.1:9999/.well-known/agent-card.json | head
```

That card request proves the route exists; it does not test conversion. For a deterministic conversion check without calling the public rate API, save the complete block above as `currency_agent.py` and run this local fixture in the same directory. It replaces only the external rate lookup and exercises the actual A2A JSON-RPC route:

```bash
python - <<'PY'
import asyncio
import httpx
import currency_agent

async def fake_rate(self, src, dst):
    assert (src, dst) == ('USD', 'EUR')
    return 0.9

async def main():
    currency_agent.FxClient.get_rate = fake_rate
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=currency_agent.build_app()),
        base_url='http://127.0.0.1:9999',
    ) as client:
        request = {'jsonrpc': '2.0', 'id': 'fx-1', 'method': 'SendMessage',
                   'params': {'message': {'messageId': 'fx-msg-1', 'role': 'ROLE_USER',
                                          'parts': [{'text': 'convert 100 USD to EUR'}]}}}
        response = await client.post('/', json=request, headers={'A2A-Version': '1.0'})
        response.raise_for_status()
        task = response.json()['result']['task']
        print(task['status']['state'])
        print(task['artifacts'][0]['parts'][0]['text'])

asyncio.run(main())
PY
```

Expected output is `TASK_STATE_COMPLETED` followed by `100.0 USD = 90.0 EUR (rate 0.9)`. To test the failed-rate path, make `fake_rate` raise `httpx.ConnectError('secret=sentinel')`; the Task must be `TASK_STATE_FAILED`, and its serialized public status must not contain `sentinel`. The fixture is a loopback/in-process test; use an authorized integration environment to test the real external provider and network timeouts.

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

There is no separate executor streaming mode. The executor emits events; the transport either relays them as SSE or buffers them into one final response.

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
except httpx.HTTPError:
    await event_queue.enqueue_event(
        TaskStatusUpdateEvent(
            task_id=task.id, context_id=task.context_id,
            status=TaskStatus(
                state=TaskState.TASK_STATE_FAILED,
                message=new_text_message('Rate service temporarily unavailable'),
            ),
        )
    )
    return
```

An HTTP exception may contain a URL with query parameters or credentials. Keep the public status fixed; record the internal failure against a correlation/task ID in a restricted log after sanitizing its fields. In a failure test, inject a URL containing a sentinel secret and assert that the serialized Task status does not contain the sentinel.

⚠️ Other common breakage:

- **Mixing event modes** — enqueuing a `Message` after a `Task`, or a status event before the `Task` — raises `InvalidAgentResponseError` in v1.0. Pick message-mode or task-mode and stay in it.
- **`cancel()` that does nothing** — if cancellation is genuinely unsupported, raise `UnsupportedOperationError()` so the client gets a clear signal, rather than silently returning.
- **`InMemoryTaskStore` behind multiple workers** — each worker has its own store, so a follow-up turn routed to a different worker cannot find the task. Use a shared `DatabaseTaskStore` once you scale out ([Scaling & Deployment](../05_production/03_scaling_deployment.md)).

> **Key insight**: The executor's job is not just "produce a result" — it is to *correctly drive the task lifecycle*. A result with no terminal state, or an exception with no `FAILED` event, is a broken task even if the computation succeeded.

---

**Next**: [Part 3: Building a Client](03_building_a_client.md)

## Recap, check yourself, and try it

- The card route advertises the interface. The request handler dispatches a Message to the executor and stores the Task events it emits.
- The executor emits the Task before status or Artifact updates, then a terminal status so the caller knows the work finished.
- An expected external failure becomes a fixed, public `FAILED` status; exception internals stay in restricted diagnostics.

**Q: EchoExecutor adds an Artifact but never calls `updater.complete()`. What does the caller observe?**

<details><summary>Answer</summary>

The Task has output but no terminal status. A synchronous caller can wait until its timeout, and a stream cannot signal normal completion. The executor must emit a terminal state after its final result.

</details>

**Try it:** modify `EchoExecutor.execute` so blank input fails before adding an Artifact. Keep the initial Task event, then insert an early branch after creating `TaskUpdater`. Hint: use `updater.failed(...)` with a fixed public message and return.

<details><summary>Worked solution</summary>

After `updater = TaskUpdater(...)`, check `if not context.get_user_input().strip(): await updater.failed(new_text_message("Input must contain text")); return`. Then run the same curl request with an empty text Part and check for `TASK_STATE_FAILED` and no echo Artifact. This preserves Task-first event order while making the error terminal.

</details>
