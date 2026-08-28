# A2A with LangChain / LangGraph

<!-- length-justification: This integration note keeps the baseline adapter, checkpoint/interrupt mapping, streaming bridge, reverse client tool, and hosted alternative together because they share one context and lifecycle mapping. -->

> **Who this is for**: Engineers who build agents with LangChain/LangGraph and want to expose them over A2A — and call remote A2A agents from inside a graph. You should have read **[Building a Server](../03_python/02_building_a_server.md)** and **[Building a Client](../03_python/03_building_a_client.md)** first; this file assumes you know `AgentExecutor`, `RequestContext`, `EventQueue`, and the A2A client API.

There is no separate `langchain-a2a` package. A small `AgentExecutor` adapter maps LangGraph output onto A2A Task events; LangSmith's hosted Agent Server is the managed alternative.

## Quick start: expose one LangChain agent

You need `OPENAI_API_KEY` plus `a2a-sdk[http-server]==1.1.2`, `langchain`, `langchain-openai`, and `uvicorn`. Save this one-file baseline as `langgraph_a2a.py`:

```python
from contextlib import asynccontextmanager

import uvicorn
from langchain.agents import create_agent
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill

graph = create_agent(
    model="openai:gpt-4.1-mini",
    tools=[],
    system_prompt="Answer in one short sentence.",
)


class LangGraphExecutor(AgentExecutor):
    async def execute(self, context, event_queue) -> None:
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        result = await graph.ainvoke({
            "messages": [{"role": "user", "content": context.get_user_input()}]
        })
        await updater.add_artifact(
            [new_text_part(result["messages"][-1].content)], name="answer"
        )
        await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        task = context.current_task
        await TaskUpdater(event_queue, task.id, task.context_id).cancel()


card = AgentCard(
    name="LangGraph Answer Agent",
    description="Answers short questions through a LangChain agent graph.",
    version="0.1.0",
    supported_interfaces=[AgentInterface(
        url="http://127.0.0.1:10000", protocol_binding="JSONRPC", protocol_version="1.0"
    )],
    capabilities=AgentCapabilities(),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(
        id="answer", name="Answer", description="Answer a question.", tags=["qa"]
    )],
)
handler = DefaultRequestHandler(LangGraphExecutor(), InMemoryTaskStore(), card)


@asynccontextmanager
async def lifespan(app):
    yield
    await handler.aclose()


app = Starlette(
    routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")],
    lifespan=lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=10000)
```

Start it with `python langgraph_a2a.py`, then send the versioned JSON-RPC request from the Python client quick start. Success is a `TASK_STATE_COMPLETED` Task with an `answer` Artifact. A `401` from the model provider means the model credential is missing; a Task stuck in `WORKING` means the adapter failed to emit `complete()` or `failed()`.

> **Production:** this baseline has no persistent checkpointer or authentication. The rest of the note explains mapping, interrupts, streaming, and remote-agent tools before production deployment.

---

## 1. The integration pattern

A LangGraph app is a compiled `StateGraph` or an agent created with `langchain.agents.create_agent`. A2A does not know about graphs — it knows about Tasks, states, and artifacts. One adapter implements `AgentExecutor` and drives the graph.

```
┌─────────────────── A2A Server (a2a-sdk) ───────────────────┐
│  Starlette/FastAPI app                                      │
│    └─ create_jsonrpc_routes + create_agent_card_routes      │
│         └─ DefaultRequestHandler(executor, store, card)     │
│              └─ CurrencyAgentExecutor(AgentExecutor)        │
│              execute(context, event_queue)                  │
│                 │                                           │
│                 ▼   wraps                                   │
│         ┌──────────────────────────┐                        │
│         │  LangGraph compiled app  │   graph.ainvoke / .astream
│         │  (StateGraph / ReAct)    │                        │
│         └──────────────────────────┘                        │
│                 │                                           │
│   LangGraph output ──▶ TaskUpdater ──▶ EventQueue ──▶ SSE   │
│   (messages,            update_status / add_artifact        │
│    tool_calls,                                              │
│    interrupts)                                              │
└─────────────────────────────────────────────────────────────┘
```

