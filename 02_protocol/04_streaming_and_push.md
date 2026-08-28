# Streaming and Push Notifications

> **Who this is for**: Engineers building A2A clients or servers that must deliver results from long-running agent tasks over unreliable connectivity — serverless functions, mobile clients, and tasks measured in hours. Before reading this, understand how a task moves through its states: **[Task Lifecycle](03_task_lifecycle.md)**.

A synchronous `SendMessage` works only when the agent finishes before the HTTP request times out. Real agent work — research, code generation, multi-tool orchestration — does not respect that budget. A2A protocol **1.0** (checked against specification release **1.0.1**) defines **Server-Sent Events (SSE)** streaming for connected clients and push notifications for disconnected clients.

---

## 1. SSE Streaming with `SendStreamingMessage`

`SendStreamingMessage` initiates or continues a task and keeps the HTTP response open as a `text/event-stream`. Instead of one final JSON-RPC response, the server emits a sequence of Server-Sent Events, each carrying a JSON-RPC 2.0 success response whose `result` is a `StreamResponse` with exactly one oneof field:

| `StreamResponse` field | Type                      | Meaning |
|------------------------|---------------------------|---------|
| `task`                 | `Task`                    | Initial snapshot of the created task |
| `message`              | `Message`                 | A direct agent reply; stream then closes |
| `statusUpdate`         | `TaskStatusUpdateEvent`   | Lifecycle change (`SUBMITTED` → `WORKING` → `COMPLETED`) |
| `artifactUpdate`       | `TaskArtifactUpdateEvent` | A produced artifact, possibly chunked |

Each streaming response object MUST contain exactly one of these. The stream follows one of two patterns:

```
Message-only:   message → [stream closes]
Task lifecycle: task → statusUpdate* → artifactUpdate* → terminal/interrupted statusUpdate → [stream closes]
```

Two pieces drive client logic:

- **Task state** — v1.0 removed the old `final` flag. The stream ends when the task reaches a terminal state (`TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED`, `TASK_STATE_REJECTED`) or when the server intentionally pauses/returns control at an interrupted state.
- **`TaskArtifactUpdateEvent.append`** and **`lastChunk`** — let the agent stream a large artifact in pieces. `append: false` (or absent) starts a fresh artifact; `append: true` concatenates onto the artifact with the same `artifactId`. `lastChunk: true` marks the final segment of that artifact.

Example SSE stream (a code-generation task that streams its output file in two chunks):

```
event: message
data: {"jsonrpc":"2.0","id":"req-1","result":{"task":{"id":"t-9f3","contextId":"c-1","status":{"state":"TASK_STATE_SUBMITTED"}}}}

data: {"jsonrpc":"2.0","id":"req-1","result":{"statusUpdate":{"taskId":"t-9f3","contextId":"c-1","status":{"state":"TASK_STATE_WORKING"}}}}

data: {"jsonrpc":"2.0","id":"req-1","result":{"artifactUpdate":{"taskId":"t-9f3","contextId":"c-1","artifact":{"artifactId":"a-1","name":"main.py","parts":[{"text":"import os\n\ndef main():\n"}]},"append":false,"lastChunk":false}}}

data: {"jsonrpc":"2.0","id":"req-1","result":{"artifactUpdate":{"taskId":"t-9f3","contextId":"c-1","artifact":{"artifactId":"a-1","parts":[{"text":"    print('done')\n"}]},"append":true,"lastChunk":true}}}

data: {"jsonrpc":"2.0","id":"req-1","result":{"statusUpdate":{"taskId":"t-9f3","contextId":"c-1","status":{"state":"TASK_STATE_COMPLETED"}}}}
```

> **Rule**: A client MUST keep reading until the stream closes after a terminal/interrupted state, or until it sees the corresponding final task state via polling. Treating an early `TASK_STATE_WORKING` event as completion drops the actual result.

---

## 2. Resubscribing with `SubscribeToTask`

An SSE connection is a live TCP stream. It breaks for ordinary reasons — load balancer idle timeouts, mobile network handoffs, laptop sleep. The task itself keeps running on the server; only the *delivery channel* is lost.

`SubscribeToTask` re-attaches an SSE stream to an existing non-terminal task by `id`. The server returns the current task state first, then resumes emitting `statusUpdate` / `artifactUpdate` events until the stream ends.

```
1. SendStreamingMessage  → task t-9f3, events flowing
2. [connection drops mid-task]
3. SubscribeToTask { "id": "t-9f3" }  → new text/event-stream
4. server sends current task snapshot, then resumes updates
```

