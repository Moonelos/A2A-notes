# CrewAI, Semantic Kernel, LlamaIndex & AG2 — A2A Integration Patterns

> **Who this is for**: Engineers building agents with CrewAI, Microsoft Semantic Kernel / Agent Framework, LlamaIndex, or AG2/AutoGen who want to expose them over A2A or consume remote A2A agents. Before reading this, understand the A2A server lifecycle: **[Building a Server](../03_python/02_building_a_server.md)**.

This file covers the *rest* of the agent-framework ecosystem. The mechanics of `AgentExecutor`, `RequestContext`, and `EventQueue` are assumed — see the prerequisite. Here we focus on what each framework gives you for free, what you still write by hand, and the integration state as of **May 2026**.

> **Rule**: A2A is the wire protocol; the framework is an implementation detail behind it. Any framework agent can be A2A-exposed because A2A only cares about `Message` in and `Task`/artifacts out.

---

## 1. The general adapter pattern

Every "framework → A2A" integration is the same shape. You write (or the framework gives you) an `AgentExecutor` that sits between the A2A transport and the framework's native agent loop. It does three things on the **server** side, and the mirror image on the **client** side.

```
                          A2A SERVER SIDE (expose a framework agent)
        ┌────────────────────────────────────────────────────────────────────┐
        │                                                                    │
  A2A   │   ┌──────────────┐   (1) translate    ┌───────────────────────┐    │
 Client ├──▶│ A2A transport │──── inbound ──────▶│  AgentExecutor.execute │   │
  Msg   │   │ (Starlette /  │   A2A Message      │                        │   │
        │   │  DefaultReq-  │   → framework      │  (2) run framework     │   │
        │   │  Handler)     │     input type     │      agent / crew /    │   │
        │   │               │                    │      workflow          │   │
        │   │               │◀─── A2A Task ──────│                        │   │
        │   │               │   events /         │  (3) emit result as    │   │
        │   │               │   artifacts        │      Task events via   │   │
        │   └──────────────┘   via EventQueue    │      event_queue       │   │
        │                                        └───────────┬───────────┘   │
        │                                                    │               │
        │                                          ┌─────────▼──────────┐    │
        │                                          │  Framework agent   │    │
        │                                          │  (Crew / SK agent /│    │
        │                                          │   Workflow / AG2)  │    │
        │                                          └────────────────────┘    │
        └────────────────────────────────────────────────────────────────────┘

                          A2A CLIENT SIDE (consume a remote A2A agent)
        ┌────────────────────────────────────────────────────────────────────┐
        │   Framework's native "tool" / "agent" abstraction                  │
        │   wraps an a2a-sdk ClientFactory + send_message call.              │
        │   The remote agent looks local to the framework's orchestrator.    │
        └────────────────────────────────────────────────────────────────────┘
```

**Server side — three responsibilities of the executor:**

1. **Translate inbound.** Pull the user input out of `RequestContext` (`context.get_user_input()` for plain text, or walk `context.message.parts` for files/data) and shape it into whatever the framework expects — a `Crew` kickoff input dict, an SK `ChatMessageContent`, a LlamaIndex `StartEvent`, an AG2 chat message.
2. **Run the framework agent.** Call the framework's run/kickoff/invoke. This is usually where the sync-vs-async mismatch bites (see §6).
3. **Emit the result.** Wrap the output in A2A `Task` events and artifacts and push them through `event_queue` — usually via `TaskUpdater.add_artifact(...)` plus `TaskUpdater.complete()` for one-shot, or explicit `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent` for streaming.

**Client side** is the mirror: you wrap an `a2a-sdk` client call inside the framework's native extension point — a CrewAI `tool`, an SK plugin `kernel_function`, a LlamaIndex `FunctionTool`, an AG2 `A2aRemoteAgent`. The framework's planner then treats the remote agent as if it were local.

> **Key insight**: There is no magic. "Native A2A support" in a framework just means *they* wrote the adapter for you. Where they haven't, you write the ~60-line `AgentExecutor` from the prerequisite file.

