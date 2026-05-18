# The A2A Task Lifecycle

> **Who this is for**: Engineers modelling long-running agent work over A2A — anyone who needs to know when a job is *done*, when it's *waiting on you*, and when it's safe to stop polling. Before reading this, understand how A2A messages move on the wire: **[Transport & RPC](02_transport_and_rpc.md)**.

A **Task** is A2A's unit of stateful, potentially long-running work. Unlike a one-shot Message exchange, a Task has an identity (`id`), a lifecycle, and a status that evolves over time. This note covers the `TaskState` enum, the legal transitions between states, and the failure modes that bite clients who model the lifecycle wrong.

---

## 1. Message vs. Task: two shapes of a response

Not every A2A interaction produces a Task. When a client sends `SendMessage`, the agent decides what to return:

```
                       SendMessage
                           │
              ┌────────────┴────────────┐
              ▼                         ▼
   Quick, synchronous work     Long-running / multi-turn work
              │                         │
              ▼                         ▼
   Returns a Message            Returns a Task
   (final answer inline,        (has id, contextId, status;
    no id, no lifecycle)         client tracks it over time)
```

- A **Message** result is terminal by construction. There is nothing to poll, nothing to cancel. The agent answered and moved on.
- A **Task** result means the agent has accepted a job it will work on. It carries a `status.state` that the client must interpret, and an `id` the client uses for every follow-up call.

> **Rule**: The *agent* decides whether a request becomes a Task. A client cannot force one shape or the other — it must be prepared to handle either oneof field (`task` or `message`) in `SendMessageResponse`.

💡 A practical heuristic: if the agent might need more than one round trip, need to pause for input, or take longer than the request timeout, it will return a Task.

---

## 2. The `TaskState` enum

`TaskState` is the single field that tells a client what to do next. In the v1.0 ProtoJSON wire format the values are enum names:

| State            | Category        | Meaning                                                        |
|------------------|-----------------|----------------------------------------------------------------|
| `TASK_STATE_SUBMITTED`      | Active          | Task accepted, not yet started.                                |
| `TASK_STATE_WORKING`        | Active          | Agent is actively processing.                                  |
| `TASK_STATE_INPUT_REQUIRED` | Interrupted     | Agent paused; needs more input from the client to continue.    |
| `TASK_STATE_AUTH_REQUIRED`  | Interrupted     | Agent paused; needs credentials to continue.                   |
| `TASK_STATE_COMPLETED`      | **Terminal**    | Work finished successfully; artifacts (if any) are available.  |
| `TASK_STATE_FAILED`         | **Terminal**    | Work stopped due to an error; will not continue.               |
| `TASK_STATE_CANCELED`       | **Terminal**    | Work stopped because a client requested cancellation.          |
| `TASK_STATE_REJECTED`       | **Terminal**    | Agent declined the task outright (e.g. invalid request).       |
| `TASK_STATE_UNSPECIFIED`    | Indeterminate   | State could not be determined.                                 |

> **Rule**: Only `TASK_STATE_COMPLETED`, `TASK_STATE_FAILED`, `TASK_STATE_CANCELED`, and `TASK_STATE_REJECTED` are **terminal**. Once a Task reaches a terminal state it will never transition again — stop polling and release any tracking resources.

The two **interrupted** states — `TASK_STATE_INPUT_REQUIRED` and `TASK_STATE_AUTH_REQUIRED` — are *not* terminal. The Task is paused, waiting on the *client*. The agent will resume once the client supplies what is missing.

> **Key insight**: There are three buckets, not two. Active (`SUBMITTED`, `WORKING`), Interrupted (`INPUT_REQUIRED`, `AUTH_REQUIRED`), and Terminal. A client that only distinguishes "done vs. not done" will mishandle the interrupted bucket.

---

## 3. The state-machine diagram

Valid transitions for a Task (shown with friendly labels; the wire values are the `TASK_STATE_*` names above):

```
                         ┌─────────────┐
                         │  submitted  │
                         └──────┬──────┘
                                │  agent starts work
                                ▼
        ┌──────────────────►┌─────────────┐◄──────────────────┐
        │                   │   working   │                   │
        │                   └──────┬──────┘                   │
        │  client sends            │                          │  client supplies
        │  another Message         │                          │  credentials
        │  (same taskId)           │                          │  (same taskId)
        │                          │                          │
   ┌────┴─────────────┐            │            ┌─────────────┴────┐
   │  input-required  │            │            │  auth-required   │
   └────▲─────────────┘            │            └─────────────▲────┘
        │                          │                          │
        │  agent needs input  ┌────┴────┬──────────┐  agent needs auth
        └─────────────────────┤         │          ├──────────────────┘
                               ▼         ▼          ▼
                        ┌───────────┐ ┌────────┐ ┌──────────┐
                        │ completed │ │ failed │ │ canceled │
                        └───────────┘ └────────┘ └──────────┘

   rejected ◄── agent declines at intake (from submitted, before work begins)

   CancelTask can drive working / input-required / auth-required ──► canceled
```