> **Rule**: The `AgentExecutor` is the *only* place the two worlds meet. Keep LangGraph types (`AIMessage`, `ToolMessage`, `Command`) inside the executor; never leak them past the `EventQueue`.

The mapping you must implement:

| LangGraph concept                  | A2A concept                                              |
|-------------------------------------|----------------------------------------------------------|
| Graph still running, tool call fired | `TASK_STATE_WORKING` + status update message            |
| Graph finished, final answer        | `TaskArtifactUpdateEvent` + `TASK_STATE_COMPLETED`       |
| `interrupt()` / needs user input    | `TASK_STATE_INPUT_REQUIRED` (terminal status update)     |
| Exception raised in a node          | `TASK_STATE_FAILED` or an `A2AError` subclass            |
| `thread_id` (checkpointer key)      | A2A `contextId`                                          |

> **v1.0 note**: `TaskState` is a protobuf enum — use the `TASK_STATE_*` constants
> (`TaskState.TASK_STATE_WORKING`, etc.), not lowercase attributes. Reaching
> `COMPLETED`/`FAILED`/`CANCELED`/`REJECTED` (or `INPUT_REQUIRED`) is itself the
> terminal signal; there is no separate `final=` flag on `update_status`.

The `thread_id` ↔ `contextId` mapping is what makes multi-turn work: A2A's `contextId` is stable across a conversation, so using it as the LangGraph checkpointer `thread_id` means the graph resumes from its saved checkpoint on every follow-up message.

---

## 2. Serving a LangGraph agent over A2A

Two files: `agent.py` (pure LangGraph, no A2A imports) and `agent_executor.py` (the adapter). This mirrors `a2a-samples/samples/python/agents/langgraph/`.

**`agent.py`** — the graph, framework-agnostic:

```python
from collections.abc import AsyncIterable
from typing import Any, Literal

from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langchain.agents import create_agent
from pydantic import BaseModel

memory = MemorySaver()  # swap for AsyncPostgresSaver in production


@tool
def get_exchange_rate(currency_from: str = "USD", currency_to: str = "EUR") -> dict:
    """Return the current exchange rate between two currencies."""
    import httpx
    resp = httpx.get(
        "https://api.frankfurter.app/latest",
        params={"from": currency_from, "to": currency_to},
    )
    resp.raise_for_status()
    return resp.json()


class ResponseFormat(BaseModel):
    """Structured output the executor inspects to pick an A2A state."""
    status: Literal["input_required", "completed", "error"] = "input_required"
    message: str


class CurrencyAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self) -> None:
        self.graph = create_agent(
            model=ChatOpenAI(model="gpt-4o", temperature=0),
            tools=[get_exchange_rate],
            checkpointer=memory,
            system_prompt="You are a currency-conversion assistant.",
            # response_format forces a typed result the executor can branch on.
            response_format=ResponseFormat,
        )

    async def stream(self, query: str, context_id: str) -> AsyncIterable[dict[str, Any]]:
        inputs = {"messages": [("user", query)]}
        # contextId is the checkpointer thread_id — this is how multi-turn resumes.
        config = {"configurable": {"thread_id": context_id}}

        async for item in self.graph.astream(inputs, config, stream_mode="values"):
            message = item["messages"][-1]
            if isinstance(message, AIMessage) and message.tool_calls:
                yield {"done": False, "needs_input": False,
                       "content": "Looking up exchange rates..."}
            elif isinstance(message, ToolMessage):
                yield {"done": False, "needs_input": False,
                       "content": "Processing exchange rates..."}

        yield self._final(config)

    def _final(self, config: dict) -> dict[str, Any]:
        state = self.graph.get_state(config)
        result: ResponseFormat | None = state.values.get("structured_response")
        if not result:
            return {"done": False, "needs_input": True,
                    "content": "Unable to process your request."}
        if result.status == "completed":
            return {"done": True, "needs_input": False, "content": result.message}
        # input_required and error both ask the caller for more info
        return {"done": False, "needs_input": True, "content": result.message}
```

