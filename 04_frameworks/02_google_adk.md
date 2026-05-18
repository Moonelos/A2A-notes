# A2A with the Google Agent Development Kit (ADK)

> **Who this is for**: Engineers using or evaluating Google ADK who want to expose ADK agents over A2A and consume remote A2A agents. Before reading this, understand how an A2A server is structured: **[Building a Server](../03_python/02_building_a_server.md)**.

ADK (`google-adk`) ships the deepest *native* A2A integration of any agent framework: a one-call `to_a2a()` wrapper that auto-generates an agent card, and a `RemoteA2aAgent` class that drops a remote agent into a multi-agent tree as if it were local. This file shows both directions and the `Event` ↔ `Task` mapping that makes it work.

---

## 1. ADK orientation in 60 seconds

ADK is Google's Python framework for building LLM agents. The pieces you need before touching A2A:

```python
from google.adk.agents import Agent          # alias of LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

def check_prime(number: int) -> dict:
    """Return whether `number` is prime."""
    if number < 2:
        return {"number": number, "is_prime": False}
    for d in range(2, int(number ** 0.5) + 1):
        if number % d == 0:
            return {"number": number, "is_prime": False}
    return {"number": number, "is_prime": True}

# An Agent = model + instruction + tools. `Agent` is a re-export of `LlmAgent`.
root_agent = Agent(
    model="gemini-flash-latest",
    name="prime_agent",
    description="Checks whether numbers are prime.",
    instruction="Use the check_prime tool to answer prime-number questions.",
    tools=[check_prime],
)
```

Running it locally goes through a `Runner`, which streams `Event` objects — the fundamental unit of ADK execution:

```python
runner = Runner(
    agent=root_agent,
    app_name="prime_app",
    session_service=InMemorySessionService(),
)

async def ask(user_id: str, session_id: str, text: str):
    message = types.Content(role="user", parts=[types.Part(text=text)])
    async for event in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=message
    ):
        # Events carry partial text, tool calls, tool results, state deltas, errors.
        if event.is_final_response():
            print(event.content.parts[0].text)
```

> **Key insight**: An ADK `Event` is a superset of a chat message — it can be a partial token, a `function_call`, a `function_response`, a `state_delta`, or an error. A2A's job is to project that stream onto the protocol's `Message` / `Task` / `TaskStatusUpdateEvent` types. ADK does that projection for you.

| ADK concept | Role | A2A counterpart |
|-------------|------|-----------------|
| `Agent` / `LlmAgent` | The agent definition | The thing behind an agent card |
| Tool (plain function, `FunctionTool`) | Capability | Surfaces as a skill in the card |
| `Runner` | Drives one invocation, yields `Event`s | Server-side execution loop |
| Session (`SessionService`) | Conversation state + event history | A2A `contextId` |
| `Event` | One step of execution | `Message` / `Task` / status update |

---

## 2. Exposing an ADK agent with `to_a2a()`

The fast path. `to_a2a()` wraps an existing ADK agent and returns a Starlette/uvicorn-compatible **ASGI app** that speaks A2A — no `AgentExecutor` boilerplate.

```python
# agent.py
from google.adk.agents import Agent
from google.adk.a2a.utils.agent_to_a2a import to_a2a

root_agent = Agent(
    model="gemini-flash-latest",
    name="check_prime_agent",
    description="Checks whether numbers are prime.",
    instruction="Use the check_prime tool to answer prime-number questions.",
    tools=[check_prime],
)

# Returns an ASGI app. The agent card is auto-generated in-memory at startup.
a2a_app = to_a2a(root_agent, port=8001)
```

Serve it with uvicorn — point at the `module:attribute` holding the app:

```bash
uvicorn agent:a2a_app --host localhost --port 8001
```

ADK introspects the agent (name, description, tools) and publishes a card at the well-known path:

```
http://localhost:8001/.well-known/agent-card.json
```

The auto-generated v1.0 card includes `supportedInterfaces`, `capabilities`, `skills`, `defaultInputModes`/`defaultOutputModes` (`text/plain`), and `version`.

⚠️ The `port` argument to `to_a2a()` only sets the endpoint URL advertised in the generated card's first `supportedInterfaces` entry. It does *not* bind a socket — uvicorn does that. If `to_a2a(..., port=8001)` disagrees with `uvicorn --port 9000`, the card advertises a URL clients cannot reach.