---

## 2. CrewAI

CrewAI is the most common framework paired with A2A, and as of the **0.x → A2A-native** releases it ships first-class A2A support: you pass an `a2a` config object to a CrewAI `Agent` and it becomes A2A-aware in either direction. The classic [`a2a-samples` CrewAI example](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/crewai) (an image-generation `Crew`) predates that and still uses a **hand-written** `AgentExecutor` — useful to study because it shows exactly what the native config now automates.

### 2a. Exposing a Crew over A2A

The sample's pattern: wrap the `Crew` in an executor and run it as a standard A2A Starlette app.

```python
# agent_executor.py — hand-written executor (mirrors the a2a-samples CrewAI example)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.helpers import new_task_from_user_message
from a2a.server.tasks import TaskUpdater
from a2a.types import InvalidParamsError, Part, UnsupportedOperationError

from crewai import Agent, Crew, Task
from crewai.process import Process


class ResearchCrewExecutor(AgentExecutor):
    """Exposes a CrewAI Crew as a single A2A agent."""

    def __init__(self) -> None:
        researcher = Agent(
            role="Research Analyst",
            goal="Answer the user's question with sourced facts",
            backstory="Senior analyst, terse and precise.",
        )
        self._researcher = researcher

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # (1) translate inbound A2A Message → Crew kickoff input
        query = context.get_user_input()
        if not query:
            raise InvalidParamsError()

        crew_task = Task(
            description=f"Research and answer: {query}",
            expected_output="A concise, sourced answer.",
            agent=self._researcher,
        )
        crew = Crew(
            agents=[self._researcher],
            tasks=[crew_task],
            process=Process.sequential,
        )

        # (2) run the framework agent. Crew.kickoff() is SYNCHRONOUS — see §6.
        #     kickoff_async() exists; use it to avoid blocking the event loop.
        result = await crew.kickoff_async(inputs={"query": query})

        # (3) emit result as an A2A Task with a text artifact
        a2a_task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(a2a_task)
        updater = TaskUpdater(event_queue, a2a_task.id, a2a_task.context_id)
        await updater.add_artifact(
            [Part(text=str(result))],
            name=f"research_{a2a_task.id}",
        )
        await updater.complete()

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise UnsupportedOperationError()
```

Wire it into a server exactly as in the prerequisite (`DefaultRequestHandler` + the `create_jsonrpc_routes` / `create_agent_card_routes` factories on a Starlette app); the only CrewAI-specific part is the executor body.

✅ The native shortcut: instead of the executor above, recent CrewAI lets you pass `A2AServerConfig` directly to an `Agent` (`Agent(..., a2a=A2AServerConfig(name="Research Analyst", protocol_version="1.0"))`) and CrewAI builds the A2A surface for you. Use the hand-written executor when you need a *multi-agent Crew* exposed as one A2A endpoint, since the native config attaches to a single `Agent`.

⚠️ CrewAI's native A2A surface is current, but its server config still exposes compatibility-oriented field names such as `preferred_transport`, `additional_interfaces`, and a documented `protocol_version` default of `"0.3"`. For A2A v1.0 teaching material, set the version explicitly and fetch the generated card before publishing examples.

### 2b. Using a remote A2A agent as a CrewAI tool

Two routes. The **native** route — pass `A2AClientConfig` to a CrewAI `Agent` so the remote agent becomes delegable:

```python
from crewai import Agent
from crewai.a2a import A2AClientConfig          # native A2A client config
from crewai.a2a.auth import BearerTokenAuth     # also: APIKeyAuth, OAuth2ClientCredentials

planner = Agent(
    role="Trip Planner",
    goal="Plan a trip, delegating currency questions to the remote FX agent",
    backstory="Coordinates specialist agents.",
    a2a=A2AClientConfig(
        # points at the remote agent's discovery document
        endpoint="https://fx-agent.internal/.well-known/agent-card.json",
        auth=BearerTokenAuth(token="..."),
    ),
)
```

