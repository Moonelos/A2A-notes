# A2A Core Concepts: The Protocol Vocabulary

> **Who this is for**: Engineers new to A2A who need the shared glossary. Every later file in this repo assumes you know the terms defined here. Before reading this, understand the high-level picture: **[What Is A2A?](01_what_is_a2a.md)**.

A2A (Agent2Agent) is a protocol for one autonomous agent to discover, call, and collaborate with another over HTTP. To do that, both sides must agree on a small set of nouns: who the participants are, how they advertise themselves, and the shape of the data that flows between them.

This file defines that vocabulary against the **v1.0.0 specification** (`a2a-protocol.org/latest/specification/`). Treat it as the dictionary you keep open while reading everything else.

---

## 1️⃣ The Two Roles: A2A Server and A2A Client

A2A is a client–server protocol. Every interaction has exactly two participants, and the roles describe *behavior in a single exchange* — not a fixed identity.

- **A2A Server** — also called the **remote agent**. It is the agent being called. It hosts an HTTP endpoint, publishes an **Agent Card**, receives requests, runs work, and returns Tasks, Messages, and Artifacts.
- **A2A Client** — the calling agent or application. It discovers a server via its Agent Card, then sends requests to that server's endpoint and consumes the responses.

> **Key insight**: The roles are per-conversation, not permanent. An agent that is a *server* to a user-facing app can simultaneously be a *client* of three other specialist agents it delegates to. A2A is designed for these chains of delegation.

```
   User-facing app                  Specialist agent
   ┌──────────────┐                 ┌──────────────┐
   │  A2A Client  │ ──── request ──▶│  A2A Server  │
   │              │ ◀─── Task ───── │ (remote agent)│
   └──────────────┘                 └──────┬───────┘
                                            │ same agent,
                                            │ now acting as
                                            ▼
                                     ┌──────────────┐
                                     │  A2A Client  │ ──▶ another server
                                     └──────────────┘
```

The protocol itself is transport-bound to HTTP and uses JSON-RPC 2.0 (or gRPC / HTTP+JSON, depending on the interface the server advertises). What matters for the vocabulary is the *data shapes* below — they are the same regardless of transport.

---

## 2️⃣ Agent Card: The Discovery Document

The **Agent Card** is a JSON document that a server publishes so clients can find it and know how to talk to it. It is the entry point for everything: a client reads the card *before* sending any request.

It declares, at minimum:

- **Identity** — `name`, `description`, and the agent's own `version`.
- **Supported interfaces** — where to send requests (`supportedInterfaces`), ordered by server preference.
- **Capabilities** — feature flags such as streaming and push notifications (`capabilities`).
- **Security schemes** — how a client authenticates (`securitySchemes`) and which schemes are required (`securityRequirements`).
- **Skills** — a list of `AgentSkill` objects describing what the agent can do.

```json
{
  "name": "Weather Agent",
  "description": "Provides forecasts and severe-weather alerts.",
  "version": "2.1.0",
  "supportedInterfaces": [
    {
      "url": "https://weather.example.com/a2a",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": { "streaming": true, "pushNotifications": false },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain", "application/json"],
  "securitySchemes": {
    "bearer": {
      "httpAuthSecurityScheme": { "scheme": "Bearer", "bearerFormat": "JWT" }
    }
  },
  "securityRequirements": [
    { "schemes": { "bearer": { "list": [] } } }
  ],
  "skills": [ /* AgentSkill objects — see next section */ ]
}
```

> **Key insight**: The Agent Card is to A2A what an OpenAPI spec is to a REST API — a machine-readable contract. A client should never hardcode a server's behavior; it should read the card.

This is only a sketch. The full card structure — signatures, extended cards, transport negotiation — is covered in **[The Agent Card](../02_protocol/01_agent_card.md)**.

---

## 3️⃣ AgentSkill: A Unit of Advertised Capability

An **AgentSkill** is one discrete capability the agent advertises inside its Agent Card's `skills` array. Skills let a client (or an orchestrating agent) decide *which* agent to route a request to.

