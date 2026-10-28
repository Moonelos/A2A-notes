# A2A Transport & RPC Methods

> **Who this is for**: Engineers implementing the A2A (Agent2Agent) protocol directly — building a server, writing a client, or wanting to know exactly what an A2A SDK does on the wire. Targets protocol **1.0**, checked against specification release **1.0.1**.

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

In the JSON-RPC binding, every operation is invoked by a `method` string. These are the protocol 1.0 methods:

| Method | Purpose | Returns |
|---|---|---|
| `SendMessage` | Send a message to an agent; start or continue a task | `SendMessageResponse` containing `task` or `message` |
| `SendStreamingMessage` | Same as `SendMessage`, but stream incremental updates over SSE | Stream of `StreamResponse` objects |
| `GetTask` | Fetch the current state of a task by ID | `Task` |
| `ListTasks` | Query multiple tasks with filtering / pagination | `ListTasksResponse` |
| `CancelTask` | Request cancellation of a running task | `Task` (updated status) |
| `SubscribeToTask` | Attach or re-attach an SSE stream to an existing non-terminal task | Stream of `StreamResponse` objects |
| `CreateTaskPushNotificationConfig` | Register a webhook config for task updates | `TaskPushNotificationConfig` |
| `GetTaskPushNotificationConfig` | Retrieve a stored push-notification config | `TaskPushNotificationConfig` |
| `ListTaskPushNotificationConfigs` | List all push-notification configs for a task | `ListTaskPushNotificationConfigsResponse` |
| `DeleteTaskPushNotificationConfig` | Remove a push-notification config | empty success result |
| `GetExtendedAgentCard` | Fetch the authenticated, possibly extended Agent Card | `AgentCard` |

> **Key insight**: `SendMessage` and `SendStreamingMessage` are the *only* JSON-RPC methods that create or continue work. `GetTask`, `ListTasks`, `CancelTask`, and `SubscribeToTask` operate on tasks that already exist. The push-notification config methods are a small CRUD surface for webhooks — covered in **[Streaming & Push](04_streaming_and_push.md)**.

In gRPC these become RPCs like `SendMessage` / `GetTask`; in HTTP+JSON they become `POST /message:send`, `GET /tasks/{id}`, `POST /tasks/{id}:cancel`, and the other resource paths defined by the binding. The removed `/v1/...` prefix belongs to pre-release material and returns `404` on a conforming v1 route map.

---

## 3. A complete JSON-RPC request/response pair

A `SendMessage` call carries a `SendMessageRequest` object. The `message` field is a `Message`, and a `Message` carries an ordered array of unified **`Part`s** (`text`, `raw`, `url`, or `data`).

**Request** — client → agent:

```json
{
  "jsonrpc": "2.0",
  "id": "req-report-001",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-001",
      "role": "ROLE_USER",
      "parts": [
        {
          "text": "Generate a sales report for October 2026."
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
  "id": "req-report-001",
  "result": {
    "task": {
      "id": "task-123",
      "contextId": "ctx-sales-001",
      "status": {
        "state": "TASK_STATE_COMPLETED",
        "timestamp": "2026-05-18T14:03:21Z"
      },
      "history": [
        {
          "messageId": "msg-001",
          "role": "ROLE_USER",
          "parts": [{ "text": "Generate a sales report for October 2026." }]
        }
      ],
      "artifacts": [
        {
          "artifactId": "art-001",
          "name": "summary",
          "parts": [{ "text": "October total sales: $150,000" }]
        }
      ]
    }
  }
}
```

Notes on the shape:

- The JSON-RPC `id` is echoed back so the client can correlate the response. It is unrelated to the `task.id`.
- The agent assigns `task.id`. A client may provide `contextId` on the first call; a server that accepts it preserves it, while a server that cannot accept it must reject the request rather than silently replace it. The conservative default is to omit it unless the client understands the server's context policy.
- `configuration.returnImmediately: false` is the default blocking behavior: the operation waits until the task reaches a terminal or interrupted state. With `returnImmediately: true`, the agent returns the initial task quickly and the client polls with `GetTask`, subscribes with `SubscribeToTask`, or receives push updates. See **[Part 3: Task Lifecycle](03_task_lifecycle.md)**.
- ⚠️ A `SendMessageResponse` contains **exactly one** of `task` or `message`. Clients MUST branch on which oneof field is present; there is no `kind` discriminator in v1.0.

---

### Direct reply, one Artifact, or multiple Artifacts

The completed Task above is one possible answer shape, even if the server finishes quickly. Execution duration does not determine the response type. A simple calculation can instead finish as a direct Message. Here is its complete exchange:

```json
{
  "jsonrpc": "2.0",
  "id": "req-math-001",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "msg-math-001",
      "role": "ROLE_USER",
      "parts": [{"text": "What is 2 + 2?"}]
    }
  }
}
```

```json
{
  "jsonrpc": "2.0",
  "id": "req-math-001",
  "result": {
    "message": {
      "messageId": "msg-math-002",
      "contextId": "ctx-math-001",
      "role": "ROLE_AGENT",
      "parts": [{"text": "2 + 2 = 4"}]
    }
  }
}
```

The client reads `result.message.parts`, saves `ctx-math-001` for another conversation turn, and has no Task to poll. Server Messages carry their context even when no Task exists.

If the report request also asks for a chart, a Task-producing server might return two Artifacts instead:

