# What Is A2A — and Why It Exists

> **Who this is for**: Engineers new to the A2A (Agent2Agent) protocol who already know HTTP and JSON and have a basic mental model of LLM agents. This is the first file in the knowledge base — start here, no prerequisites.

---

## 1️⃣ The Problem: Agents Can't Talk to Each Other

By 2025, building a single LLM agent was a solved problem. The hard part became getting *different* agents to cooperate.

A real workflow rarely fits inside one agent. Booking a trip involves a flights agent, a hotels agent, and a calendar agent — often built by different vendors, in different languages, hosted on different infrastructure. Without a shared protocol, every connection between two agents is a bespoke integration:

```
        WITHOUT A SHARED PROTOCOL

   Travel Agent ──custom glue──▶ Flights Agent (Vendor A)
        │
        ├────────custom glue──▶ Hotels Agent (Vendor B)
        │
        └────────custom glue──▶ Calendar Agent (Vendor C)

   N agents  ─▶  up to N×(N−1) one-off integrations
   Every new agent = re-wire everything it touches.
```

This is the **agent interoperability problem**. It is the same N-squared integration trap that plagued databases before ODBC and messaging before AMQP. The fix is always the same: agree on one protocol so every participant speaks a common language.

```
          WITH A SHARED PROTOCOL (A2A)

   Travel Agent ──┐
   Flights Agent ─┤
   Hotels Agent ──┼──▶  A2A  ◀── one protocol, any pair
   Calendar Agent ┘

   N agents  ─▶  N implementations of one protocol.
   New agent = implement A2A once, talk to everyone.
```

> **Key insight**: A2A is not a framework for *building* agents. It is a protocol for letting agents you have already built **communicate** — regardless of who built them or how.

---

## 2️⃣ What A2A Actually Is

**A2A (Agent2Agent)** is an open standard that lets independent AI agents discover each other, exchange messages and tasks, and collaborate — even when they are built by different vendors, on different frameworks, and run on separate infrastructure.

A2A deliberately runs on plumbing engineers already know:

| Layer | A2A uses | Why it matters |
|---|---|---|
| Transport | HTTP / HTTPS | No new ports, proxies, or tooling |
| RPC | JSON-RPC 2.0 | Plain request/response, easy to debug |
| Streaming | Server-Sent Events (SSE) | Incremental updates for long tasks |
| Discovery | **Agent Cards** | Machine-readable capability, transport, and auth metadata |
| Integrity | Optional signed Agent Cards | Tamper evidence when cards move through registries or caches |

Because the wire format is just HTTP and JSON, an A2A agent is — from the outside — an ordinary web service. Your existing load balancers, API gateways, auth middleware, and observability stack all work unchanged.

A2A defines a small set of primitives — Agent Cards, Tasks, Messages, Artifacts — covered in detail in [Core Concepts](02_core_concepts.md). For now, the mental model is enough: **one agent (a client) sends a task to another agent (a server) over HTTP and receives results back.**

> **Key insight**: A2A's most underrated design choice is being *boring*. Reusing HTTP, JSON-RPC, and SSE means there is almost nothing new to learn at the transport layer — the novelty is entirely in the agent semantics.

---

## 3️⃣ A Short History

A2A moved from a Google announcement to a vendor-neutral foundation project, then to a stable 1.0 specification, in less than a year.

```
 2025          2025           2026              2026
 Apr 9         Jun 23         Mar 12            Apr 9
   │             │               │                 │
   ▼             ▼               ▼                 ▼
 Announced    Donated to     50 → 100+         Spec v1.0.0:
 by Google    the Linux      organizations     first stable,
 at Cloud     Foundation     sign on           production-
 Next         as the                           ready release
              "Agent2Agent
              Protocol
              Project"
```

- **April 9, 2025** — Google announces A2A at Google Cloud Next, with 50+ launch partners.
- **June 23, 2025** — Google contributes A2A to the **Linux Foundation**, where it becomes the **Agent2Agent (A2A) Protocol Project**, governed for vendor neutrality and licensed under **Apache 2.0**. Founding supporters include AWS, Cisco, Microsoft, Salesforce, SAP, and ServiceNow alongside Google.
- **March 12, 2026** — A2A **v1.0.0** is released: the first stable spec. The breaking release aligns the wire format with ProtoJSON, moves transport declarations to `supportedInterfaces`, removes the old streaming `final` flag, and modernizes OAuth/security fields.
- **April 9, 2026** — At the one-year mark, the Linux Foundation reports 150+ supporting organizations, major cloud integrations, and active enterprise production use.

The Linux Foundation move matters: it means no single vendor controls the standard. A2A is now governed like Kubernetes or Linux itself — by an open, multi-stakeholder process.

> **Key insight**: Apache 2.0 + Linux Foundation governance is what makes A2A safe to build a business on. Competitors can adopt it without ceding control to a rival, which is precisely why adoption accelerated.

---

## 4️⃣ The Design Principles

A2A's behavior follows from five stated principles. Understanding them explains nearly every design decision in the spec.