> **Rule**: Keep the `port` passed to `to_a2a()` identical to the port uvicorn binds, and make the advertised `supportedInterfaces[*].url` reachable from where clients actually run (not `localhost` if they are remote).

---

## 3. Exposing with an explicit agent card

`to_a2a()` accepts an `AgentCard` object or a path to a JSON file when you need control over skills, auth, or input/output modes:

```python
from a2a.types import AgentCard, AgentCapabilities, AgentInterface, AgentSkill
from google.adk.a2a.utils.agent_to_a2a import to_a2a

my_card = AgentCard(
    name="check_prime_agent",
    description="Checks whether integers are prime.",
    version="1.2.0",
    capabilities=AgentCapabilities(streaming=True),
    supported_interfaces=[
        AgentInterface(
            protocol_binding="JSONRPC",
            protocol_version="1.0",
            url="https://prime.internal.example.com",  # address clients will dial
        )
    ],
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[
        AgentSkill(
            id="check_prime",
            name="Check prime",
            description="Determine whether a number is prime.",
            tags=["math"],
            examples=["Is 7919 prime?"],
        ),
    ],
)

a2a_app = to_a2a(root_agent, port=8001, agent_card=my_card)
# Or load from disk: to_a2a(root_agent, port=8001, agent_card="/path/agent-card.json")
```

### The `adk api_server --a2a` route

For hosting **multiple agents from one parent folder**, use the ADK CLI instead of hand-writing uvicorn entrypoints. Each agent folder must contain its own `agent.json` card:

```bash
adk api_server --a2a --port 8001 ./agents_root
# add --log_level debug while wiring things up
```

This serves every sub-agent folder under `./agents_root`, exposing each at `/.well-known/agent-card.json` relative to its mount path (e.g. `/a2a/check_prime_agent/.well-known/agent-card.json`).

### The fully explicit route: `A2aAgentExecutor`

`to_a2a()` is itself a thin wrapper over the A2A SDK's request handler plus ADK's `A2aAgentExecutor`. Drop to it when you need converter or interceptor hooks:

```python
from google.adk.a2a.executor.a2a_agent_executor import A2aAgentExecutor

executor = A2aAgentExecutor(
    runner=runner,            # your configured ADK Runner
    # custom hooks: a2a_part_converter, gen_ai_part_converter, request_converter
)
```

You then hand `executor` to the standard `a2a-sdk` `DefaultRequestHandler` and mount the `create_jsonrpc_routes` / `create_agent_card_routes` factories on a Starlette app — exactly the server shape from [Building a Server](../03_python/02_building_a_server.md). ✅ Use the explicit route only when you genuinely need a custom converter; otherwise `to_a2a()` is less to maintain.

---

## 4. Consuming a remote A2A agent with `RemoteA2aAgent`

`RemoteA2aAgent` is an ADK `Agent` subclass that, instead of calling a model, forwards the turn to a remote A2A server. It is a **drop-in sub-agent**.

```python
from google.adk.agents.remote_a2a_agent import (
    RemoteA2aAgent,
    AGENT_CARD_WELL_KNOWN_PATH,   # = "/.well-known/agent-card.json"
)

prime_agent = RemoteA2aAgent(
    name="prime_agent",
    description="Agent that checks whether numbers are prime.",
    agent_card=(
        f"http://localhost:8001/a2a/check_prime_agent{AGENT_CARD_WELL_KNOWN_PATH}"
    ),
    use_legacy=False,   # opt into the current ADK<->A2A integration
)
```

| Parameter | Purpose |
|-----------|---------|
| `name` | Local identifier; the LLM uses it to decide delegation |
| `description` | Fed to the parent agent's router — make it precise |
| `agent_card` | URL of the remote card (or a card object / dict) |
| `use_legacy` | `False` for the current integration; `True` is the old path |
| `config` | Optional `A2aRemoteAgentConfig` for converters/interceptors |

⚠️ `description` is not cosmetic. The **parent** agent's LLM routes to sub-agents using their descriptions. A vague description ("does math stuff") causes mis-delegation. Be specific about inputs and outputs.