Reading the diagram:

- `submitted → working` — the agent picked up the job.
- `working → completed | failed` — the normal happy/sad endings.
- `working → input-required → working` — the agent pauses, the client answers, work resumes. This loop can repeat any number of times.
- `working → auth-required → working` — same loop, but the missing thing is credentials.
- `submitted → rejected` — the agent refuses the task before doing any work.
- Any non-terminal state `→ canceled` — a `CancelTask` call (subject to a race; see §8).

> **Rule**: A terminal state has *no outgoing edges*. There is no `completed → working`. If you need to "continue" finished work, that is a **new Task** (optionally linked via `referenceTaskIds` — see §7).

---

## 4. The `TaskStatus` object

Every Task carries a `status` field of type `TaskStatus`:

| Field       | Type        | Required | Purpose                                                       |
|-------------|-------------|----------|---------------------------------------------------------------|
| `state`     | `TaskState` | Yes      | The current lifecycle state.                                  |
| `message`   | `Message`   | No       | A human/agent message explaining or accompanying this status. |
| `timestamp` | string      | No       | ISO 8601 timestamp of when this status was recorded.          |

A Task that is actively working:

```json
{
  "id": "task-7f3a9c21",
  "contextId": "ctx-4b8e",
  "status": {
    "state": "TASK_STATE_WORKING",
    "timestamp": "2026-05-18T09:14:02Z"
  }
}
```

A Task paused for input — note the `message` carries the agent's question:

```json
{
  "id": "task-7f3a9c21",
  "contextId": "ctx-4b8e",
  "status": {
    "state": "TASK_STATE_INPUT_REQUIRED",
    "message": {
      "role": "ROLE_AGENT",
      "parts": [
        { "text": "Which date range should the report cover?" }
      ]
    },
    "timestamp": "2026-05-18T09:14:31Z"
  }
}
```

A failed Task — the `message` should explain *why*:

```json
{
  "id": "task-7f3a9c21",
  "contextId": "ctx-4b8e",
  "status": {
    "state": "TASK_STATE_FAILED",
    "message": {
      "role": "ROLE_AGENT",
      "parts": [
        { "text": "Upstream data source returned 503 after 3 retries." }
      ]
    },
    "timestamp": "2026-05-18T09:19:50Z"
  }
}
```

💡 `status.message` is the most under-used field in A2A. For `TASK_STATE_INPUT_REQUIRED`, `TASK_STATE_AUTH_REQUIRED`, and `TASK_STATE_FAILED`, it is where the *actionable* information lives. Surface it to users — don't just display the bare state string.

---

## 5. Handling `input-required`

`input-required` means the agent has done as much as it can and needs the client to answer something before continuing. The Task is **alive but paused** — it is not finished.

The resume flow:

```
1. Client sends `SendMessage`                  → Task { id: T, contextId: C }
2. Agent works, then needs more info           → Task status.state = `TASK_STATE_INPUT_REQUIRED`
                                                  status.message = "the question"
3. Client reads the question, gets the answer
4. Client sends `SendMessage` AGAIN with:
      - a new Message containing the answer
      - taskId    = T   ◄── continues the SAME task
      - contextId = C   ◄── keeps the SAME conversation
5. Agent resumes                                → Task status.state = `TASK_STATE_WORKING`
6. ... eventually → `TASK_STATE_COMPLETED`
```

The critical detail is step 4: the follow-up Message must reference the **existing** `taskId` and `contextId`. That is what distinguishes "continuing a paused task" from "starting a brand-new task."

> **Rule**: To answer an `input-required` Task, send a new Message with the original `taskId` and `contextId`. Omitting `taskId` starts a fresh, unrelated Task — the agent never gets your answer.

✅ Correct — the answer routes back to the waiting Task:

```json
{
  "method": "SendMessage",
  "params": {
    "message": {
      "role": "ROLE_USER",
      "taskId": "task-7f3a9c21",
      "contextId": "ctx-4b8e",
      "parts": [{ "text": "2026-01-01 to 2026-03-31" }]
    }
  }
}
```

❌ Wrong — no `taskId`, so this spawns an orphan Task and the original stays stuck in `input-required` forever.

---

## 6. Handling `auth-required`

`auth-required` is structurally the same as `input-required` — a non-terminal pause waiting on the client — but the missing thing is **credentials**, not content.

Typical triggers: the agent must call a downstream API on the user's behalf (a SaaS connector, a payment provider) and has no valid token for it. Rather than fail, it parks the Task in `auth-required` and uses `status.message` to describe what authentication is needed.

