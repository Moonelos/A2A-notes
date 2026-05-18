# A2A Transport & RPC Methods

> **Who this is for**: Engineers implementing the A2A (Agent2Agent) protocol directly — building a server, writing a client, or wanting to know exactly what an A2A SDK does on the wire. Targets spec **v1.0.0**.

Before reading this, understand how an agent advertises itself: **[The Agent Card](01_agent_card.md)**.

---

## 1. The three first-class transport bindings

A2A defines a set of **abstract operations** (send a message, get a task, cancel a task...) and then maps them onto concrete **transport bindings**. The operations are identical across bindings; only the wire encoding changes.

The spec mandates three first-class bindings. An A2A agent MUST implement **at least one**:

| Binding | Encoding | Streaming mechanism | Typical use |
|---|---|---|---|
| **JSON-RPC 2.0 over HTTP(S)** | JSON-RPC 2.0 envelope, single POST endpoint | Server-Sent Events (SSE) | Default / most common; what most SDKs use |
| **gRPC** | Protocol Buffers over HTTP/2 | gRPC server streaming | High-throughput, polyglot, strongly-typed services |
| **HTTP+JSON / REST** | Plain JSON over RESTful verbs + resource paths | SSE | Teams standardized on REST; easy to debug with `curl` |

```
                 ┌──────────────────────────────┐
                 │   Abstract A2A operations     │
                 │  SendMessage / GetTask / ...  │
                 └───────────────┬──────────────-┘
                                 │  (functional equivalence required)
            ┌────────────────────┼────────────────────┐
            ▼                    ▼                    ▼
     ┌────────────┐       ┌────────────┐       ┌────────────┐
     │ JSON-RPC   │       │   gRPC     │       │ HTTP+JSON  │
     │ 2.0 / HTTP │       │  / HTTP2   │       │  / REST    │
     └────────────┘       └────────────┘       └────────────┘
```

An agent declares its transports in the **Agent Card** with an ordered `supportedInterfaces` list. The first supported interface is the server's preference:

```json
{
  "name": "Recipe Agent",
  "supportedInterfaces": [
    {
      "url": "https://recipes.example.com/a2a/v1",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    },
    {
      "url": "https://grpc.recipes.example.com",
      "protocolBinding": "GRPC",
      "protocolVersion": "1.0"
    },
    {
      "url": "https://recipes.example.com/a2a/rest/v1",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0"
    }
  ]
}
```

> **Rule**: An agent that exposes multiple transports MUST provide **functional equivalence** across all of them — every operation must behave identically regardless of which binding the client picks. A client may choose any advertised transport it supports, though it should prefer earlier `supportedInterfaces` entries unless it has a reason not to.

The rest of this note focuses on the **JSON-RPC 2.0 binding**, since it is the default and the one most SDKs implement first. The method *semantics* carry over to gRPC and REST unchanged.

---

## 2. The RPC method set

In the JSON-RPC binding, every operation is invoked by a `method` string. These are the v1.0.0 methods:

| Method | Purpose | Returns |
|---|---|---|
| `SendMessage` | Send a message to an agent; start or continue a task | `SendMessageResponse` containing `task` or `message` |
| `SendStreamingMessage` | Same as `SendMessage`, but stream incremental updates over SSE | Stream of `StreamResponse` objects |
| `GetTask` | Fetch the current state of a task by ID | `Task` |
| `ListTasks` | Query multiple tasks with filtering / pagination | `ListTasksResponse` |
| `CancelTask` | Request cancellation of a running task | `Task` (updated status) |
| `SubscribeToTask` | Re-attach an SSE stream to an existing non-terminal task | Stream of `StreamResponse` objects |
| `CreateTaskPushNotificationConfig` | Register a webhook config for task updates | `TaskPushNotificationConfig` |
| `GetTaskPushNotificationConfig` | Retrieve a stored push-notification config | `TaskPushNotificationConfig` |
| `ListTaskPushNotificationConfigs` | List all push-notification configs for a task | `ListTaskPushNotificationConfigsResponse` |
| `DeleteTaskPushNotificationConfig` | Remove a push-notification config | empty success result |
| `GetExtendedAgentCard` | Fetch the authenticated, possibly extended Agent Card | `AgentCard` |