**`agent_executor.py`** — the A2A adapter. Imports/APIs below target the repository's `a2a-sdk` 1.1.2 baseline:

```python
import logging

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.tasks import TaskUpdater
from a2a.helpers.proto_helpers import new_task_from_user_message
from a2a.types import InternalError, Part, TaskState, UnsupportedOperationError
from a2a.utils.errors import ServerError

from app.agent import CurrencyAgent

logger = logging.getLogger(__name__)


class CurrencyAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.agent = CurrencyAgent()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        task = context.current_task
        if not task:
            # First message of a conversation -> create the Task.
            # task_id / context_id are pre-computed on the RequestContext.
            task = new_task_from_user_message(context.message)
            task.id = context.task_id
            task.context_id = context.context_id
            task.status.state = TaskState.TASK_STATE_WORKING
            await event_queue.enqueue_event(task)

        # TaskUpdater is the bridge: every call emits an event onto the queue.
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        try:
            async for item in self.agent.stream(query, context.context_id):
                # A Part is a protobuf oneof; build a text part directly.
                msg = updater.new_agent_message([Part(text=item["content"])])

                if not item["done"] and not item["needs_input"]:
                    # Graph still running -> working state.
                    await updater.update_status(TaskState.TASK_STATE_WORKING, msg)

                elif item["needs_input"]:
                    # LangGraph wants more from the user -> input-required.
                    # INPUT_REQUIRED is itself the terminal status; no final= flag.
                    await updater.update_status(
                        TaskState.TASK_STATE_INPUT_REQUIRED, msg
                    )
                    break

                else:
                    # Final answer -> emit an artifact, then complete the Task.
                    await updater.add_artifact(
                        [Part(text=item["content"])],
                        name="conversion_result",
                    )
                    await updater.complete()
                    break

        except Exception as e:
            logger.exception("LangGraph execution failed")
            # Keep details in server logs; the protocol gets a stable generic error.
            raise ServerError(error=InternalError()) from e

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        # LangGraph has no built-in mid-run cancel; reject unless you wire one.
        raise ServerError(error=UnsupportedOperationError(message="cancel not implemented"))
```

**`__main__.py`** — wire it into a Starlette app. In v1.0 the server app classes
(`A2AStarletteApplication` / `A2AFastAPIApplication`) were **removed**; you now build
the app yourself from route-factory functions in `a2a.server.routes`:

```python
import uvicorn
from starlette.applications import Starlette
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from a2a.utils import TransportProtocol

from app.agent import CurrencyAgent
from app.agent_executor import CurrencyAgentExecutor

skill = AgentSkill(
    id="convert_currency",
    name="Currency Exchange Rates Tool",
    description="Converts values between currencies.",
    tags=["currency"],
    examples=["What is the USD to GBP rate?"],
)
# v1.0: the endpoint URL lives in `supported_interfaces` (a list of
# AgentInterface), not a single top-level `url` field.
agent_card = AgentCard(
    name="Currency Agent",
    description="Helps with currency exchange rates.",
    version="1.0.0",
    default_input_modes=CurrencyAgent.SUPPORTED_CONTENT_TYPES,
    default_output_modes=CurrencyAgent.SUPPORTED_CONTENT_TYPES,
    capabilities=AgentCapabilities(streaming=True),
    skills=[skill],
    supported_interfaces=[
        AgentInterface(
            protocol_binding=TransportProtocol.JSONRPC,
            protocol_version="1.0",
            url="http://localhost:10000/",
        ),
    ],
)

# DefaultRequestHandler is positional: (agent_executor, task_store, agent_card).
# The agent_card argument is required in v1.0.
request_handler = DefaultRequestHandler(
    CurrencyAgentExecutor(),
    InMemoryTaskStore(),
    agent_card,
)

# Build the Starlette app yourself from the route factories and mount them.
routes = create_jsonrpc_routes(request_handler=request_handler, rpc_url="/")
routes += create_agent_card_routes(agent_card=agent_card)  # /.well-known/agent-card.json
app = Starlette(routes=routes)

if __name__ == "__main__":
    uvicorn.run(app, host="localhost", port=10000)
```