> **Rule**: The `agent_card` URL must resolve to a live card *at construction-or-first-call time*. ADK fetches it lazily; a 404 there surfaces as a runtime failure deep inside an invocation, not at import.

### Auth and request shaping with `A2aRemoteAgentConfig`

```python
from google.adk.a2a.agent.config import A2aRemoteAgentConfig

class BearerAuthInterceptor:
    def __init__(self, token: str):
        self._token = token

    async def before_request(self, request):
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    async def after_request(self, response):
        return response

prime_agent = RemoteA2aAgent(
    name="prime_agent",
    description="Agent that checks whether numbers are prime.",
    agent_card=f"http://localhost:8001/a2a/check_prime_agent{AGENT_CARD_WELL_KNOWN_PATH}",
    use_legacy=False,
    config=A2aRemoteAgentConfig(
        request_interceptors=[BearerAuthInterceptor(token=os.environ["PRIME_TOKEN"])],
        # also: a2a_message_converter, a2a_task_converter,
        #       a2a_status_update_converter, a2a_artifact_update_converter
    ),
)
```

❌ Do not assume `RemoteA2aAgent` reads ambient credentials. If the remote card advertises a `securitySchemes` entry, you must attach the credential yourself via a `request_interceptors` hook — there is no implicit token pickup.

---

## 5. Multi-agent example: root delegates to a remote agent

A local root agent with two children — one local (`roll_agent`), one remote (`prime_agent`). The root's LLM picks which to invoke.

```python
# root/agent.py
import os
from google.adk.agents import Agent
from google.adk.agents.remote_a2a_agent import (
    RemoteA2aAgent,
    AGENT_CARD_WELL_KNOWN_PATH,
)

def roll_die(sides: int) -> int:
    """Roll a die with `sides` faces."""
    import random
    return random.randint(1, sides)

roll_agent = Agent(
    model="gemini-flash-latest",
    name="roll_agent",
    description="Rolls dice with a configurable number of sides.",
    instruction="Use roll_die to satisfy dice-rolling requests.",
    tools=[roll_die],
)

# Remote agent exposed in section 2/3, consumed here as a sub-agent.
prime_agent = RemoteA2aAgent(
    name="prime_agent",
    description="Checks whether a given integer is prime.",
    agent_card=f"http://localhost:8001/a2a/check_prime_agent{AGENT_CARD_WELL_KNOWN_PATH}",
    use_legacy=False,
)

root_agent = Agent(
    model="gemini-flash-latest",
    name="root_agent",
    instruction=(
        "You coordinate two specialists. Delegate dice rolls to roll_agent "
        "and prime-number checks to prime_agent. Do not answer those yourself."
    ),
    sub_agents=[roll_agent, prime_agent],   # RemoteA2aAgent sits alongside local agents
)
```

Run the consuming side with the ADK dev UI (point it at the folder containing `root/`):

```bash
# 1. Start the remote agent
adk api_server --a2a --port 8001 ./agents_root

# 2. Start the root agent that delegates to it
adk web ./
```

Flow when a user asks *"Is 7919 prime?"*:

```
user ──> root_agent (LLM router)
              │  picks prime_agent based on its description
              ▼
        RemoteA2aAgent "prime_agent"
              │  A2A SendMessage over HTTP
              ▼
   remote A2A server (to_a2a-wrapped check_prime_agent)
              │  runs ADK Runner, executes check_prime tool
              ▼
        A2A Task (TASK_STATE_COMPLETED) ──> events ──> root_agent ──> user
```

The root agent never knows `prime_agent` lives on another process. ✅ This is the payoff of native integration: a remote agent and a local agent are both just entries in `sub_agents`.

---

## 6. Mapping ADK `Event`s and long-running tools onto A2A `Task`s

This is the part that makes the abstraction leak-proof — and the part to understand before debugging.

**Server side (`to_a2a` / `A2aAgentExecutor`)** consumes the `Runner.run_async()` event stream and converts:

| ADK `Event` | A2A projection |
|-------------|----------------|
| Partial text event | `Message`/artifact chunks streamed via `SendStreamingMessage` |
| `function_call` / `function_response` | Internal to the Task; not separate A2A messages |
| Final response event | `Task` transitions to `TASK_STATE_COMPLETED`, text in artifact/message |
| Error event | `Task` transitions to `TASK_STATE_FAILED` with an error |
| Long-running tool pending | `Task` transitions to `TASK_STATE_INPUT_REQUIRED` |