> **Key insight**: `SendMessage` and `SendStreamingMessage` are the *only* JSON-RPC methods that create or continue work. `GetTask`, `ListTasks`, `CancelTask`, and `SubscribeToTask` operate on tasks that already exist. The push-notification config methods are a small CRUD surface for webhooks — covered in **[Streaming & Push](04_streaming_and_push.md)**.

In gRPC these become RPCs like `SendMessage` / `GetTask`; in HTTP+JSON they become `POST /v1/message:send`, `GET /v1/tasks/{id}`, etc. The names differ, the behavior does not.

---

## 3. A complete JSON-RPC request/response pair

A `SendMessage` call carries a `SendMessageRequest` object. The `message` field is a `Message`, and a `Message` carries an ordered array of unified **`Part`s** (`text`, `raw`, `url`, or `data`).

**Request** — client → agent:

```json
{
  "jsonrpc": "2.0",
  "id": "req-7f3a1c",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-001",
      "role": "ROLE_USER",
      "parts": [
        {
          "text": "Convert 2 cups of flour to grams."
        }
      ]
    },
    "configuration": {
      "acceptedOutputModes": ["text/plain"],
      "returnImmediately": false
    }
  }
}
```

**Response** — agent → client. The `result` is a `Task`:

```json
{
  "jsonrpc": "2.0",
  "id": "req-7f3a1c",
  "result": {
    "task": {
      "id": "task-9d2e44",
      "contextId": "ctx-5510ab",
      "status": {
        "state": "TASK_STATE_COMPLETED",
        "timestamp": "2026-05-18T14:03:21Z"
      },
      "history": [
        {
          "messageId": "msg-001",
          "role": "ROLE_USER",
          "parts": [{ "text": "Convert 2 cups of flour to grams." }]
        }
      ],
      "artifacts": [
        {
          "artifactId": "art-001",
          "name": "conversion",
          "parts": [{ "text": "2 cups of all-purpose flour is about 240 grams." }]
        }
      ]
    }
  }
}
```

Notes on the shape:

- The JSON-RPC `id` is echoed back so the client can correlate the response. It is unrelated to the `task.id`.
- The agent assigns `task.id` and `task.contextId` — the client does **not** supply them on the first call. To continue an existing task, the client passes `taskId` and reuses `contextId` inside the next `Message`.
- `configuration.returnImmediately: false` is the default blocking behavior: the operation waits until the task reaches a terminal or interrupted state. With `returnImmediately: true`, the agent returns the initial task quickly and the client polls with `GetTask`, subscribes with `SubscribeToTask`, or receives push updates. See **[Part 3: Task Lifecycle](03_task_lifecycle.md)**.
- ⚠️ A `SendMessageResponse` contains **exactly one** of `task` or `message`. Clients MUST branch on which oneof field is present; there is no `kind` discriminator in v1.0.

---

## 4. The HTTP layer

For the JSON-RPC binding, every method call is a single HTTP request:

```
POST /a2a/v1 HTTP/1.1
Host: recipes.example.com
Content-Type: application/json
Accept: application/json
Authorization: Bearer <token>

{ "jsonrpc": "2.0", "id": "req-7f3a1c", "method": "SendMessage", "params": { ... } }
```

- **Method & URL**: always `POST` to the agent's `url` from the Agent Card. There is one endpoint; the JSON-RPC `method` field selects the operation — not the path.
- **`Content-Type`**: requests and non-streaming responses use `application/json`. `SendStreamingMessage` and `SubscribeToTask` responses use `text/event-stream` (SSE).
- **Auth**: transport-level — typically an `Authorization` header. A2A does not put credentials in the JSON-RPC body.

