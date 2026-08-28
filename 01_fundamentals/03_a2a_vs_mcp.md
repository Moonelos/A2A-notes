# A2A vs MCP: Two Axes, One Architecture

> **Who this is for**: Engineers who have read the A2A core concepts and want to understand how A2A fits alongside the Model Context Protocol (MCP). Some prior MCP familiarity helps but is not required.

Before reading this, understand the building blocks of A2A: **[Core Concepts](02_core_concepts.md)**.

---

## 1️⃣ The Common Misconception

The first question almost everyone asks is "A2A or MCP — which one do I pick?" That framing is wrong. They are not alternatives. They solve **different problems on different axes** of an agentic system, and a serious production app runs **both at once**.

| | **MCP (Model Context Protocol)** | **A2A (Agent2Agent Protocol)** |
|---|---|---|
| Axis | Vertical | Horizontal |
| Connects | One agent → its tools, data, resources | Agent ↔ agent (peers) |
| Question it answers | "How does this agent *use* a capability?" | "How do agents *partner* on a task?" |
| Counterpart | A tool / data source (often stateless) | Another autonomous agent (stateful, reasoning) |
| Interaction shape | Function call: structured input → output | Task lifecycle: messages, streaming, multi-turn |
| Governance | Agentic AI Foundation (Linux Foundation), after Anthropic donated MCP in December 2025 | Agent2Agent Protocol Project (Linux Foundation), after Google donated A2A in June 2025 |

MCP is commonly the internal wiring of an agent, while A2A is external collaboration between agents. The analogy is directional, not exclusive: either protocol can cross a process or organizational boundary.

Both protocols now live under the broader **Linux Foundation** umbrella, but not in the same project. A2A is hosted by the Linux Foundation's **Agent2Agent Protocol Project**. MCP moved to the Linux Foundation's **Agentic AI Foundation** in December 2025, alongside AGENTS.md and goose. The practical architecture point is unchanged: A2A and MCP are complements, not rivals.

---

## 2️⃣ The Two Axes — A Picture

Picture a single agent at the center of a cross. MCP runs **down**, A2A runs **across**.

```
                    HORIZONTAL  ──  A2A  (agent ↔ agent)
                            │
        ┌───────────┐       │       ┌───────────┐
        │  Hotel    │◄──────┼──────►│  Flights  │
        │  Agent    │  A2A  │  A2A  │  Agent    │
        └─────┬─────┘       │       └─────┬─────┘
              │             │             │
              │     ┌───────▼────────┐    │
              │     │                │    │
              └────►│  TRIP PLANNER  │◄───┘
                    │     AGENT      │
                    │                │
                    └───────┬────────┘
                            │
                            │  MCP   (agent → tools/data)
                            │  VERTICAL
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Calendar │  │ Weather  │  │  Maps    │
        │   tool   │  │   API    │  │   API    │
        └──────────┘  └──────────┘  └──────────┘
         (MCP tools / resources — structured, stateless)
```

- **Going down (MCP)**: the Trip Planner reaches its own tools — a calendar, a weather API, a maps service. These are well-defined primitives with structured inputs and outputs. They do not reason; they execute.
- **Going across (A2A)**: the Trip Planner talks to *other agents* — a Flights agent, a Hotel agent — as peers. Those agents reason, plan, hold state across turns, and may use *their own* MCP tools underneath.

Every peer on the horizontal axis can itself use MCP tools beneath it: A2A between agents, MCP within an agent's capability layer.

---

## 3️⃣ Contrasting the Primitives

The protocols feel different the moment you look at what they expose.

**MCP primitives** — server-side capabilities an agent consumes:

| Primitive | What it is |
|---|---|
| **Tool** | A callable function with a JSON schema. Stateless, deterministic-ish, single round-trip. |
| **Resource** | Readable data the agent can pull into context (a file, a record, a URL). |
| **Prompt** | A reusable prompt template the host can offer to the user. |

**A2A primitives** — the vocabulary of agent collaboration:

| Primitive | What it is |
|---|---|
| **Agent Card** | A public, discoverable descriptor of an agent's identity, skills, and endpoints. |
| **Task** | A unit of work with a lifecycle (`submitted` → `working` → `completed`/`failed`/`input-required`). |
| **Message** | A turn in a conversation between client and remote agent — request or update. |
| **Artifact** | A concrete output produced by a Task (a document, an image, structured data). |

The shapes still differ, but lifecycle alone is no longer the discriminator. An ordinary MCP `Tool` is a function-like invocation. The official **MCP Tasks extension** can add durable long-running execution, polling, progress metadata, and an `input_required` pause. A2A Tasks provide lifecycle together with peer discovery, agent messages, artifacts, and collaboration context. MCP optimizes for exposing a host capability; A2A optimizes for delegating to an autonomous peer.