The **manual** route — wrap an `a2a-sdk` call in a `@tool`, useful when you want fine control or are on an older CrewAI:

```python
from crewai.tools import tool
import httpx
from uuid import uuid4

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_stream_response_text
from a2a.types import Message, Part, Role, SendMessageRequest

@tool("RemoteFXAgent")
async def remote_fx_agent(question: str) -> str:
    """Ask the remote currency-exchange A2A agent a question."""
    async with httpx.AsyncClient() as http:
        resolver = A2ACardResolver(
            httpx_client=http,
            base_url="https://fx-agent.internal",
        )
        card = await resolver.get_agent_card()
        factory = ClientFactory(ClientConfig(httpx_client=http))
        client = factory.create(card)
        request = SendMessageRequest(
            message=Message(
                role=Role.ROLE_USER,
                parts=[Part(text=question)],
                message_id=str(uuid4()),
            )
        )
        chunks = []
        async for event in client.send_message(request):
            text = get_stream_response_text(event, delimiter="")
            if text:
                chunks.append(text)
        return "".join(chunks).strip()
```

> **Rule**: `crewai.a2a.config.A2AConfig` is **deprecated** (removed in CrewAI v2.0.0). Use the split `A2AClientConfig` / `A2AServerConfig` classes. On the client side, the discovery URL parameter is `endpoint`, not `url`.

⚠️ Confirm class names against *your* installed CrewAI version. The `crewai.a2a` namespace is new and has moved fast through the 1.x line.

---

## 3. Semantic Kernel / Microsoft Agent Framework

Two distinct things share the "Microsoft" label here — keep them separate:

- **Semantic Kernel (SK)** — the older orchestration SDK. As of May 2026 SK has **no built-in `A2AAgent` class or A2A abstraction**. The Microsoft devblog integration guide and the [`a2a-samples` semantickernel example](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/semantickernel) both wire A2A by **hand-writing an `AgentExecutor`** around a SK `ChatCompletionAgent`. Treat any `A2AAgent` import from `semantic_kernel.agents` as not real — it does not exist.
- **Microsoft Agent Framework (MAF) 1.0** — reached version 1.0 in April 2026, unifying SK and AutoGen concepts into one SDK. The .NET A2A provider wraps an A2A endpoint as a standard `AIAgent` with `RunAsync` / `RunStreamingAsync`; the Microsoft docs still mark the A2A NuGet package as `--prerelease` and say Python A2A-agent docs are coming. Treat MAF as the Microsoft path for A2A, but do not assume the older SK package has the same abstraction.

### Exposing a SK agent over A2A (the sample pattern)

The sample wraps a SK `ChatCompletionAgent` and maps SK streaming onto A2A status updates.

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from semantic_kernel.agents import ChatCompletionAgent, ChatHistoryAgentThread
from semantic_kernel.connectors.ai.open_ai import OpenAIChatCompletion

class SemanticKernelExecutor(AgentExecutor):
    def __init__(self) -> None:
        self._agent = ChatCompletionAgent(
            service=OpenAIChatCompletion(),
            name="TravelManager",
            instructions="Plan trips. Ask for clarification when budget is missing.",
        )

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        thread = ChatHistoryAgentThread()      # SK conversational memory
        # SK is async-native: invoke_stream yields StreamingChatMessageContent.
        async for response in self._agent.invoke_stream(
            messages=context.get_user_input(), thread=thread
        ):
            # map each SK streaming chunk → an A2A TaskStatusUpdateEvent
            await event_queue.enqueue_event(_status_update(context, str(response)))
        # ... emit a final artifact and TASK_STATE_COMPLETED status (omitted)
