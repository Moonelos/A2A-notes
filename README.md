# A2A Protocol Notes

> A practical, implementation-focused guide to the Agent2Agent (A2A) protocol — from core concepts to production-grade multi-agent systems.

[![A2A](https://img.shields.io/badge/A2A-spec_1.0.0-4285F4.svg?logo=googlecloud&logoColor=white)](https://a2a-protocol.org/latest/specification/)
[![a2a-sdk](https://img.shields.io/badge/a2a--sdk-1.0.3-3776AB.svg?logo=python&logoColor=white)](https://pypi.org/project/a2a-sdk/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Linux Foundation](https://img.shields.io/badge/Governance-Linux_Foundation-003366.svg)](https://www.linuxfoundation.org/press/linux-foundation-launches-the-agent2agent-protocol-project-to-enable-secure-intelligent-communication-between-ai-agents)
[![License](https://img.shields.io/badge/Protocol-Apache_2.0-D22128.svg)](https://github.com/a2aproject/A2A)

---

## Structure

```
a2a-notes/
│
│ ── FUNDAMENTALS ───────────────────────────────────────
├── 01_fundamentals/      What A2A is, its vocabulary, and how it relates to MCP
│   ├── 01_what_is_a2a.md         Motivation, history, governance, where it fits
│   ├── 02_core_concepts.md       Agent Card, Task, Message, Part, Artifact, roles
│   └── 03_a2a_vs_mcp.md          Horizontal vs vertical; using both together
│
│ ── PROTOCOL ───────────────────────────────────────────
├── 02_protocol/          The wire protocol: discovery, transport, lifecycle
│   ├── 01_agent_card.md          Card schema, skills, discovery, signed cards
│   ├── 02_transport_and_rpc.md   JSON-RPC 2.0, gRPC, HTTP+JSON; RPC methods
│   ├── 03_task_lifecycle.md      Task states, the state machine, errors
│   └── 04_streaming_and_push.md  SSE streaming + push-notification webhooks
│
│ ── PYTHON SDK ─────────────────────────────────────────
├── 03_python/            Building A2A servers and clients with a2a-sdk
│   ├── 01_sdk_setup.md           Install, extras, project layout, versioning
│   ├── 02_building_a_server.md   AgentExecutor, request handlers, Starlette/FastAPI
│   └── 03_building_a_client.md   Resolving cards, ClientFactory, calling tasks
│
│ ── FRAMEWORKS ─────────────────────────────────────────
├── 04_frameworks/        Exposing existing agent frameworks over A2A
│   ├── 01_langchain_langgraph.md LangGraph agent as A2A server and client
│   ├── 02_google_adk.md          ADK agents, remote-agent consumption
│   └── 03_crewai_and_others.md   CrewAI, Semantic Kernel, LlamaIndex, AG2
│
│ ── PRODUCTION ─────────────────────────────────────────
└── 05_production/        Running A2A securely and at scale
    ├── 01_authentication.md      OAuth2/OIDC/API key/mTLS; card security schemes
    ├── 02_security_hardening.md  Card signing, input validation, threat model
    └── 03_scaling_deployment.md  Stateless servers, task stores, observability
```

---

## Contents

### Fundamentals — [full index](01_fundamentals/README.md)

[![A2A](https://img.shields.io/badge/A2A-spec_1.0.0-4285F4.svg)](https://a2a-protocol.org/latest/specification/)

| Guide | Description |
|-------|-------------|
| [What Is A2A?](01_fundamentals/01_what_is_a2a.md) | The interoperability problem A2A solves, its history, and Linux Foundation governance |
| [Core Concepts](01_fundamentals/02_core_concepts.md) | The protocol vocabulary: Agent Card, Task, Message, Part, Artifact, and client/server roles |
| [A2A vs MCP](01_fundamentals/03_a2a_vs_mcp.md) | Why A2A and the Model Context Protocol are complementary, not competing |

### Protocol — [full index](02_protocol/README.md)

[![JSON-RPC](https://img.shields.io/badge/JSON--RPC-2.0-F7DF1E.svg)](https://www.jsonrpc.org/specification)

| Guide | Description |
|-------|-------------|
| [The Agent Card](02_protocol/01_agent_card.md) | Card schema, skill declarations, discovery via well-known URI, signed and extended cards |
| [Transport & RPC](02_protocol/02_transport_and_rpc.md) | JSON-RPC, gRPC, and HTTP+JSON bindings; the full set of RPC methods |
| [Task Lifecycle](02_protocol/03_task_lifecycle.md) | The Task state machine, terminal states, input/auth-required pauses, error codes |
| [Streaming & Push](02_protocol/04_streaming_and_push.md) | Server-Sent Events for live updates and webhooks for disconnected clients |

### Python SDK — [full index](03_python/README.md)

[![a2a-sdk](https://img.shields.io/badge/a2a--sdk-1.0.3-3776AB.svg?logo=python&logoColor=white)](https://pypi.org/project/a2a-sdk/)
[![FastAPI](https://img.shields.io/badge/FastAPI-supported-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

| Guide | Description |
|-------|-------------|
| [SDK Setup](03_python/01_sdk_setup.md) | Installing `a2a-sdk`, optional extras, project layout, and version-compatibility notes |
| [Building a Server](03_python/02_building_a_server.md) | Implementing `AgentExecutor`, wiring request handlers, serving with Starlette or FastAPI |
| [Building a Client](03_python/03_building_a_client.md) | Resolving Agent Cards, `ClientFactory`, sending tasks, consuming streams |

### Frameworks — [full index](04_frameworks/README.md)

[![LangGraph](https://img.shields.io/badge/LangGraph-integrated-1C3C3C.svg)](https://langchain-ai.github.io/langgraph/)
[![Google ADK](https://img.shields.io/badge/Google_ADK-integrated-4285F4.svg?logo=googlecloud&logoColor=white)](https://google.github.io/adk-docs/)

| Guide | Description |
|-------|-------------|
| [LangChain & LangGraph](04_frameworks/01_langchain_langgraph.md) | Exposing a LangGraph agent as an A2A server and calling remote agents as tools |
| [Google ADK](04_frameworks/02_google_adk.md) | ADK's native A2A support: serving agents and consuming remote A2A agents |
| [CrewAI & Others](04_frameworks/03_crewai_and_others.md) | A2A integration for CrewAI, Semantic Kernel, LlamaIndex, and AG2/AutoGen |

### Production — [full index](05_production/README.md)

[![Auth](https://img.shields.io/badge/Auth-OAuth2_/_OIDC_/_mTLS-EB5424.svg?logo=auth0&logoColor=white)](https://a2a-protocol.org/latest/topics/enterprise-ready/)

| Guide | Description |
|-------|-------------|
| [Authentication](05_production/01_authentication.md) | Declaring and enforcing API key, OAuth2, OIDC, and mTLS auth in A2A |
| [Security Hardening](05_production/02_security_hardening.md) | Card signing, input validation, the A2A threat model, and defensive patterns |
| [Scaling & Deployment](05_production/03_scaling_deployment.md) | Stateless servers, shared task stores, push infrastructure, and observability |

---

## Reading Order

> [!TIP]
> Not sure where to start? Pick the path that matches your goal.

### Path 1 — New to A2A

1. [What Is A2A?](01_fundamentals/01_what_is_a2a.md) — understand the problem before the solution
2. [Core Concepts](01_fundamentals/02_core_concepts.md) — learn the vocabulary every later file uses
3. [A2A vs MCP](01_fundamentals/03_a2a_vs_mcp.md) — place A2A correctly in the agent stack
4. [The Agent Card](02_protocol/01_agent_card.md) — the first concrete artifact you will create

### Path 2 — Implementing in Python

1. [Core Concepts](01_fundamentals/02_core_concepts.md) — required vocabulary
2. [Transport & RPC](02_protocol/02_transport_and_rpc.md) — what the SDK does under the hood
3. [SDK Setup](03_python/01_sdk_setup.md) — install and lay out the project
4. [Building a Server](03_python/02_building_a_server.md) — expose your first agent
5. [Building a Client](03_python/03_building_a_client.md) — call other agents

### Path 3 — Integrating an existing framework

1. [Core Concepts](01_fundamentals/02_core_concepts.md) — vocabulary
2. [The Agent Card](02_protocol/01_agent_card.md) — what your framework must publish
3. The relevant [framework guide](04_frameworks/README.md) — LangGraph, ADK, CrewAI, etc.
4. [Building a Client](03_python/03_building_a_client.md) — the consumption side

### Path 4 — Shipping to production

1. [Task Lifecycle](02_protocol/03_task_lifecycle.md) — model long-running work correctly
2. [Streaming & Push](02_protocol/04_streaming_and_push.md) — handle disconnects and async results
3. [Authentication](05_production/01_authentication.md) — lock down agent-to-agent calls
4. [Security Hardening](05_production/02_security_hardening.md) — defend against the threat model
5. [Scaling & Deployment](05_production/03_scaling_deployment.md) — run it at scale