> **Rule**: Build resubscribe into the client from day one. Treat SSE drops as expected, not exceptional — retry with backoff, capped at the task's known max duration.

⚠️ Subscribe gives you a fresh task snapshot plus future events. If the agent emitted artifact chunks while you were disconnected and they were not persisted into the `Task`, you may miss them. For artifacts that must survive a reconnect, fetch the full task with `GetTask` after subscribing rather than relying on replayed deltas alone.

---

## 3. The `capabilities.streaming` Flag

SSE is optional. A client MUST check the Agent Card before calling `SendStreamingMessage`:

```json
{
  "name": "research-agent",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true
  }
}
```

If `capabilities.streaming` is `false` or absent, the agent rejects `SendStreamingMessage` and `SubscribeToTask` with an `UnsupportedOperationError`. To poll work while it runs, call `SendMessage` with `configuration.returnImmediately: true`; the initial response is typically a `Task` in `TASK_STATE_SUBMITTED` or `TASK_STATE_WORKING`, which the client then reads with `GetTask`. The default blocking call may not return until a terminal or interrupted state, leaving no in-progress result to poll.

> **Rule**: Never hardcode the assumption that an agent streams. Capability discovery happens per-agent, at the Agent Card, before the first request.

---

## 4. Push Notifications and Webhooks

SSE assumes the client can hold a connection open for the entire task. That assumption fails for:

- **Serverless clients** — a Lambda or Cloud Function is billed per-millisecond and killed after minutes; it cannot babysit an hours-long SSE stream.
- **Mobile apps** — the OS suspends background sockets aggressively. The public webhook belongs on your backend; that backend validates the A2A push and forwards a notification through APNs, FCM, or another mobile push channel.
- **Very-long-running tasks** — a task that takes six hours has no business pinning a TCP connection for six hours on either side.

For these, A2A inverts the flow: the client registers a **webhook**, disconnects entirely, and the agent **POSTs task updates to that URL** when they happen. The client wakes only on real progress.

This HTTP+JSON example creates a config for an existing Task. Credentials shown as angle-bracket placeholders come from a secret manager at runtime; they never belong in source or logs.

```http
POST /tasks/t-9f3/pushNotificationConfigs HTTP/1.1
Host: agent.example.com
Content-Type: application/a2a+json
A2A-Version: 1.0
Authorization: Bearer <a2a-client-token>

{
  "url": "https://client.example.com/a2a/webhook",
  "authentication": {
    "scheme": "Bearer",
    "credentials": "<webhook-bearer-secret>"
  }
}
```

Success is `200 OK` with an assigned config ID:

```json
{
  "id": "push-42",
  "taskId": "t-9f3",
  "url": "https://client.example.com/a2a/webhook",
  "authentication": { "scheme": "Bearer" }
}
```

- **`url`** — the HTTPS endpoint the agent POSTs to.
- **`authentication`** — how the agent authenticates each outbound HTTP request. The receiving backend validates this header before parsing the body.

The first callback might be:

```http
POST /a2a/webhook HTTP/1.1
Host: client.example.com
Authorization: Bearer <webhook-bearer-secret>
Content-Type: application/a2a+json

{"statusUpdate":{"taskId":"t-9f3","contextId":"c-1","status":{"state":"TASK_STATE_WORKING"}}}
```

The receiver validates the header and expected `taskId`, persists the update idempotently, and returns `204 No Content`. A `401`/`403` at the callback means authentication failed; connection/DNS errors mean the endpoint is not publicly reachable; `PushNotificationNotSupportedError` means the card capability was absent; `TaskNotFoundError` means the config was attached to an inaccessible or unknown Task.

The POST body is exactly one `StreamResponse` — `task`, `message`, `statusUpdate`, or `artifactUpdate`. It does not echo the config's legacy `token` field. Configs can also be retrieved, listed, and deleted, and all operations are gated by `capabilities.pushNotifications`.

SSE is connection-shaped: the client holds the channel. Push is event-shaped: the agent initiates a new authenticated HTTP request for each update.

---

## 5. Securing the Webhook

A webhook URL is a publicly reachable endpoint that accepts POSTs and acts on them. Both sides must harden it.

**The receiving client MUST validate every notification:**