```

✅ SK is **async-native** (`invoke`, `invoke_stream` are coroutines), so it drops cleanly into `AgentExecutor.execute` with no thread-pool wrapping.

For consuming a remote A2A agent from SK, the sample/devblog approach builds a `KernelFunction` from the remote Agent Card and bundles it as a plugin — there is no shipped helper class; you write the factory yourself.

---

## 4. LlamaIndex

LlamaIndex exposes agents and **Workflows** over A2A via a hand-written executor. The reference is the [`a2a-samples` LlamaIndex example](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/llama_index_file_chat) — a file-chat **Workflow** (`ParseAndChat`) with multi-turn memory, file parsing, streaming, and JWK-authenticated push notifications. There is no official `a2a` package from LlamaIndex; the integration lives as a sample, so treat it as a pattern, not a library.

### Exposing a LlamaIndex Workflow over A2A

The pattern: feed the inbound A2A message in as a Workflow `StartEvent`, and translate each emitted Workflow event into an A2A event.

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from llama_index.core.workflow import Workflow

class LlamaIndexWorkflowExecutor(AgentExecutor):
    def __init__(self, workflow: Workflow) -> None:
        self._workflow = workflow

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        # (1) inbound A2A Message → Workflow input
        handler = self._workflow.run(msg=context.get_user_input())

        # (2)+(3) stream Workflow events → A2A status updates
        async for event in handler.stream_events():
            # the sample emits a LogEvent per step; map it to a TaskStatusUpdateEvent
            await event_queue.enqueue_event(_status_update(context, str(event)))

        result = await handler                # final Workflow result
        await event_queue.enqueue_event(_completed(context, result))
```

LlamaIndex `Workflow` event streaming maps almost 1:1 onto A2A's incremental `Task` events — each `LogEvent`/custom event becomes a `TaskStatusUpdateEvent`, and the final result becomes an artifact. To consume a remote A2A agent inside LlamaIndex, wrap the `a2a-sdk` client call in a `FunctionTool` and hand it to an `AgentWorkflow` / `FunctionAgent`.

⚠️ Workflows are async-native, but `Workflow.run()` returns a *handler* — you must `await` it (or stream it) inside `execute`; forgetting to await silently drops the result.

---

## 5. AG2 / AutoGen

AG2 (formerly AutoGen; PyPI package `ag2`, import alias `autogen`) has the most mature A2A story of the four — **native A2A support since AG2 v0.10** (October 2025) in the `autogen.a2a` module:

- **`A2aAgentServer`** — wraps an AG2 `ConversableAgent` into an A2A server. `A2aAgentServer.build()` returns a Starlette ASGI app you run with `uvicorn`.
- **`A2aRemoteAgent`** — an `a2a-sdk`-based client that *is* a `ConversableAgent`. The remote A2A agent looks like any other AG2 agent to the orchestrator. **Async-only** — use `a_initiate_chat`, not `initiate_chat`.

