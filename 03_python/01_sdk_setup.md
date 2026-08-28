# Setting Up the `a2a-sdk` Python SDK

> **Who this is for**: Python engineers about to build an A2A server or client. You're comfortable with `async`/`await`, virtual environments, and `pip`. By the end you'll have a verified install, a clean project skeleton, and a mental map of the SDK's packages.

Before reading this, understand how A2A messages move over the wire: **[Transport & RPC](../02_protocol/02_transport_and_rpc.md)**.

## Quick start: prove the pinned SDK works

Install the current repository baseline into an active Python 3.10+ environment:

```bash
python -m pip install "a2a-sdk==1.1.2"
python -c "from importlib.metadata import version; from a2a.types import AgentCard; print(f'a2a-sdk {version(\"a2a-sdk\")} install OK')"
```

Expected output:

```text
a2a-sdk 1.1.2 install OK
```

If the import fails, `python -m pip --version` and `python --version` usually reveal that `pip` installed into a different environment. If the version differs, an existing lockfile or environment constraint won; resolve that before copying SDK examples.

> **Production:** the base package proves the Protocol Buffers model imports. Add the specific server, transport, database, signing, encryption, or telemetry extra only when the next note uses it.

---

## 1. What `a2a-sdk` Is

`a2a-sdk` is the **official Python SDK** for the Agent2Agent (A2A) protocol, maintained at [`github.com/a2aproject/a2a-python`](https://github.com/a2aproject/a2a-python). It is async-first, requires **Python 3.10+** (tested through 3.14), and ships the protocol model as generated **Protocol Buffers** classes. These classes enforce the wire schema and field-presence rules; they are not ordinary Python data classes with arbitrary attributes.

The checked baseline is **`1.1.2`** (released 2026-07-20). It implements wire protocol **1.0** and includes compatibility support for older 0.3 peers. Patch releases of the specification do not change the negotiated `Major.Minor` wire value.

The SDK gives you three layers:

```
┌─────────────────────────────────────────────────────────┐
│  a2a.types        Protocol data model (AgentCard, Task,  │
│                   Message, Part, TaskState, ...)         │
├─────────────────────────────────────────────────────────┤
│  a2a.client       Talk to remote A2A agents              │
│  a2a.server       Host your own A2A agent                │
├─────────────────────────────────────────────────────────┤
│  a2a.utils        Constants, errors, telemetry, signing  │
│  a2a.helpers      Convenience builders (new_text_message)│
└─────────────────────────────────────────────────────────┘
```

> **Key insight**: The base install is deliberately thin. HTTP server bindings, gRPC, database task stores, signing, and encryption are all **optional extras** — you pull in only the dependency weight you actually need.

---

## 2. Installation

The base package is enough to import `a2a.types` and use the in-memory client/server primitives:

```bash
pip install a2a-sdk
```

Most real agents need at least the HTTP server bindings. Install extras with the bracket syntax:

```bash
# HTTP server (Starlette / FastAPI route factories)
pip install "a2a-sdk[http-server]"

# Persistent task store on Postgres + telemetry
pip install "a2a-sdk[postgresql,telemetry]"

# Everything
pip install "a2a-sdk[all]"
```

### 2.1 Optional extras

| Extra         | Pulls in / enables                                                        |
|---------------|---------------------------------------------------------------------------|
| `http-server` | Starlette / FastAPI support — needed to expose JSON-RPC & REST routes      |
| `grpc`        | gRPC transport (`GrpcHandler`, gRPC client transport)                      |
| `signing`     | Agent Card signature creation / verification (`a2a.utils.signing`)         |
| `encryption`  | Payload encryption support                                                |
| `sqlite`      | SQLite driver for the persistent `DatabaseTaskStore`                       |
| `postgresql`  | PostgreSQL driver for the persistent `DatabaseTaskStore`                   |
| `mysql`       | MySQL driver for the persistent `DatabaseTaskStore`                        |
| `sql`         | All SQL drivers at once (sqlite + postgresql + mysql)                      |
| `db-cli`      | The `a2a-db` CLI for running task-store schema migrations                  |
| `telemetry`   | OpenTelemetry tracing hooks (`a2a.utils.telemetry`)                        |
| `all`         | Every extra above                                                          |

> **Rule**: `DatabaseTaskStore`, `DatabasePushNotificationConfigStore`, and `GrpcHandler` are exported as **placeholder classes** when their extra is missing. They import fine but raise `ImportError` at construction with a message telling you which extra to install. So a clean import does *not* mean the feature works — install the matching extra.

### 2.2 Using `uv` (recommended)

`uv` resolves and installs an order of magnitude faster, and its lockfile keeps the SDK version pinned across machines:

```bash
# In a project directory
uv init a2a-agent && cd a2a-agent
uv add "a2a-sdk[http-server]"

# Or, ad hoc, into an existing venv
uv pip install "a2a-sdk[http-server]"
```

💡 For a throwaway smoke test you don't even need a project: `uv run --with a2a-sdk python smoke_test.py`.

---

## 3. Recommended Project Layout

A2A agents have a small, predictable shape. Keep the **agent card**, the **executor** (your logic), and the **entrypoint** in separate modules so each stays testable:

```
a2a-agent/
├── pyproject.toml          # deps: a2a-sdk[http-server], uvicorn, ...
├── README.md
└── src/
    └── my_agent/
        ├── __init__.py
        ├── agent_card.py   # build_agent_card() -> AgentCard
        ├── executor.py     # MyAgentExecutor(AgentExecutor)
        └── __main__.py     # wires routes + handler, runs uvicorn
```

`pyproject.toml` — pin the SDK (see Section 5) and declare an ASGI server:

```toml
[project]
name = "my-agent"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "a2a-sdk[http-server]==1.1.2",
    "uvicorn>=0.30",
]

[project.scripts]
my-agent = "my_agent.__main__:main"
```

Why this split:

- `agent_card.py` — the card is static metadata; isolating it makes it trivial to unit-test and to serve at the `/.well-known/agent-card.json` path.
- `executor.py` — your `AgentExecutor` subclass holds *all* the agent behavior. It has no knowledge of HTTP.
- `__main__.py` — the only module that touches Starlette/FastAPI and `uvicorn`. Swapping transports later means editing one file.

> **Rule**: Keep transport wiring out of `executor.py`. An `AgentExecutor` that imports Starlette is an `AgentExecutor` you can't reuse behind gRPC.

---

## 4. Tour of the SDK Packages

### 4.1 `a2a.types` — the protocol data model

Every wire object is a generated, validated type. The core ones you'll touch constantly:

| Type            | Role                                                          |
|-----------------|---------------------------------------------------------------|
| `AgentCard`     | Agent's self-description (skills, capabilities, transport URLs)|
| `AgentSkill`    | One advertised capability inside a card                       |
| `AgentCapabilities` | Feature flags (streaming, push notifications)             |
| `Message`       | A single turn — carries one or more `Part`s and a `Role`      |
| `Part`          | Single protobuf oneof for content: `text`, `data`, `raw`, or `url` |
| `Task`          | A unit of work with a `TaskStatus` and `Artifact`s            |
| `TaskState`     | Enum: `TASK_STATE_SUBMITTED`, `TASK_STATE_WORKING`, ...       |

```python
from a2a.types import AgentCard, Message, Part, Task, TaskState
```

Error types (`TaskNotFoundError`, `InvalidParamsError`, `UnsupportedOperationError`, ...) are also re-exported from `a2a.types` even though they originate in `a2a.utils.errors`.

### 4.2 `a2a.server` — hosting an agent

| Submodule                       | Key names                                                       |
|---------------------------------|-----------------------------------------------------------------|
| `a2a.server.agent_execution`    | `AgentExecutor`, `RequestContext`, `RequestContextBuilder`      |
| `a2a.server.request_handlers`   | `DefaultRequestHandler`, `RequestHandler`, `GrpcHandler`        |
| `a2a.server.routes`             | `create_jsonrpc_routes`, `create_rest_routes`, `create_agent_card_routes` |
| `a2a.server.tasks`              | `InMemoryTaskStore`, `DatabaseTaskStore`, `TaskStore`, `TaskUpdater`, `TaskManager` |
| `a2a.server.events`             | `EventQueue`, `QueueManager`, `InMemoryQueueManager`            |

You implement `AgentExecutor`, hand it to `DefaultRequestHandler` along with a `TaskStore`, then turn the handler into **Asynchronous Server Gateway Interface (ASGI)** routes via the `create_*_routes` factories. ASGI is the async Python web-server contract that lets Starlette or FastAPI host those generated routes.

💡 In `1.1.2`, `DefaultRequestHandler` aliases `DefaultRequestHandlerV2` and uses a process-local active-task registry. The older `LegacyRequestHandler` remains for 0.3-style paths; prefer `DefaultRequestHandler` for new agents and close it during application shutdown.

### 4.3 `a2a.client` — talking to agents

| Name                | Role                                                       |
|---------------------|------------------------------------------------------------|
| `A2ACardResolver`   | Fetch a remote agent's `AgentCard` (e.g. from `/.well-known/...`) |
| `ClientFactory`     | Build a `Client` configured for a resolved card            |
| `create_client`     | One-shot convenience constructor                           |
| `Client`            | The transport-agnostic client object                       |
| `ClientConfig`      | Streaming, transport preference, polling options           |
| `minimal_agent_card`| Build a stub card when you only have a URL                 |

Transports live under `a2a.client.transports` (`jsonrpc`, `rest`, `grpc`); the factory picks one based on the card and your `ClientConfig`.

### 4.4 `a2a.utils` and `a2a.helpers`

- `a2a.utils` — constants (`AGENT_CARD_WELL_KNOWN_PATH`, `DEFAULT_RPC_URL`, `TransportProtocol`), error types, plus opt-in `signing` and `telemetry` submodules.
- `a2a.helpers` — ergonomic builders so you don't construct `Part`/`Message` trees by hand: `new_text_message`, `new_text_part`, `new_task`, `new_text_artifact`, `get_message_text`, and friends.

### 4.5 `a2a.compat` — 0.3 interoperability

`a2a.compat.v0_3` holds the JSON-RPC / REST / gRPC adapters and model conversions that let a `1.1.x` SDK speak to protocol-0.3 agents. You rarely import it directly — request handlers and transports use it when version negotiation requires it.

---

## 5. Version Compatibility

The SDK version and the spec version are **not** the same number — track both.

| SDK version      | Spec implemented | Notes                                                  |
|------------------|------------------|--------------------------------------------------------|
| `1.1.x` (baseline `1.1.2`) | A2A protocol 1.0 | Current checked line; includes 0.3 compatibility and current handler shutdown behavior |
| `1.0.x` | A2A protocol 1.0 | Older stable SDK line; upgrade deliberately |
| `0.3.x` and earlier    | A2A v0.3.x  | Pre-1.0. Different class names and module layout       |

Key points:

- **`1.0.0` was a breaking release.** Classes were renamed and modules reorganized between the `0.x` line and `1.0`. Code or tutorials written against `0.2`/`0.3` will not import cleanly under `1.0.x`.
- **0.3 compatibility mode** is about interoperability on the wire, not source compatibility. A `1.1.x` agent can negotiate down when configured to do so, but your Python source still uses current class names. Clients that require 1.0 features should disable silent fallback.
- The `request_handlers` package keeps a `LegacyRequestHandler` for 0.3-style server semantics; `DefaultRequestHandler` is the v2 (1.0) handler.

> **Rule**: Pin the SDK — `a2a-sdk==1.1.2`, not `a2a-sdk>=1.0`. Minor releases can change lifecycle behavior even when the wire protocol remains 1.0. Pin, read the changelog, run conformance checks, then upgrade deliberately.

⚠️ When following a blog post or tutorial, check its date and the SDK version it targets. An import like `from a2a.server.apps import A2AStarletteApplication` is a 0.x-era pattern; in `1.0.x` you compose routes with the `create_*_routes` factories instead.

---

## 6. Prove the extra you intend to use

The opening smoke test proves only the base model. Before continuing to the server note, verify the HTTP extra itself:

```bash
python -m pip install "a2a-sdk[http-server]==1.1.2"
python -c "from a2a.server.routes import create_jsonrpc_routes; print('http-server OK')"
```

The success signal is `http-server OK`. An `ImportError` that names an optional dependency means the base SDK is present but that extra is missing; a clean `import a2a` alone would not expose this silent mismatch.

---

**Next**: [Part 2: Building a Server](02_building_a_server.md)