| Field         | Type       | Meaning |
|---------------|------------|---------|
| `id`          | string     | Stable, unique identifier for the skill. |
| `name`        | string     | Short human-readable name. |
| `description` | string     | What the skill does, in prose. |
| `tags`        | string[]   | Keywords for categorization and discovery. |
| `examples`    | string[]   | Sample prompts or use cases the skill handles. |
| `inputModes`  | string[]   | MIME types the skill accepts (overrides the card's `defaultInputModes`). |
| `outputModes` | string[]   | MIME types the skill produces (overrides `defaultOutputModes`). |

```json
{
  "id": "forecast-lookup",
  "name": "Weather Forecast",
  "description": "Returns a multi-day forecast for a named location.",
  "tags": ["weather", "forecast", "geo"],
  "examples": [
    "What's the weather in Lisbon this weekend?",
    "5-day forecast for 48.85, 2.35"
  ],
  "inputModes": ["text/plain"],
  "outputModes": ["application/json"]
}
```

> **Key insight**: `inputModes` / `outputModes` are *MIME types*, not free-form labels. They tell the client what content it may send in (text, images, audio) and what to expect back — the basis for multi-modal interaction.

---

## 4️⃣ Task: The Stateful Unit of Work

A **Task** is the central object of A2A. When a client asks a server to *do something*, the server may create a Task to represent that work. A Task is **stateful** and **server-owned**: the server assigns its `id` and is the sole authority on its status.

| Field       | Type        | Meaning |
|-------------|-------------|---------|
| `id`        | string      | Server-generated unique identifier for this Task. |
| `contextId` | string      | Groups this Task with related Tasks/Messages (see §8). |
| `status`    | TaskStatus  | Current lifecycle state — `{ state, message?, timestamp? }`. |
| `history`   | Message[]   | Ordered conversational turns exchanged for this Task. |
| `artifacts` | Artifact[]  | Tangible outputs the Task has produced. |
| `metadata`  | object      | Arbitrary key-value data attached by the server. |

```json
{
  "id": "task-9f3c1e",
  "contextId": "ctx-trip-planning-42",
  "status": {
    "state": "working",
    "timestamp": "2026-05-18T14:03:11Z"
  },
  "history": [ /* Message objects */ ],
  "artifacts": [ /* Artifact objects */ ],
  "metadata": { "priority": "normal" }
}
```

The `status.state` field moves through ProtoJSON enum values like `TASK_STATE_SUBMITTED`, `TASK_STATE_WORKING`, `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, and `TASK_STATE_CANCELED`. Not every interaction needs a Task — a quick question may be answered with a single Message and no Task at all. The full state machine and when a Task is created is covered in **[Task Lifecycle](../02_protocol/03_task_lifecycle.md)**.

> **Key insight**: A Task is *long-lived and resumable*. Because the server owns the `id`, a client can disconnect, reconnect later, and poll the same Task by its `id` — essential for long-running agent work.

---

## 5️⃣ Message: One Conversational Turn

A **Message** represents a single turn in the conversation between client and server — a request, a reply, a clarification. Messages are *ephemeral communication*, in contrast to a Task (durable state) and an Artifact (durable output).

| Field               | Type       | Meaning |
|---------------------|------------|---------|
| `messageId`         | string     | Unique identifier created by the sender. |
| `role`              | enum       | `ROLE_USER` (from the client) or `ROLE_AGENT` (from the server). |
| `parts`             | Part[]     | The content of the turn — one or more Parts. |
| `contextId`         | string     | Conversation this Message belongs to (see §8). |
| `taskId`            | string     | Task this Message relates to, if any. |
| `referenceTaskIds`  | string[]   | Other Tasks this Message refers to. |
| `metadata`          | object     | Arbitrary sender-supplied data. |
| `extensions`        | string[]   | URIs of protocol extensions in use. |

```json
{
  "messageId": "msg-001",
  "role": "ROLE_USER",
  "contextId": "ctx-trip-planning-42",
  "parts": [
    { "text": "Plan a 3-day trip to Kyoto in autumn." }
  ]
}
```

> **Key insight**: `role` is always relative to the protocol, not the human. `ROLE_USER` means "the calling side of this A2A exchange" — even when that caller is itself an autonomous agent with no human in the loop.

---

## 6️⃣ Part: The Unit of Content

A **Part** is the smallest piece of content. Every Message and every Artifact carries a list of Parts. There are **three logical kinds** of content a Part can hold:

- **Text content** — plain text. Carries a `text` field.
- **File content** — a file, supplied either *inline* as base64 bytes (`raw`) **or** *by reference* as a URL (`url`). Carries `mediaType` and optional `filename`.
- **Data content** — structured machine-readable JSON. Carries a `data` field (any JSON value) — used for forms, parameters, and tool-style payloads.

⚠️ **v1.0 change**: In v1.0 these are *not* three separate object types. The spec defines a **single unified `Part`** object, and the kind is determined by **which field is present** — there is no `kind` discriminator field (that field existed in pre-1.0 drafts and was removed). Likewise `mimeType` was renamed to `mediaType`.

```json
// Text content — "text" field present
{ "text": "Kyoto is best visited in November for autumn foliage." }

// File content by reference — "url" field present
{
  "url": "https://cdn.example.com/itinerary.pdf",
  "mediaType": "application/pdf",
  "filename": "itinerary.pdf"
}

// File content inline — "raw" field present (base64-encoded bytes)
{
  "raw": "JVBERi0xLjcKJ...",
  "mediaType": "application/pdf",
  "filename": "itinerary.pdf"
}

// Data content — "data" field present
{
  "data": {
    "destination": "Kyoto",
    "nights": 3,
    "season": "autumn"
  }
}
```

To dispatch on a Part's kind, check field presence rather than a type tag:

```
if ("text" in part)        -> text content
else if ("data" in part)   -> structured JSON
else if ("raw" in part)    -> inline file bytes (base64)
else if ("url" in part)    -> file by reference
```

> **Key insight**: A single Message can mix Part kinds — e.g. text instructions plus structured `data` parameters plus a file attachment. This is how A2A carries multi-modal, structured interactions in one turn.

---

## 7️⃣ Artifact: A Tangible Task Output

An **Artifact** is a concrete result produced by a Task — a generated report, an image, a structured dataset. Like a Message, an Artifact is **composed of Parts**, but its purpose is different: a Message is a turn of *conversation*, an Artifact is a *deliverable* that persists on the Task.

| Field        | Type     | Meaning |
|--------------|----------|---------|
| `artifactId` | string   | Identifier, unique within the owning Task. |
| `name`       | string   | Optional human-readable label. |
| `description`| string   | Optional explanation of the Artifact. |
| `parts`      | Part[]   | The content — at least one Part. |
| `metadata`   | object   | Optional arbitrary data. |
| `extensions` | string[] | Optional extension URIs. |

```json
{
  "artifactId": "art-itinerary-1",
  "name": "Kyoto 3-Day Itinerary",
  "description": "Day-by-day plan with map links.",
  "parts": [
    { "text": "Day 1: Fushimi Inari at sunrise..." },
    { "data": { "days": 3, "totalCostEstimateUSD": 640 } }
  ]
}
```

> **Key insight**: Messages are how agents *talk*; Artifacts are what they *produce*. A Task's `history` holds the conversation; its `artifacts` hold the results. Both are just containers of Parts.

---

## 8️⃣ contextId: Grouping Tasks Into a Conversation

A **contextId** is a string identifier (typically a UUID) that ties together all Tasks and Messages belonging to the same logical conversation or workflow. It is the protocol's notion of a "session."

Both `Task` and `Message` carry an optional `contextId`. When a client wants several Tasks treated as one ongoing collaboration — a multi-turn trip-planning session, say — it reuses the same `contextId` across all of them.

```
contextId: "ctx-trip-planning-42"
   │
   ├── Task task-9f3c1e   ("find flights")        status: completed
   ├── Task task-a72d04   ("book hotel")          status: working
   └── Message msg-118    ("also add a car")      role: ROLE_USER
```

> **Key insight**: `id` (or `taskId`) scopes a *single piece of work*; `contextId` scopes a *whole conversation*. A long collaboration has one stable `contextId` and many short-lived Task `id`s underneath it.

---

## 9️⃣ How It All Nests

Two container hierarchies sit under a Task. Both bottom out at **Part** — the universal content unit.

```
contextId  "ctx-trip-planning-42"   ── the conversation
   │
   └── Task                          ── stateful unit of work (server-owned id)
        │
        ├── status        TaskStatus { state, message?, timestamp? }
        │
        ├── history ──▶ Message      ── one conversational turn (ROLE_USER/ROLE_AGENT)
        │                  │
        │                  └── parts ──▶ Part   ── text | raw/url file | data
        │
        └── artifacts ──▶ Artifact   ── a tangible deliverable
                             │
                             └── parts ──▶ Part ── text | raw/url file | data
```

Read it as two sentences:

- **Task → Message → Part** — the *conversation* path: what was said, turn by turn.
- **Task → Artifact → Part** — the *output* path: what was produced.

> **Key insight**: Learn `Part` well. Every payload a client sends or a server returns — questions, files, structured parameters, finished results — is ultimately a list of Parts inside a Message or an Artifact.

---

## 🔟 Summary Table

| Concept        | What it is | Key fields | Lifetime |
|----------------|-----------|------------|----------|
| **A2A Server** | The remote agent being called; hosts the endpoint and Agent Card. | — (a role) | — |
| **A2A Client** | The calling agent/app; discovers and invokes a server. | — (a role) | — |
| **Agent Card** | JSON discovery document describing a server. | `name`, `supportedInterfaces`, `capabilities`, `securitySchemes`, `securityRequirements`, `skills` | Published, stable |
| **AgentSkill** | One advertised capability inside the card. | `id`, `name`, `description`, `tags`, `examples`, `inputModes`, `outputModes` | Stable |
| **Task**       | Stateful, server-owned unit of work. | `id`, `contextId`, `status`, `history`, `artifacts`, `metadata` | Long-lived, resumable |
| **Message**    | One conversational turn. | `messageId`, `role`, `parts`, `contextId`, `taskId` | Ephemeral |
| **Part**       | Smallest content unit; kind by field presence. | `text` / `raw`+`url` / `data`, `mediaType`, `filename` | Inside a Message/Artifact |
| **Artifact**   | A tangible Task output. | `artifactId`, `name`, `description`, `parts`, `metadata` | Durable on the Task |
| **contextId**  | Identifier grouping Tasks/Messages into one conversation. | (a string, e.g. UUID) | Spans the whole session |

> **Key insight**: Three nouns carry all the data — **Message** (talk), **Artifact** (output), **Part** (content). Two nouns carry identity and scope — **Task** (`id`) and **contextId** (conversation). Everything else in A2A is built on these.

---

**Next**: [Part 3: A2A vs MCP](03_a2a_vs_mcp.md)