**Client side (`RemoteA2aAgent`)** does the inverse: incoming A2A `Message` / `Task` / `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent` are converted back into ADK `Event`s and yielded into the parent agent's stream (this is what the `*_converter` config hooks override).

### Long-running tools and `input-required`

When the remote agent calls a `LongRunningFunctionTool` (ADK's human-in-the-loop / async-job primitive), the `Runner` *pauses* the invocation. ADK projects that pause onto the A2A **`input-required`** task state:

```python
from google.adk.tools import LongRunningFunctionTool

def request_approval(amount: float) -> dict:
    """Kick off an out-of-band approval. Returns a ticket; resolves later."""
    ticket = create_approval_ticket(amount)
    # Returning without a final answer => Runner pauses the invocation.
    return {"status": "pending", "ticket_id": ticket.id}

approval_tool = LongRunningFunctionTool(func=request_approval)
```

```
remote agent runs ──> LongRunningFunctionTool returns "pending"
        │
        ▼
   A2A Task state = TASK_STATE_INPUT_REQUIRED   (Task stays open, not failed)
        │
   client (RemoteA2aAgent) surfaces it to the parent agent / user
        │
   parent sends follow-up message on the SAME contextId/taskId
        ▼
   Runner resumes the paused invocation with a function_response
```

> **Key insight**: `input-required` is *not* an error. The A2A `Task` stays alive; the same `taskId` / `contextId` must be reused for the follow-up message, or the remote agent starts a fresh, stateless invocation and loses the pending tool call.

⚠️ ADK long-running tools rely on `EventActions.state_delta` to accumulate state across pauses. If a follow-up arrives on a new context, the delta history is gone and the resumed tool sees an empty session. Always thread `contextId` through the round-trip.

---

## 7. Failure modes and gotchas

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `RemoteA2aAgent` fails mid-invocation, not at import | Card fetched lazily; URL 404s | Curl `…/.well-known/agent-card.json` before wiring it in |
| Client dials `localhost` but agent is remote | `to_a2a(port=…)` / card `url` set to `localhost` | Set the card `url` to a routable host (sec. 2–3) |
| `404` for the card | `agent.json` missing in an `adk api_server --a2a` folder | Add an `agent.json` per agent folder |
| Card path mismatch | Mixing `/agent.json` and `/agent-card.json` | Use the `AGENT_CARD_WELL_KNOWN_PATH` constant, don't hardcode |
| `401` / `403` from the remote agent | No credential attached | Add a `request_interceptors` hook in `A2aRemoteAgentConfig` (sec. 4) |
| `ImportError` on `google.adk.a2a.*` or `a2a.types` | Version skew: `google-adk` vs `a2a-sdk` | Pin both; install `google-adk[a2a]` extra |
| Deserialization / converter errors | A2A protocol version skew between server and client | Match `supportedInterfaces[*].protocolVersion`; upgrade the lagging side |
| Remote turn ends in `failed` unexpectedly | Long-running tool treated as error | It should be `input-required`; check the tool returns a non-final dict |

### Version skew — the most common production break

`to_a2a`, `RemoteA2aAgent`, and the converter classes live in `google.adk.a2a.*` but depend on the separately-versioned `a2a-sdk` (`a2a.types`, request handlers). ADK releases sometimes require a newer `a2a-sdk` than the one already installed.

```bash
# Install the A2A extra so the matching a2a-sdk version is resolved together.
pip install "google-adk[a2a]"
```

> **Rule**: Pin `google-adk` and `a2a-sdk` together in your lockfile, and upgrade them as a pair. A mismatched pair fails as `ImportError` at best and silent converter misbehavior at worst.

❌ Don't `pip install google-adk a2a-sdk` with unpinned versions across server and client repos — independent upgrades drift the protocol version and break the wire format.

✅ Verify the contract end-to-end after any upgrade: fetch the card, send one `SendMessage`, and confirm a clean `TASK_STATE_COMPLETED` task before trusting the multi-agent tree.

---

**Next**: [Part 3: CrewAI & Others](03_crewai_and_others.md)