⚠️ A common mistake is choosing A2A only because work is long-running. If a host needs a durable operation from one of its own capabilities, MCP Tasks may be sufficient. Choose A2A when the counterpart is an autonomous, discoverable peer whose messages, artifacts, and collaboration context are part of the contract.

---

## 4️⃣ When to Reach for Which

| Signal in your design | Use **MCP** | Use **A2A** |
|---|---|---|
| The counterpart is a function/API/data store | ✅ | ❌ |
| The counterpart reasons, plans, or chooses its own tools | ❌ | ✅ |
| Interaction is a single structured request → response | ✅ | ❌ |
| One host capability needs durable polling/progress/input pause | ✅ (MCP Tasks) | possible, usually unnecessary |
| An autonomous peer needs multi-turn messages and artifacts | possible adapter | ✅ |
| You need discovery of *who* can do a job (capability catalog) | ❌ | ✅ (Agent Card) |
| You want to pull a document/record into the model's context | ✅ (Resource) | ❌ |
| The counterpart is owned by a different team/org/vendor | possible | ✅ (preferred) |
| You need lifecycle only, without peer-agent semantics | ✅ (MCP Tasks) | possible |
| You need lifecycle plus agent discovery/messages/artifacts | ❌ | ✅ |

> **Rule of thumb**: If you are *using* a capability, that's MCP. If you are *partnering* with something that has its own judgment, that's A2A.

### Scenario A — Trip planner (the canonical case)

A `TripPlanner` agent receives "Plan me a 4-day trip to Lisbon."

- **MCP, internally**: it calls a flights-search MCP tool, reads a weather Resource, queries a maps API. All vertical, all its own.
- **A2A, outward**: hotel booking is owned by a separate `HotelBooking` agent (different team, holds inventory state, negotiates dates). The planner delegates a `Task` over A2A: "book 3 nights near Alfama under €600." The hotel agent may reply `input-required` ("two options, which?"), stream a `working` update, then return a confirmation `Artifact`.

One agent, both protocols, each on its natural axis.

### Scenario B — Auto repair shop (from the spec)

A `ShopManager` agent runs a multi-turn diagnostic conversation with a customer over A2A. It delegates to `Mechanic` agents over A2A. Each `Mechanic` uses **MCP** to drive specialized tools — a diagnostic scanner, a repair-manual database, a platform lift — and uses **A2A** to coordinate with a `PartsSupplier` agent. The customer never sees the tools; they see collaborating agents.

### Scenario C — Internal RAG assistant (MCP-only is fine)

A support assistant that answers from a knowledge base, hits a ticketing API, and reads user records needs **no A2A at all**. Nothing here is a peer agent — it's all tools and data. Reaching for A2A would add a coordination layer with nothing to coordinate.

Not every system needs both. MCP-only is often right for a single agent with tools, including durable MCP Tasks. A2A enters when another autonomous peer and its collaboration contract matter.

---

## 5️⃣ Crossing the Layers — and Why You Usually Shouldn't

The protocols are bridgeable in both directions:

- **A2A agent exposed as an MCP tool** — an A2A server can surface a skill as an MCP `Tool`, so an MCP-only host can invoke it.
- **MCP tool wrapped as an A2A agent** — you can put a thin A2A agent in front of an MCP server so peers can `Task` it.

These bridges are legitimate adapters at a boundary. But keeping each protocol at its **natural layer** is cleaner, and here is why:

- ❌ **Wrapping an A2A agent as a plain MCP tool flattens its collaboration model.** MCP Tasks can preserve long-running state, progress, polling, and input pauses, but the adapter must still map or discard A2A discovery, Message, Artifact, and peer-context semantics. Use that bridge only when the MCP host does not need the full A2A contract.
- ❌ **Wrapping an MCP tool as an A2A agent adds ceremony for nothing.** A stateless API call gains Agent Card discovery, task state machines, and message turns it never needed. More moving parts, more failure surface, no benefit.
- ✅ **Match the protocol to the relationship.** Tool-shaped thing on the vertical axis with MCP. Agent-shaped peer on the horizontal axis with A2A. The code reads the way the system actually works.

⚠️ The honest exception: a real org boundary. If the *only* thing a partner exposes is an MCP endpoint, wrap it — pragmatism beats purity at a boundary you do not control. Just treat the wrapper as an adapter, not as your default architecture.

> **Key insight**: Duration no longer decides between MCP and A2A. Choose MCP Tasks for a durable host capability; choose A2A when the remote party's autonomous identity, discovery, messages, artifacts, and collaboration context are part of the contract.

---

**Next**: [Part 1: The Agent Card](../02_protocol/01_agent_card.md)