> **Rule**: For the JSON-RPC binding, a successful call returns **HTTP 200** even when the *application* outcome is an error. JSON-RPC errors live in the response body, not the status line.

That gives two distinct error channels — know which one you are reading:

| Layer | Signals | Examples |
|---|---|---|
| **HTTP status** | Transport / infrastructure failures *before* JSON-RPC processing | `401` bad auth, `404` wrong URL, `415` non-JSON body, `429` rate limited, `503` agent down |
| **JSON-RPC `error` object** | Application-level failures *during* method handling | Malformed request, unknown method, task not found, task not cancelable |

A well-behaved client checks the HTTP status first; on `200` it then inspects the body for an `error` member. (gRPC and HTTP+JSON bindings differ here — they map A2A errors onto native status codes — but the JSON-RPC binding deliberately keeps the HTTP layer "thin".)

---

## 5. Error codes

A JSON-RPC error response replaces `result` with an `error` object:

```json
{
  "jsonrpc": "2.0",
  "id": "req-7f3a1c",
  "error": {
    "code": -32001,
    "message": "Task not found",
    "data": [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "TASK_NOT_FOUND",
        "domain": "a2a-protocol.org",
        "metadata": { "taskId": "task-bad-id" }
      }
    ]
  }
}
```

**Standard JSON-RPC 2.0 errors** — generic protocol-level failures:

| Code | Name | Meaning |
|---|---|---|
| `-32700` | Parse error | Request body is not valid JSON |
| `-32600` | Invalid Request | Valid JSON, but not a valid JSON-RPC request object |
| `-32601` | Method not found | The `method` string is unknown to this agent |
| `-32602` | Invalid params | `params` are missing, malformed, or fail validation |
| `-32603` | Internal error | Unhandled server-side error |

**A2A-specific errors** — defined in the JSON-RPC server-error range (`-32000` to `-32099`):

| Code | Name | Meaning |
|---|---|---|
| `-32001` | `TaskNotFoundError` | The given task ID does not exist, has expired, or is not accessible |
| `-32002` | `TaskNotCancelableError` | `CancelTask` called on a task already in a terminal state |
| `-32003` | `PushNotificationNotSupportedError` | A push-notification config call hit an agent whose card declares no push-notification capability |
| `-32004` | `UnsupportedOperationError` | The requested operation is valid but not implemented by this agent (e.g. `SendStreamingMessage` on a non-streaming agent) |
| `-32005` | `ContentTypeNotSupportedError` | A `Part`'s media type is not accepted by the agent |
| `-32006` | `InvalidAgentResponseError` | The agent produced a response that violates the A2A spec (surfaced by clients / intermediaries) |

In v1.0.0 the JSON-RPC and HTTP+JSON bindings additionally embed a `google.rpc.ErrorInfo` object inside `error.data` — with `reason` (the UPPER_SNAKE_CASE error name, e.g. `TASK_NOT_FOUND`) and `domain: "a2a-protocol.org"` — so machine error-matching does not depend on the numeric code alone:

```json
{
  "code": -32002,
  "message": "Task is not in a cancelable state",
  "data": [
    {
      "@type": "type.googleapis.com/google.rpc.ErrorInfo",
      "reason": "TASK_NOT_CANCELABLE",
      "domain": "a2a-protocol.org",
      "metadata": { "taskId": "task-9d2e44", "state": "TASK_STATE_COMPLETED" }
    }
  ]
}
```

💡 When implementing a server: map your internal exceptions to these codes consistently, and **always populate `error.data`** with enough context (`taskId`, `state`, accepted content types) for the client to act without a second round trip.

> **Key insight**: Numeric codes are stable across A2A versions, but the `ErrorInfo.reason` string is the canonical identity in v1.0.0. Match on `reason` + `domain` for forward compatibility; treat the numeric `code` as a coarse category.

---

**Next**: [Part 3: Task Lifecycle](03_task_lifecycle.md)