> **Migration note**: `create_jsonrpc_routes(request_handler, rpc_url, ...)` and
> `create_agent_card_routes(agent_card, card_url=AGENT_CARD_WELL_KNOWN_PATH)` each
> return a `list[starlette.routing.Route]`. Concatenate them and pass to
> `Starlette(routes=...)` — or `FastAPI(routes=...)`, or `app.mount(prefix, ...)`
> a sub-app. Requires the `a2a-sdk[http-server]` extra (pulls in `starlette`).

> **Rule**: `agent.py` must not import `a2a`. If you ever need to test the graph in isolation, or reuse it behind a non-A2A interface, that boundary is what makes it possible.

---

## 3. Interrupts / human-in-the-loop → `input-required`

LangGraph has two ways a graph pauses for a human:

1. **`response_format` status field** (above) — the model itself decides it needs more info and emits `status="input_required"`. Simple, no checkpointer surgery.
2. **`interrupt()`** — a node calls `langgraph.types.interrupt(...)`, which suspends the graph at a checkpoint until you resume with a `Command(resume=...)`.

Both map to the same A2A state: **`TaskState.TASK_STATE_INPUT_REQUIRED`**. Reaching that state is itself the terminal signal on the stream — there is no `final=` flag in v1.0. The A2A client treats it as "the Task is paused; send another `SendMessage` request on the same `contextId` to continue."

```python
from langgraph.types import Command

async def stream(self, query: str, context_id: str):
    config = {"configurable": {"thread_id": context_id}}

    # Resume a paused graph, or start a fresh run.
    state = await self.graph.aget_state(config)
    if state.next:                       # graph is parked at an interrupt
        graph_input = Command(resume=query)
    else:
        graph_input = {"messages": [("user", query)]}

    async for chunk in self.graph.astream(graph_input, config, stream_mode="values"):
        ...

    # After the stream ends, check whether the graph hit a fresh interrupt.
    state = await self.graph.aget_state(config)
    if state.interrupts:
        # StateSnapshot.interrupts is the current public interrupt surface.
        interrupt_payload = [interrupt.value for interrupt in state.interrupts]
        yield {"done": False, "needs_input": True,
               "content": str(interrupt_payload)}
```

The executor side is unchanged — `needs_input` still drives `update_status(TaskState.TASK_STATE_INPUT_REQUIRED, msg)`.

`input-required` is neither failure nor completion. The Task is alive but waiting, and `contextId` keeps the checkpoint addressable for the next Message.

⚠️ If you drop the `contextId` → `thread_id` mapping (e.g. generate a new UUID per request), the resume reads an empty checkpoint and the graph restarts from scratch — silently losing the conversation.

---

## 4. Streaming: `graph.astream(...)` → A2A SSE

A2A streaming is `SendStreamingMessage`: the server pushes `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` frames over Server-Sent Events. LangGraph's `astream` has several **`stream_mode`** values — pick based on the granularity you want to forward:

| `stream_mode`  | Yields                                  | Forward to A2A as                       |
|----------------|------------------------------------------|------------------------------------------|
| `"values"`     | full state after each node               | coarse `working` status updates          |
| `"updates"`    | only the delta each node produced        | per-node progress (`working`)            |
| `"messages"`   | LLM token chunks `(token, metadata)`     | token-level streaming into an artifact   |
| `"custom"`     | whatever a node emits via `StreamWriter` | app-defined progress signals             |

Token-level streaming — bridge `"messages"` mode into incremental artifact updates:

```python
async def execute(self, context, event_queue):
    task = context.current_task
    if not task:
        task = new_task_from_user_message(context.message)
        task.id = context.task_id
        task.context_id = context.context_id
        task.status.state = TaskState.TASK_STATE_WORKING
        await event_queue.enqueue_event(task)
    updater = TaskUpdater(event_queue, context.task_id, context.context_id)

    config = {"configurable": {"thread_id": context.context_id}}
    inputs = {"messages": [("user", context.get_user_input())]}
    buffer = ""

    async for token, metadata in self.graph.astream(
        inputs, config, stream_mode="messages"
    ):
        if not token.content:            # skip tool-call-only chunks
            continue
        buffer += token.content
        # Each TaskArtifactUpdateEvent with append=True grows the same artifact.
        await updater.update_status(
            TaskState.TASK_STATE_WORKING,
            updater.new_agent_message([Part(text="streaming...")]),
        )
        await updater.add_artifact(
            [Part(text=token.content)],
            name="answer",
            append=True,            # append to the existing artifact
            last_chunk=False,
        )

    await updater.add_artifact(
        [Part(text="")], name="answer", append=True, last_chunk=True
    )
    await updater.complete()
```