| # | Principle | What it means in practice |
|---|---|---|
| 1 | **Simplicity** | Reuse existing standards (HTTP, JSON-RPC, SSE) instead of inventing new ones. |
| 2 | **Enterprise readiness** | First-class authentication, authorization, security, privacy, tracing, and monitoring — not afterthoughts. |
| 3 | **Asynchronous by default** | Built for long-running tasks and human-in-the-loop steps; agents may be only intermittently connected. |
| 4 | **Modality independence** | Agents exchange text, structured data, files, audio/video — not just chat strings. |
| 5 | **Opaque execution** | Agents collaborate **without exposing internal logic, memory, or proprietary tools**. |

The fifth principle — **opaque execution** — is the heart of A2A and deserves its own picture.

### The opaque agent model

A2A treats every remote agent as a black box. A client agent sees only the *declared capabilities* and the *outputs* of the agent it calls — never its prompts, model, tools, memory, or reasoning.

```
   CLIENT AGENT                 REMOTE AGENT
  ┌────────────┐               ┌──────────────────────────┐
  │            │  task ───────▶│  ░░ internal logic ░░     │
  │  sees:     │               │  ░░ private tools  ░░     │  ← invisible
  │  - card    │◀─── result ───│  ░░ memory / model ░░     │    to caller
  │  - outputs │               │                          │
  └────────────┘               └──────────────────────────┘
        only declared capabilities cross the boundary
```

This is what separates A2A from "wrap the other agent as a function I call." Opacity gives you two things at once:

- ✅ **IP protection** — vendors expose a capability without revealing how it works.
- ✅ **Security** — a caller cannot reach into another agent's tools or data.

> **Principle**: In A2A, agents are **autonomous peers**, not tools. A peer is asked to *accomplish a goal*; a tool is *invoked with arguments*. That distinction drives the whole protocol — and is the cleanest way to tell A2A apart from MCP (see [A2A vs MCP](03_a2a_vs_mcp.md)).

---

## 5️⃣ Where A2A Sits in the Agent Stack

A2A is one layer in a larger stack. It does not replace models, frameworks, or tool protocols — it complements them.

```
   ┌─────────────────────────────────────────────┐
   │  AGENT FRAMEWORKS  (ADK, LangGraph, CrewAI)  │  build agents
   ├─────────────────────────────────────────────┤
   │  A2A  ── agent  ⇄  agent  collaboration      │  ◀── this protocol
   ├─────────────────────────────────────────────┤
   │  MCP  ── agent  →  tools / data sources      │  give one agent
   ├─────────────────────────────────────────────┤   access to tools
   │  MODELS  (LLMs that supply the reasoning)    │
   └─────────────────────────────────────────────┘
```

The two protocol layers answer different questions:

| Question | Protocol |
|---|---|
| "How does *one* agent reach a tool, database, or API?" | **MCP** (Model Context Protocol) |
| "How do *two* agents — built independently — collaborate?" | **A2A** |

They are complementary, not competing. A single agent commonly uses **MCP internally** to call its own tools, and **A2A externally** to delegate sub-tasks to other agents. The full comparison lives in [A2A vs MCP](03_a2a_vs_mcp.md).

> **Key insight**: MCP connects an agent *downward* to tools. A2A connects an agent *sideways* to peers. Most production systems need both.

---

## 6️⃣ Adoption and Ecosystem

A2A's traction is unusually fast for a protocol this young.

- **150+ organizations** support A2A by 2026 — including AWS, Cisco, Google, IBM, Microsoft, Salesforce, SAP, and ServiceNow — up from ~50 at launch.
- It is integrated into major cloud platforms and has reached **enterprise production use** within its first year.
- **Five official SDKs**, maintained under the `a2aproject` organization, implement the same canonical data model:

| SDK | Notes |
|---|---|
| **Python** | Reference implementation; most extensively documented |
| **JavaScript / TypeScript** | For Node and web-facing agents |
| **Java** | Enterprise JVM stacks |
| **Go** | High-throughput services |
| **.NET** | Microsoft ecosystem |

Because all five SDKs target the same spec, an agent written in Go can call an agent written in Python with no special bridging — which is the entire point of the protocol.

> **Key insight**: A protocol is only as useful as its implementations. Five vendor-neutral SDKs across the dominant backend languages mean you can adopt A2A in your existing stack instead of changing it.

---

## 7️⃣ When to Reach for A2A

A2A is not the answer to every integration. Use this to decide:

| Scenario | Use A2A? |
|---|---|
| Delegating a sub-task to an agent built by another team or vendor | ✅ Yes |
| Composing a multi-agent workflow across frameworks/languages | ✅ Yes |
| Long-running or human-in-the-loop tasks needing status updates | ✅ Yes |
| Giving one agent access to a database, file, or API | ❌ No — use MCP |
| A plain function call inside a single codebase | ❌ No — just call the function |
| Two services that are not agents exchanging data | ❌ No — use a normal REST/RPC API |

⚠️ **Common mistake**: reaching for A2A when you only need a tool call. If the remote thing has no autonomy — it just executes with arguments — it is a tool, and MCP or a plain API is the simpler choice.

> **Key insight**: A2A earns its keep when the other side is *autonomous* — it decides how to accomplish a goal, may take time, and you should not (or cannot) see inside it. Anything less, and a simpler integration wins.

---

**Next**: [Part 2: Core Concepts](02_core_concepts.md)
