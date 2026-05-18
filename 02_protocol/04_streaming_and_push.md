# Streaming and Push Notifications

> **Who this is for**: Engineers building A2A clients or servers that must deliver results from long-running agent tasks over unreliable connectivity — serverless functions, mobile clients, and tasks measured in hours. Before reading this, understand how a task moves through its states: **[Task Lifecycle](03_task_lifecycle.md)**.

A synchronous `SendMessage` works only when the agent finishes before the HTTP request times out. Real agent work — research, code generation, multi-tool orchestration — does not respect that budget. A2A spec v1.0.0 defines two mechanisms for delivering results that take time: **SSE streaming** for connected clients, and **push notifications** for disconnected ones.

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

If `capabilities.streaming` is `false` or absent, the agent rejects `SendStreamingMessage` and `SubscribeToTask` with an `UnsupportedOperationError`. The client must fall back to synchronous `SendMessage` plus polling, or to push notifications if `pushNotifications` is supported.

> **Rule**: Never hardcode the assumption that an agent streams. Capability discovery happens per-agent, at the Agent Card, before the first request.

---

## 4. Push Notifications and Webhooks

SSE assumes the client can hold a connection open for the entire task. That assumption fails for:

- **Serverless clients** — a Lambda or Cloud Function is billed per-millisecond and killed after minutes; it cannot babysit an hours-long SSE stream.
- **Mobile clients** — the OS suspends background sockets aggressively; the connection dies the moment the app backgrounds.
- **Very-long-running tasks** — a task that takes six hours has no business pinning a TCP connection for six hours on either side.

For these, A2A inverts the flow: the client registers a **webhook**, disconnects entirely, and the agent **POSTs task updates to that URL** when they happen. The client wakes only on real progress.

The webhook is registered with `CreateTaskPushNotificationConfig`:

```json
{
  "taskId": "t-9f3",
  "url": "https://client.example.com/a2a/webhook",
  "token": "9b1d4c0e-task-t9f3-secret",
  "authentication": {
    "scheme": "Bearer",
    "credentials": "eyJhbGciOiJSUzI1Ni..."
  }
}
```

- **`url`** — the HTTPS endpoint the agent POSTs to. MUST be HTTPS.
- **`token`** — an opaque client-generated secret. The agent echoes it back in every notification so the client can confirm the call is tied to a config it created.
- **`authentication`** — how the *agent* proves its identity to the webhook (scheme + credentials). The receiving client validates this.

The POST body is the same `StreamResponse` shape as an SSE event — a JSON object with one of `task`, `message`, `statusUpdate`, or `artifactUpdate`. Configs can also be retrieved, listed, and deleted. Push notifications are gated by `capabilities.pushNotifications` in the Agent Card, exactly as SSE is gated by `capabilities.streaming`.

> **Key insight**: SSE is *pull-shaped* (client holds the channel). Push is *event-shaped* (agent initiates contact). Choose by asking "can my client realistically stay connected for the whole task?" — not by which feels more modern.

---

## 5. Securing the Webhook

A webhook URL is a publicly reachable endpoint that accepts POSTs and acts on them. Both sides must harden it.

**The receiving client MUST validate every notification:**

- ⚠️ **Verify the `token`.** Reject any POST whose token does not match a config you created. Without this, anyone who learns the URL can forge "task completed" calls.
- ⚠️ **Enforce the declared `authentication` scheme.** If you registered `Bearer` with a JWT, verify the JWT signature against the agent's trusted public keys (JWKS), check `exp`/`iat` for staleness, and confirm `aud`/`iss`. A bare token check is not enough — the transport-level auth proves *who* is calling.
- ⚠️ **Treat the body as untrusted input.** The `taskId` and artifact contents could be attacker-controlled. Look up the task in your own store; never act on a `taskId` you do not recognize.

**The agent MUST protect against SSRF when POSTing:**