```
TASK_STATE_WORKING ──► TASK_STATE_AUTH_REQUIRED ──► (client obtains/refreshes credentials) ──► TASK_STATE_WORKING
```

The client's job:

1. Read `status.message` to learn *which* credential or scheme is required.
2. Acquire it — typically an out-of-band OAuth flow, token refresh, or secret lookup.
3. Resume the Task by sending a Message with the matching `taskId`/`contextId`, supplying the credential via the channel the agent specified (often a transport-level `Authorization` header rather than message content).

> **Rule**: Treat `auth-required` exactly like `input-required` for lifecycle purposes — non-terminal, resumed by reusing `taskId`/`contextId`. The only difference is *what* you must provide.

⚠️ Never put long-lived secrets in a message `part`. Credentials belong in transport headers or the agent's declared auth scheme. The `auth-required` state tells you authentication is needed; it does not invite you to paste a token into chat text.

---

## 7. Polling, cancelling, and linking tasks

For non-streaming clients, the lifecycle is observed by **polling**:

- **`GetTask`** — fetch the current `Task` (and thus its `status.state`). Poll on a backoff until `state` is terminal, then stop. `GetTask` is a pure read and fully **idempotent** — calling it ten times changes nothing.
- **`CancelTask`** — request that the agent stop a non-terminal Task. On success the Task moves to `TASK_STATE_CANCELED`. Cancelling an *already-terminal* Task is a no-op or an error — it cannot resurrect or alter finished work.

> **Rule**: Poll `GetTask` with exponential backoff, not a tight loop. The terminal states (`COMPLETED`/`FAILED`/`CANCELED`/`REJECTED`) are your *only* stop condition — `INPUT_REQUIRED` and `AUTH_REQUIRED` mean "keep the Task open and act," not "stop."

**Idempotency.** `GetTask` and `CancelTask` are safe to retry — re-issuing them does not duplicate work. `SendMessage` can be treated as idempotent only when the server deduplicates by the client-supplied `messageId`; a retry without the same `messageId` or without the `taskId` on a continuation can create duplicate work.

**`referenceTaskIds`.** A Task lifecycle is closed once it terminates — there is no reopening it. To express that a *new* Task builds on or relates to earlier ones, the new request's `Message` carries a `referenceTaskIds` array listing those prior task IDs:

```json
{
  "role": "ROLE_USER",
  "contextId": "ctx-4b8e",
  "referenceTaskIds": ["task-7f3a9c21"],
  "parts": [{ "text": "Now redo that report for Q2." }]
}
```

This gives the agent context (the earlier completed Task) without violating the "terminal is forever" rule.

💡 `referenceTaskIds` lives on the **`Message`**, not on the `Task` object. It links *across* task boundaries; `taskId` continues *within* one.

---

## 8. Real-world failure modes

The lifecycle is small, but clients break it in predictable ways.

❌ **Treating a non-terminal state as terminal.** A client sees anything other than `TASK_STATE_WORKING` and assumes "done," then renders `TASK_STATE_INPUT_REQUIRED` as a final answer. The Task silently stalls because nobody answers the agent. *Fix*: branch on the three categories — Active, Interrupted, Terminal — never on a binary.

❌ **Not handling `input-required` (or `auth-required`) at all.** The client polls until it sees something "not working," gives up, and the paused Task expires server-side. *Fix*: when you see an interrupted state, read `status.message` and send a continuation Message.

❌ **Losing the `contextId`.** The client answers an `input-required` Task but generates a fresh `contextId` (or drops it). The agent treats the reply as an unrelated new conversation and loses all prior context — the report it asked you to scope is gone. *Fix*: persist `contextId` (and `taskId`) alongside any pending Task; echo them back verbatim.

❌ **Races on cancel.** The client calls `CancelTask`, assumes the Task is `TASK_STATE_CANCELED`, and stops — but the agent had *already* reached `TASK_STATE_COMPLETED` microseconds earlier. Cancel is a *request*, not a command; the agent may have finished or failed first. *Fix*: after `CancelTask`, do one more `GetTask` and trust the *actual* returned state. The Task may legitimately end up `TASK_STATE_COMPLETED` or `TASK_STATE_FAILED` instead of `TASK_STATE_CANCELED`.

⚠️ **Polling forever on `TASK_STATE_UNSPECIFIED`.** `TASK_STATE_UNSPECIFIED` is not terminal and not actionable. If `GetTask` keeps returning it, that is an operational problem (agent restarted, lost state). Cap retries and escalate — do not poll indefinitely.

> **Key insight**: Most lifecycle bugs are the same bug — the client collapsed the three-bucket model into two. Model Active, Interrupted, and Terminal explicitly, persist `taskId` + `contextId` for every open Task, and re-read state after every `cancel`.

---

**Next**: [Part 4: Streaming & Push](04_streaming_and_push.md)