- ⚠️ **Enforce the configured HTTP authentication.** For an opaque bearer secret, compare it in constant time. For a JSON Web Token (JWT), configure trusted issuers and JSON Web Key Set (JWKS) URLs, allowlist the signing algorithm instead of accepting `alg` from the token, then verify signature, `exp`, `iat`, `aud`, `iss`, and subject as required. The callback body contains no echoed config token.
- ⚠️ **Treat the body as untrusted input.** The `taskId` and artifact contents could be attacker-controlled. Look up the task in your own store; never act on a `taskId` you do not recognize.

**The agent MUST protect against SSRF when POSTing:**

- ⚠️ An agent that blindly POSTs to any client-supplied `url` is an SSRF gadget. A malicious client could register `http://169.254.169.254/...` (cloud metadata) or `http://10.0.0.5/internal`. The agent MUST reject non-HTTPS URLs, resolve the hostname and block private / link-local / loopback IP ranges, and ideally require the webhook host to be pre-allowlisted.
- The agent MUST authenticate *to* the webhook using the `authentication` config — sign a JWT or present the agreed credential — so the receiver can distinguish a real notification from a forged one.

For the full SSRF defense checklist (DNS-rebinding, IP-range blocklists, egress proxies), see [Security Hardening](../05_production/02_security_hardening.md).

> **Rule**: A webhook without authenticated HTTP delivery is an open input endpoint. Validate the configured authentication and expected Task ownership on every request before acting on the body.

---

## 6. Choosing a Delivery Mechanism

| Dimension              | `SendMessage` (sync) | `SendStreamingMessage` (SSE)   | Push notifications            |
|------------------------|-----------------------|-------------------------------|-------------------------------|
| Latency to first byte  | Full task duration    | Immediate, incremental        | Per-event, agent-initiated    |
| Client stays connected | Yes, briefly          | Yes, for the whole task       | No — disconnects entirely     |
| Best task length       | Seconds               | Seconds to minutes            | Minutes to hours              |
| Client type            | Any                   | Long-lived process, browser   | Public backend, serverless, batch |
| Incremental output     | No                    | Yes (chunked artifacts)       | Yes (per POST)                |
| Infrastructure needed  | None                  | None                          | Public HTTPS endpoint         |
| Capability flag        | (always available)    | `capabilities.streaming`      | `capabilities.pushNotifications` |
| Recovery on drop       | Retry only under a known deduplication contract | `SubscribeToTask` | `GetTask` reconciliation; agent retries are optional |

Decision shortcut:

- **Sub-second to a few seconds, simple request/reply** → `SendMessage`.
- **Want progressive output and the client can hold a connection** → `SendStreamingMessage`.
- **Client cannot stay connected, or the task runs for many minutes/hours** → push notifications.
- **Can't hold a connection but the agent has no `pushNotifications`** → `SendMessage` then poll `GetTask` with backoff.

> **Key insight**: Delivery mechanisms do not change the authoritative state. Choose sync, stream, push, or polling for reachability and latency, then reconcile uncertainty against `GetTask`.

---

## 7. Failure Modes

| Failure                        | Symptom                                   | Mitigation |
|--------------------------------|-------------------------------------------|------------|
| SSE connection drops mid-task  | Stream ends before a terminal/interrupted state | `SubscribeToTask` with backoff; `GetTask` to backfill missed artifacts |
| Webhook endpoint down          | Agent's POST fails or times out           | Retry policy is implementation-defined; client polls `GetTask` as the reliable reconciliation path |
| Duplicate notifications        | Same event POSTed more than once          | Make webhook handling **idempotent** — dedupe on `taskId` + event identity (JWT `jti` if signed); a redelivered "completed" must be a no-op |
| Out-of-order notifications     | `TASK_STATE_WORKING` arrives after `TASK_STATE_COMPLETED` | Trust task **state**, not arrival order — never regress a task from a terminal state; use timestamps in `TaskStatus` to discard stale events |
| Stale / replayed notification  | Old captured POST replayed by an attacker | Reject notifications past a freshness window (`iat` check); track seen `jti` values |
| Stream never closes after no events | Agent crashed or stream silently stalled  | Client-side timeout bounded by the task's expected max duration, then `GetTask` to read the authoritative state |

⚠️ The server guarantees at least one delivery attempt per configured webhook, not a retry schedule. It may retry with backoff and may stop after repeated failures. When delivery is uncertain — a drop, duplicate, reorder, or exhausted retry policy — fall back to `GetTask` and reconcile.

> **Rule**: Design every notification handler to be idempotent and ordering-tolerant. Networks reorder, retry, and replay; a correct client assumes all three will happen.

---

**Next**: [Part 1: SDK Setup](../03_python/01_sdk_setup.md)