- ⚠️ An agent that blindly POSTs to any client-supplied `url` is an SSRF gadget. A malicious client could register `http://169.254.169.254/...` (cloud metadata) or `http://10.0.0.5/internal`. The agent MUST reject non-HTTPS URLs, resolve the hostname and block private / link-local / loopback IP ranges, and ideally require the webhook host to be pre-allowlisted.
- The agent MUST authenticate *to* the webhook using the `authentication` config — sign a JWT or present the agreed credential — so the receiver can distinguish a real notification from a forged one.

For the full SSRF defense checklist (DNS-rebinding, IP-range blocklists, egress proxies), see [Security Hardening](../05_production/02_security_hardening.md).

> **Rule**: A webhook with no token check and no transport auth is an open RPC endpoint for the internet. Validate both, on every request, before reading the body.

---

## 6. Choosing a Delivery Mechanism

| Dimension              | `SendMessage` (sync) | `SendStreamingMessage` (SSE)   | Push notifications            |
|------------------------|-----------------------|-------------------------------|-------------------------------|
| Latency to first byte  | Full task duration    | Immediate, incremental        | Per-event, agent-initiated    |
| Client stays connected | Yes, briefly          | Yes, for the whole task       | No — disconnects entirely     |
| Best task length       | Seconds               | Seconds to minutes            | Minutes to hours              |
| Client type            | Any                   | Long-lived process, browser   | Serverless, mobile, batch     |
| Incremental output     | No                    | Yes (chunked artifacts)       | Yes (per POST)                |
| Infrastructure needed  | None                  | None                          | Public HTTPS endpoint         |
| Capability flag        | (always available)    | `capabilities.streaming`      | `capabilities.pushNotifications` |
| Recovery on drop       | Retry carefully with same `messageId` | `SubscribeToTask`     | Agent retries the POST        |

Decision shortcut:

- **Sub-second to a few seconds, simple request/reply** → `SendMessage`.
- **Want progressive output and the client can hold a connection** → `SendStreamingMessage`.
- **Client cannot stay connected, or the task runs for many minutes/hours** → push notifications.
- **Can't hold a connection but the agent has no `pushNotifications`** → `SendMessage` then poll `GetTask` with backoff.

> **Key insight**: These are not mutually exclusive per agent — they are per *interaction*. A single agent commonly supports all three; the client picks based on the task and its own runtime constraints.

---

## 7. Failure Modes

| Failure                        | Symptom                                   | Mitigation |
|--------------------------------|-------------------------------------------|------------|
| SSE connection drops mid-task  | Stream ends before a terminal/interrupted state | `SubscribeToTask` with backoff; `GetTask` to backfill missed artifacts |
| Webhook endpoint down          | Agent's POST fails or times out           | Agent retries with exponential backoff; client polls `GetTask` as a safety net; treat the config as best-effort delivery |
| Duplicate notifications        | Same event POSTed more than once          | Make webhook handling **idempotent** — dedupe on `taskId` + event identity (JWT `jti` if signed); a redelivered "completed" must be a no-op |
| Out-of-order notifications     | `TASK_STATE_WORKING` arrives after `TASK_STATE_COMPLETED` | Trust task **state**, not arrival order — never regress a task from a terminal state; use timestamps in `TaskStatus` to discard stale events |
| Stale / replayed notification  | Old captured POST replayed by an attacker | Reject notifications past a freshness window (`iat` check); track seen `jti` values |
| Stream never closes after no events | Agent crashed or stream silently stalled  | Client-side timeout bounded by the task's expected max duration, then `GetTask` to read the authoritative state |

⚠️ The recurring theme: **the task object on the server is the source of truth**. SSE events and webhook POSTs are *delivery optimizations* over that state. When delivery is uncertain — a drop, a duplicate, a reorder — fall back to `GetTask` and reconcile. Never let your client's view of a task diverge from the server's.

> **Rule**: Design every notification handler to be idempotent and ordering-tolerant. Networks reorder, retry, and replay; a correct client assumes all three will happen.

---

**Next**: [Part 1: SDK Setup](../03_python/01_sdk_setup.md)