Both sides are first-class; you rarely write a raw `AgentExecutor` for AG2. Current AG2 docs also show some custom-card examples through `a2a.compat.v0_3.types`, so inspect the generated card if you need strict v1.0 fields. See the [`a2a-samples` ag2 example](https://github.com/a2aproject/a2a-samples/tree/main/samples/python/agents/ag2) (a mypy code-reviewer agent).

### Expose an AG2 agent over A2A

```python
from autogen import ConversableAgent, LLMConfig
from autogen.a2a import A2aAgentServer

reviewer = ConversableAgent(
    name="ReviewerAgent",
    system_message="Strict Python reviewer. Validate typing with mypy.",
    llm_config=LLMConfig({"model": "gpt-4o-mini", "api_key": "..."}),
    human_input_mode="NEVER",
)

app = A2aAgentServer(reviewer).build()   # Starlette ASGI app
# uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Consume a remote A2A agent in AG2

```python
import asyncio
from autogen import ConversableAgent, LLMConfig
from autogen.a2a import A2aRemoteAgent

codegen = ConversableAgent(name="CodeGenAgent",
                           llm_config=LLMConfig({"model": "gpt-4o-mini", "api_key": "..."}))

# the remote A2A agent behaves like a local ConversableAgent
reviewer = A2aRemoteAgent(url="http://localhost:8000", name="ReviewerAgent")

async def main() -> None:
    # A2aRemoteAgent is async-only → a_initiate_chat
    await reviewer.a_initiate_chat(codegen, message="Generate a USD→EUR converter script.")

asyncio.run(main())
```

> **Key insight**: AG2 is the cleanest demonstration of A2A as a "lingua franca" — the agent-as-a-service pattern means the remote agent's tools, environment, and model are fully encapsulated behind the A2A endpoint.

---

## 6. Comparison & gotchas

### Integration state (May 2026)

| Framework | A2A server support | A2A client support | Notable example |
|---|---|---|---|
| **CrewAI** | Native — `A2AServerConfig` on `Agent`; hand-written `AgentExecutor` for multi-agent Crews | Native — `A2AClientConfig(endpoint=...)` on `Agent`; or wrap client in `@tool` | `a2a-samples` image-generation Crew |
| **Semantic Kernel** | Hand-written `AgentExecutor` only — **no SK A2A class** | Hand-written `KernelFunction`/plugin factory | `a2a-samples` semantickernel travel agent |
| **Microsoft Agent Framework 1.0** | .NET hosting/agent-provider docs cover A2A; Python coverage is still catching up | First-class .NET `A2AAgent` wrapper over remote endpoints | Microsoft Agent Framework A2A docs |
| **LlamaIndex** | Hand-written `AgentExecutor` around a `Workflow` — sample, no official package | Wrap client in a `FunctionTool` | `a2a-samples` LlamaIndex file-chat Workflow |
| **AG2 / AutoGen** | Native — `autogen.a2a.A2aAgentServer` (v0.10+) | Native — `autogen.a2a.A2aRemoteAgent` (async-only) | `a2a-samples` ag2 mypy reviewer |

> **Rule**: "Native" ≠ "stable". AG2's `autogen.a2a` and CrewAI's `crewai.a2a` are recent and have moved fast. SK has *no* A2A abstraction at all — only a sample pattern. Verify imports against your installed version; do not trust class names from blog posts.

### Gotchas

⚠️ **Framework version skew with `a2a-sdk`.** Each sample pins a specific `a2a-sdk` version in `pyproject.toml`. A native integration (AG2's `autogen.a2a`, CrewAI's `crewai.a2a`) depends on a *range* of `a2a-sdk` — bumping `a2a-sdk` independently can break `ClientFactory`/`AgentExecutor` signatures. Pin both together and upgrade them as a pair.

⚠️ **Sync vs async mismatch.** `AgentExecutor.execute` is a coroutine on a shared event loop. CrewAI's `Crew.kickoff()` is **synchronous and blocking** — calling it directly stalls every concurrent A2A request. Use `Crew.kickoff_async()`, or offload with `await asyncio.to_thread(crew.kickoff, ...)`. SK, LlamaIndex Workflows, and AG2 are async-native and drop in cleanly — but AG2's `A2aRemoteAgent` is *async-only*; `initiate_chat` (sync) will not work.

⚠️ **Mapping framework streaming onto A2A events.** Frameworks emit their own event types — LlamaIndex `Workflow` events, SK `StreamingChatMessageContent`, CrewAI step callbacks, AG2 messages. A2A expects `TaskStatusUpdateEvent` (progress) and `TaskArtifactUpdateEvent` (incremental output), terminated by `TASK_STATE_COMPLETED` or `TASK_STATE_FAILED`. You must translate each. ❌ Do not forward raw framework chunks as text and forget the terminal event — the A2A client will hang waiting for a final state. ✅ Always emit exactly one terminal status, and set `AgentCapabilities(streaming=...)` on the Agent Card to match what your executor actually does (the CrewAI image sample sets `streaming=False` precisely because it returns one artifact).

💡 **When in doubt, hand-write the executor.** Native configs attach to a single agent and assume a simple request/response. For multi-agent Crews, branching Workflows, or custom artifact types, the explicit `AgentExecutor` from [Building a Server](../03_python/02_building_a_server.md) is more predictable than fighting a framework's abstraction.

---

**Next**: [Part 1: Authentication](../05_production/01_authentication.md)
