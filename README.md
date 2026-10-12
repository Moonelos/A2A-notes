# A2A Protocol Notes

> A practical, implementation-focused guide to the Agent2Agent (A2A) protocol — from core concepts to production-grade multi-agent systems.

**Audience:** developers comfortable with basic Python, HTTP, JSON, and command-line use; no prior A2A knowledge is assumed. Framework branches assume the chosen framework. The notes teach A2A wire protocol 1.0 (specification patch 1.0.1) and pin Python SDK 1.1.2 for reproducible examples. The SDK pin is historical as of 2026-10-12; newer 1.2.x behavior is covered as upgrade context. AP2 payment mandate details are outside this A2A learning path.

**Production version gate:** [SDK 1.1.4 fixed owner-scoped cancel/subscribe and push callback URL validation](https://github.com/a2aproject/a2a-python/releases). Do not deploy the 1.1.2 teaching pin unchanged for multi-tenant or callback-enabled production; upgrade and rerun the isolation and callback tests in the production path.

[![A2A](https://img.shields.io/badge/A2A-wire_1.0_%7C_spec_1.0.1-4285F4.svg?logo=googlecloud&logoColor=white)](https://a2a-protocol.org/latest/specification/)
[![a2a-sdk](https://img.shields.io/badge/a2a--sdk-1.1.2-3776AB.svg?logo=python&logoColor=white)](https://pypi.org/project/a2a-sdk/)
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
│   ├── 04_streaming_and_push.md  SSE streaming + push-notification webhooks
│   ├── 05_extensions_and_custom_bindings.md  Extension negotiation and bindings
│   ├── 06_version_negotiation_and_migration.md Version rollout and compatibility
│   └── 07_agent_payments_ap2.md  AP2 payment mandates over A2A
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
    ├── 03_scaling_deployment.md  Stateless servers, task stores, observability
    ├── 04_multi_tenant_scoping.md Tenant routing and resource isolation
    └── 05_conformance_and_interoperability.md Inspector/TCK release validation
```

---

## Contents

### Fundamentals — [full index](01_fundamentals/README.md)

[![A2A](https://img.shields.io/badge/A2A-wire_1.0_%7C_spec_1.0.1-4285F4.svg)](https://a2a-protocol.org/latest/specification/)

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
| [Extensions & Bindings](02_protocol/05_extensions_and_custom_bindings.md) | Declaring, activating, and governing protocol extensions and custom bindings |
| [Version Migration](02_protocol/06_version_negotiation_and_migration.md) | Explicit version selection and staged v0.3-to-v1.0 rollout |
| [Agent Payments with AP2](02_protocol/07_agent_payments_ap2.md) | Where AP2 payment mandates extend an ordinary A2A task |

### Python SDK — [full index](03_python/README.md)

[![a2a-sdk](https://img.shields.io/badge/a2a--sdk-1.1.2-3776AB.svg?logo=python&logoColor=white)](https://pypi.org/project/a2a-sdk/)
[![FastAPI](https://img.shields.io/badge/FastAPI-supported-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

| Guide | Description |
|-------|-------------|
| [SDK Setup](03_python/01_sdk_setup.md) | Installing the 1.1.2 baseline, optional extras, project layout, and compatibility notes |
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
| [Multi-Tenant Scoping](05_production/04_multi_tenant_scoping.md) | Verified tenant routing and owner-scoped tasks, streams, jobs, and push configs |
| [Conformance](05_production/05_conformance_and_interoperability.md) | Inspector/TCK and cross-binding release gates |

---

## Reading Order

> [!TIP]
> Not sure where to start? Pick the path that matches your goal.

### Path 1 — New to A2A

1. [What Is A2A?](01_fundamentals/01_what_is_a2a.md) — understand the problem before the solution
2. [Core Concepts](01_fundamentals/02_core_concepts.md) — learn the vocabulary every later file uses
3. [A2A vs MCP](01_fundamentals/03_a2a_vs_mcp.md) — conceptual stop: you can now decide which protocol belongs where
4. [The Agent Card](02_protocol/01_agent_card.md) — continue here when you will implement discovery

### Path 2 — Implementing in Python

1. [SDK Setup](03_python/01_sdk_setup.md) — install 1.1.2 and run the smoke test
2. [Building a Server](03_python/02_building_a_server.md) — run the minimal echo agent first
3. [Core Concepts](01_fundamentals/02_core_concepts.md) and [Transport & RPC](02_protocol/02_transport_and_rpc.md) — understand the working exchange
4. [Task Lifecycle](02_protocol/03_task_lifecycle.md) — learn the terminal and interrupted states your executor must drive
5. Return to the hardened sections of [Building a Server](03_python/02_building_a_server.md) — server-only stop after lifecycle, shutdown, and error tests pass
6. [Building a Client](03_python/03_building_a_client.md) — continue for callers, orchestrators, streaming recovery, and auth

### Path 3 — Integrating an existing framework

Choose your branch and begin with its minimal exposure outcome: [LangChain/LangGraph](04_frameworks/01_langchain_langgraph.md), [Google ADK](04_frameworks/02_google_adk.md), or the direct [CrewAI, Semantic Kernel, LlamaIndex, and AG2 branches](04_frameworks/03_crewai_and_others.md#choose-a-branch-before-you-read-the-implementations). Pair it with [SDK Setup](03_python/01_sdk_setup.md) within your first two steps so the protocol dependency is pinned and verified.

After the agent is exposed, use [Core Concepts](01_fundamentals/02_core_concepts.md) and [The Agent Card](02_protocol/01_agent_card.md) to understand and inspect what the adapter published. Stop after exposure tests pass. Continue to [Building a Client](03_python/03_building_a_client.md) only for lower-level consumption, custom credentials, or stream recovery not supplied by the framework.

### Path 4 — Shipping to production

**Entry contract**: start with a working [server](03_python/02_building_a_server.md) and [client](03_python/03_building_a_client.md), plus a reviewed [Agent Card](02_protocol/01_agent_card.md).

1. [Task Lifecycle](02_protocol/03_task_lifecycle.md) — model long-running work correctly
2. [Streaming & Push](02_protocol/04_streaming_and_push.md) — handle disconnects and async results
3. [Authentication](05_production/01_authentication.md) — establish and carry the caller principal
4. [Security Hardening](05_production/02_security_hardening.md) and [Multi-Tenant Scoping](05_production/04_multi_tenant_scoping.md) — secure single-replica milestone
5. [Scaling & Deployment](05_production/03_scaling_deployment.md) — continue for multiple replicas, durable jobs, or operational SLOs
6. [Conformance & Interoperability](05_production/05_conformance_and_interoperability.md) — release gate every advertised binding

The production notes include executable local proofs for owner-scoped JSON-RPC access, worker crash recovery, and SDK cross-replica Task state. A deployment is ready only after the same checks pass with your issuer, shared stores, worker, broker, callbacks, gateway, and advertised bindings; the [conformance guide](05_production/05_conformance_and_interoperability.md) gives the release gate.

## What's changing

Checked 2026-10-12 against the [SDK releases](https://github.com/a2aproject/a2a-python/releases), [protocol releases](https://github.com/a2aproject/A2A/releases), and [official roadmap](https://github.com/a2aproject/A2A/blob/main/docs/roadmap.md). The runnable examples stay pinned to SDK 1.1.2; use [SDK Setup](03_python/01_sdk_setup.md) and [Scaling & Deployment](05_production/03_scaling_deployment.md) when evaluating an upgrade.

| Item | Status | Decision impact |
|---|---|---|
| SDK 1.2.0 opt-in cluster mode; card cache and media-type validation | GA | Compare cluster mode with the explicit worker design and test card/runtime parity. |
| SDK 1.2.2 SSE shutdown grace and REST/compatibility fixes | GA | Recheck shutdown, REST errors, and v0.3 conversion during upgrades. |
| SDK 1.1.4 owner-scope and push URL fixes | GA security fixes | Upgrade the teaching pin before tenant-scoped or callback-enabled deployment. |
| A2A 1.1 task timeline/event filtering and bidirectional streaming | Preview roadmap | Keep 1.0 SSE and Task guarantees as the baseline. |
| Elicitation/multi-turn patterns and A2A CLI | Preview roadmap | Do not use proposed schemas or tooling as a conformance gate yet. |
| v0.3 card/type fields removed in v1.0 | Deprecated/removed | Use the [migration guide](02_protocol/06_version_negotiation_and_migration.md) for mixed fleets. |

[Glossary](GLOSSARY.md) defines the terms used across the paths and links to their teaching notes.