> **Rule**: Emit a terminal frame. The SSE stream stays open until the Task reaches `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, or `TASK_STATE_INPUT_REQUIRED`. If `astream` finishes but you never call `updater.complete()`, the client hangs until timeout.

💡 Use `stream_mode=["values", "messages"]` (a list) to get both node-level state and token chunks in one pass — useful when you want progress status *and* streamed text.

---

## 5. Consumption side: calling a remote A2A agent as a LangChain `@tool`

The reverse direction: a local LangGraph agent **delegates** to a remote A2A agent. Wrap the A2A client call in a `@tool` so the model can invoke it like any other tool. This is the cleanest way to do A2A-based multi-agent routing inside a graph.

```python
import uuid
import httpx
from langchain_core.tools import tool

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_message_text, get_artifact_text
from a2a.types import Message, Part, Role, SendMessageRequest


REMOTE_URL = "http://localhost:10000"


@tool
async def ask_currency_agent(question: str) -> str:
    """Delegate a currency-conversion question to the remote A2A currency agent.

    Use this whenever the user asks about exchange rates between currencies.
    """
    async with httpx.AsyncClient(timeout=30.0) as httpx_client:
        # 1. Resolve the AgentCard from /.well-known/agent-card.json.
        resolver = A2ACardResolver(httpx_client=httpx_client, base_url=REMOTE_URL)
        agent_card = await resolver.get_agent_card()

        # 2. Build a client; ClientFactory picks streaming vs non-streaming
        #    based on the card's declared capabilities.
        factory = ClientFactory(ClientConfig(httpx_client=httpx_client))
        client = factory.create(agent_card)

        # 3. Send a message. v1.0: build a protobuf Message (Role.ROLE_USER,
        #    Part oneof) and wrap it in a SendMessageRequest. send_message
        #    yields StreamResponse objects (a oneof of task / message /
        #    status_update / artifact_update).
        outgoing = Message(
            role=Role.ROLE_USER,
            parts=[Part(text=question)],
            message_id=str(uuid.uuid4()),
        )
        request = SendMessageRequest(message=outgoing)

        final_text = ""
        async for response in client.send_message(request):
            if response.HasField("artifact_update"):
                final_text += get_artifact_text(response.artifact_update.artifact)
            elif response.HasField("task"):
                for artifact in response.task.artifacts:
                    final_text += get_artifact_text(artifact)
            elif response.HasField("message"):
                final_text += get_message_text(response.message)

        return final_text or "No response from currency agent."
```

Now attach the tool to the local graph — the remote A2A agent is indistinguishable from a normal tool:

```python
from langchain.agents import create_agent
from langchain_openai import ChatOpenAI