```json
{
  "jsonrpc": "2.0",
  "id": "req-report-001",
  "result": {
    "task": {
      "id": "task-123",
      "contextId": "ctx-sales-001",
      "status": {"state": "TASK_STATE_COMPLETED"},
      "artifacts": [
        {
          "artifactId": "art-summary",
          "name": "summary",
          "parts": [{"text": "Sales increased by 20%."}]
        },
        {
          "artifactId": "art-chart",
          "name": "chart",
          "parts": [{"url": "https://example.com/chart.png", "mediaType": "image/png"}]
        }
      ]
    }
  }
}
```

These responses illustrate alternative server behaviors; they are not three successive replies to one RPC. For a Task, inspect `status.state` before deciding the next action and render each returned Artifact's Parts. `INPUT_REQUIRED` means display the question and send a continuation; `COMPLETED` means successful work, with whatever outputs exist. Do not assume `[0]` is present or that `name` is unique. Output-specific routing needs an application agreement; protocol identity is `artifactId` within the Task.

For ongoing work, the client sends `configuration.returnImmediately: true`, saves the returned Task ID, then chooses polling, subscription or push. The [complete nonblocking/subscription exchange](04_streaming_and_push.md#2-subscribing-to-existing-work) covers that fourth response case. The [report clarification exchange](03_task_lifecycle.md#one-report-through-a-pause-and-completion) shows a Task waiting for input.

The [protocol response definitions](https://github.com/a2aproject/A2A/blob/v1.0.1/specification/a2a.proto) define the container shapes. Raw JSON clients first check the envelope for `error` or `result`; SDK clients receive typed results/events or exceptions. Neither should branch directly between a Message and an Artifact: a non-streaming success contains **Message or Task**, with Artifacts nested in the Task.

---

## 4. The HTTP layer

For the JSON-RPC binding, every method call is a single HTTP request:

```
POST /a2a/v1 HTTP/1.1
Host: recipes.example.com
Content-Type: application/json
Accept: application/json
Authorization: Bearer <token>
A2A-Version: 1.0

{ "jsonrpc": "2.0", "id": "req-report-001", "method": "SendMessage", "params": { ... } }
```

- **Method & URL**: always `POST` to the agent's `url` from the Agent Card. There is one endpoint; the JSON-RPC `method` field selects the operation — not the path.
- **`Content-Type`**: requests and non-streaming responses use `application/json`. `SendStreamingMessage` and `SubscribeToTask` responses use `text/event-stream` (SSE).
- **Auth**: transport-level — typically an `Authorization` header. A2A does not put credentials in the JSON-RPC body.
- **Protocol version**: every protocol 1.0 request carries `A2A-Version: 1.0` (or the equivalent service parameter for the binding). An empty header is interpreted as `0.3`; unsupported values map to `VersionNotSupportedError`.

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
  "id": "req-report-001",
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
| `-32007` | `ExtendedAgentCardNotConfiguredError` | `GetExtendedAgentCard` was called after support was declared but no extended card is configured |
| `-32008` | `ExtensionSupportRequiredError` | A required extension was not activated by the client |
| `-32009` | `VersionNotSupportedError` | The requested `A2A-Version` is not supported by the selected interface |

`error.data` is optional typed detail. Where applicable, a server can include a `google.rpc.ErrorInfo` object with `reason`, `domain`, and metadata:

```json
{
  "code": -32002,
  "message": "Task is not in a cancelable state",
  "data": [
    {
      "@type": "type.googleapis.com/google.rpc.ErrorInfo",
      "reason": "TASK_NOT_CANCELABLE",
      "domain": "a2a-protocol.org",
      "metadata": { "taskId": "task-123", "state": "TASK_STATE_COMPLETED" }
    }
  ]
}
```

💡 When implementing a server, map internal failures to binding-native codes consistently. Add typed detail when it helps the client act, but do not expose secrets or internal exception strings.

Clients branch first on the binding's native error code or type. Only inspect `reason` and `domain` when a typed `ErrorInfo` detail is actually present; do not make optional detail the sole error identity.

## Recap and check yourself

- The Agent Card advertises an interface; the selected binding maps the same abstract A2A operation to its own wire envelope.
- A successful HTTP exchange can still contain a JSON-RPC `error`; inspect both layers before using the result.
- A JSON-RPC response has one `result` or one `error`. The returned `result` itself has one A2A result variant.
- The client must retain the chosen interface and version across later Task operations.

**Q: The Recipe Agent returns HTTP 200 with JSON-RPC `error.code = -32001`. Did the HTTP exchange fail?**

<details><summary>Answer</summary>

The HTTP transport succeeded. The JSON-RPC method returned `TaskNotFoundError`, so the client should inspect the `error` object and check the task ID and access scope.

</details>

**Q: A client selected the HTTP+JSON interface but sends a JSON-RPC `method` envelope to its REST URL. What failed first?**

<details><summary>Answer</summary>

The client mixed bindings. The interface URL determines the path and body shape. Choosing an operation such as `SendMessage` does not make JSON-RPC syntax valid at an HTTP+JSON endpoint.

</details>

**Try it.** The Recipe Agent's card advertises both JSON-RPC and HTTP+JSON. Choose the HTTP+JSON binding for a flour conversion and sketch the request path and body. Hint: use the operation map above, then put the user Message in the REST body without a JSON-RPC `method` wrapper.

<details><summary>Worked solution</summary>

Send `POST /message:send` to the advertised HTTP+JSON URL with `A2A-Version: 1.0` and `Content-Type: application/a2a+json`. The JSON body contains the `message` and its `messageId`, role, and text Part. Inspect the HTTP status and the returned Message or Task; a JSON-RPC `id`, `method`, or `params` wrapper would target the wrong binding.

</details>

---

**Next**: [Part 3: Task Lifecycle](03_task_lifecycle.md)