orchestrator = create_agent(
    model=ChatOpenAI(model="gpt-4o"),
    tools=[ask_currency_agent],          # remote A2A agent, exposed as a tool
    system_prompt="Route currency questions to the currency agent.",
)
```

An A2A agent and a local Python function can look alike after both are wrapped as tools. A2A adds the separately deployed peer contract behind that wrapper.

⚠️ Prefer an async tool for network calls. Current LangChain can offload a synchronous `@tool` through its executor, but that consumes the shared thread pool and becomes a scalability limit. Blocking I/O executed directly inside an async node or coroutine still stalls the event loop.

💡 Resolving the `AgentCard` on every call is wasteful. In production, resolve cards once at startup and cache `agent_card` (and the `httpx.AsyncClient`) so each tool call is just a `send_message`.

---

## 6. LangSmith Agent Server: A2A without writing an executor

If you deploy graphs to LangSmith's hosted **Agent Server**, A2A is built in — you do **not** write an `AgentExecutor`. Every deployed assistant is automatically reachable at:

```
POST /a2a/{assistant_id}                       # platform-documented: message/send, message/stream, tasks/get
GET  /.well-known/agent-card.json?assistant_id={assistant_id}
```

Requirements and config (checked August 2026):

- Needs `langgraph-api >= 0.4.21`.
- A2A is **on by default**. Disable it per-deployment in `langgraph.json`:

```json
{
  "http": { "disable_a2a": true }
}
```

⚠️ Hosted framework endpoints are platform compatibility surfaces. Fetch the deployed card and test the exact version, binding, methods, and part shapes it advertises before mixing it with strict 1.0 clients. The hand-written executor examples above target `a2a-sdk` 1.1.2 and the 1.0 protobuf model.

The hosted server maps Agent Server runs onto A2A Tasks for you. The trade-off vs. a hand-written executor: you give up control over the LangGraph-output → artifact mapping (§1) and over interrupt handling (§3). For full control — custom artifact names, multi-part outputs, bespoke interrupt payloads — write the `AgentExecutor` yourself as in §2.

> **Rule**: Use Agent Server's built-in A2A for standard request/response and streaming. Drop to a hand-written `AgentExecutor` when you need custom event mapping or non-trivial human-in-the-loop semantics.

---

## 7. Failure modes

| Failure                                  | Symptom                                              | Fix                                                                 |
|-------------------------------------------|------------------------------------------------------|----------------------------------------------------------------------|
| Blocking I/O directly inside an async node | Event loop stalls; SSE stream freezes for all clients | Use `graph.astream` / `ainvoke` and async clients; bound any sync-tool thread pool |
| Lost `contextId` ↔ `thread_id` mapping    | Multi-turn "forgets"; interrupts restart the graph    | Always set `thread_id = task.context_id` in the checkpointer config  |
| Error swallowed instead of propagated     | Task stuck in `working` forever; client times out     | Call `updater.failed(...)` or raise `ServerError(error=InternalError())` |
| Stream ends without a terminal state      | SSE connection hangs until client timeout             | Always reach a terminal state: `updater.complete()`, `updater.failed()`, or `update_status(TASK_STATE_INPUT_REQUIRED, ...)` |
| In-memory checkpointer in production      | Conversation state lost on restart / not shared       | Use `AsyncPostgresSaver` (or another persistent checkpointer)        |
| `cancel()` not implemented                | Client cancel is a silent no-op                       | Implement `cancel`, or explicitly reject with `UnsupportedOperationError` |

**Blocking calls** — distinguish an offloaded sync tool from blocking I/O inside an async node. The latter stalls every coroutine on that event loop:

```python
# ❌ Direct sync I/O inside a coroutine blocks the event loop.
async def lookup_node(state):
    response = httpx.get(url)  # no executor boundary here
    return {"result": response.text}
```

✅ Correct — async all the way down:

```python
# ✅ astream/ainvoke yield control; sync I/O is offloaded explicitly.
@tool
async def lookup(q: str) -> str:
    async with httpx.AsyncClient() as c:
        return (await c.get(url)).text

# For unavoidable sync code, push it off the loop:
import anyio
result = await anyio.to_thread.run_sync(legacy_blocking_fn, arg)
```

**Error propagation** — a LangGraph node exception must become an A2A `failed` Task, not a hang:

```python
try:
    async for item in self.agent.stream(query, context.context_id):
        ...
except Exception as e:
    logger.exception("graph failed")
    # The caller receives a stable generic error; details remain in logs.
    raise ServerError(error=InternalError()) from e
```

The client observes a failed Task or the binding's internal-error response without receiving `str(e)`, which may contain prompts, URLs, or credentials.

> **Key insight**: Every code path through `execute` must end the Task in a terminal or interrupted state — `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, or `TASK_STATE_INPUT_REQUIRED`. A Task left in `TASK_STATE_WORKING` is invisible breakage: no error, no result, just a client waiting.

---

**Next**: [Part 2: Google ADK](02_google_adk.md)
