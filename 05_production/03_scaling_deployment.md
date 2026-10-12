# Scaling & Deploying A2A Servers

> **Length note**: This production runbook keeps state, execution, deployment, observability, and failure recovery together because their shutdown and ownership contracts must be reviewed as one system.

> **Who this is for**: Engineers taking an A2A agent from a single-process prototype to a horizontally-scaled production deployment. Before reading this, understand how a server is wired up: **[Building a Server](../03_python/02_building_a_server.md)**, and how streaming works on the wire: **[Streaming & Push](../02_protocol/04_streaming_and_push.md)**.

The teaching baseline is `a2a-sdk` 1.1.2. It is an architecture example, **not a recommended production pin**: 1.1.4 fixed owner-scoped cancel/subscribe and push URL validation, and 1.2.0 introduced cluster mode. Plan a tested upgrade before production. The default 1.1.2 server you build from the quickstart runs fine on one machine. The moment you put two replicas behind a load balancer, a pile of in-process assumptions break: Task state lives in one replica's RAM, a live Server-Sent Events (SSE) stream and its `SubscribeToTask` attempt may land on different replicas, and a 40-minute task is pinned to the lifetime of one HTTP request. This file is about fixing all of that.

---

## 1. Stateless servers + shared state

> **Rule**: A horizontally-scaled A2A server replica must hold **no Task state in process memory**. Every replica must be able to serve a request for any task — because the load balancer will route it to whichever replica it likes.

The `a2a-sdk` request handler delegates all persistence to three pluggable abstractions. In the quickstart they all default to in-memory implementations, which are **dev-only** — they make every replica an island.

| Abstraction | In-memory (dev-only) | Production implementation |
|---|---|---|
| `TaskStore` | `InMemoryTaskStore` | `DatabaseTaskStore` (SQLAlchemy) or a custom Redis/Postgres store |
| `PushNotificationConfigStore` | `InMemoryPushNotificationConfigStore` | `DatabasePushNotificationConfigStore` |

⚠️ **SDK 1.1.2 reality check**: `DefaultRequestHandler` aliases the v2 handler and persists snapshots through `TaskStore`, but its `ActiveTaskRegistry` and live event fan-out remain process-local. The old `queue_manager=` argument is compatibility surface, not a cross-replica solution. Use shared task storage for polling and terminal recovery, and a durable worker/broker layer for execution ownership.

### The TaskStore interface

`TaskStore` is a thin async ABC — `save()`, `get()`, `delete()`, `list()`. The SDK ships a SQLAlchemy-backed `DatabaseTaskStore`, gated behind install extras:

```bash
# Pick the driver matching your DB. 'sql' pulls all of them.
pip install "a2a-sdk[postgresql,encryption]"  # asyncpg + encrypted push config
pip install "a2a-sdk[mysql]"        # aiomysql
pip install "a2a-sdk[sqlite]"       # aiosqlite — single-node only, not for scale-out
```

Wiring `DatabaseTaskStore` into the server:

```python
from sqlalchemy.ext.asyncio import create_async_engine
from a2a.server.owner_resolver import resolve_user_scope
from a2a.server.tasks import DatabaseTaskStore, DatabasePushNotificationConfigStore
from a2a.server.request_handlers import DefaultRequestHandler

# One shared engine per replica; the connection pool is per-process.
engine = create_async_engine(
    "postgresql+asyncpg://a2a:secret@db.internal:5432/a2a",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # drops dead connections instead of erroring mid-request
)

task_store = DatabaseTaskStore(
    engine,
    create_table=True,
    owner_resolver=resolve_user_scope,
)
push_store = DatabasePushNotificationConfigStore(
    engine,
    create_table=True,
    encryption_key=PUSH_CONFIG_KEY,  # webhook URLs + tokens are secrets — encrypt at rest
)

# Call initialize() once at startup so the tables exist before traffic arrives.
await task_store.initialize()
await push_store.initialize()

handler = DefaultRequestHandler(
    agent_executor=MyAgentExecutor(),
    task_store=task_store,
    agent_card=agent_card,  # the same validated card served by discovery routes
    push_config_store=push_store,
)
```

`resolve_user_scope(context)` must receive the authenticated owner established at ingress. The shipped database store includes that owner in save/get/list/delete predicates; verify your HTTP/gRPC adapter actually populates the context before relying on it. Generate the Fernet key using the SDK encryption utility or `Fernet.generate_key()`, store it in a secrets manager, and rotate it with an explicit decrypt-and-re-encrypt migration—losing it makes stored callback credentials unreadable.

⚠️ `create_table=True` is convenient for dev but races when N replicas boot at once. In production set `create_table=False` and run schema migrations as a separate deploy step (Alembic, or a one-shot `db-cli` job).

### A custom store must implement the whole ownership contract

Do not copy a task-ID-only Redis example into production. The current `TaskStore` abstract interface requires `save`, `get`, `list`, and `delete`, each with a `ServerCallContext`. Every Redis key and index must include `resolve_user_scope(context)`—for example `a2a:{owner}:task:{task_id}` and `a2a:{owner}:tasks`—and `list` must filter only that owner before applying context/status filters and page tokens. It must return `ListTasksResponse` with `tasks`, `totalSize`, `pageSize`, and `nextPageToken`; the handler then applies requested history length and artifact inclusion. Use atomic transactions/Lua for blob-plus-index updates, opaque signed page tokens, and a time-to-live (TTL) policy that expires the blob and owner index consistently.

The shipped `DatabaseTaskStore` is the safer baseline because those owner predicates and list semantics are already implemented. A custom store is complete only after tests prove that owner A cannot get, list, overwrite, or delete owner B's task—even with a known task ID or page token.

✅ With a shared store, any replica can answer `GetTask` and list completed or in-progress task snapshots.
❌ Leaving `InMemoryTaskStore` in place under a load balancer produces "task not found" errors that depend on which replica you hit — the worst kind of intermittent bug.

---

## 2. Why this matters for streaming

`SendStreamingMessage` opens an SSE response; the agent's execution pushes incremental events (`TaskStatusUpdateEvent`, `TaskArtifactUpdateEvent`) into an `EventQueue`, and the server drains that queue into the SSE stream. `SubscribeToTask` lets a client **re-attach** to a non-terminal task's event stream after a dropped connection.

In a single process this is just an in-memory `asyncio.Queue`. With multiple replicas it breaks immediately:

```
   Client opens SSE stream            Client reconnects (SubscribeToTask)
            │                                       │
            ▼                                       ▼
     ┌────────────┐                          ┌────────────┐
     │ Replica A  │  agent runs HERE          │ Replica B  │  Subscribe lands HERE
     │ events ──▶ │  in-process queue ✗       │  queue is  │  empty — no events ever arrive
     └────────────┘                          └────────────┘
```

The agent runs on Replica A and emits into A's local queue. The client reconnects, the load balancer routes it to Replica B, and B's process-local active-task registry knows nothing about the live stream. The client can still call `GetTask` against the shared store, but it may not be able to tap live events from Replica A.

> **Rule**: With more than one replica, treat live SSE as a best-effort channel unless you have explicitly moved execution/events into a shared brokered architecture. The portable fallback is `GetTask` against the shared `TaskStore`; the scalable long-task pattern is push notifications or a worker tier that writes durable task updates.

If you need cross-replica live replay, design it deliberately: have workers publish task events to a durable broker (Redis Streams, Kafka, Pub/Sub), persist every artifact/status update to the `TaskStore`, and expose `SubscribeToTask` from a service that can read that broker. Do not assume the stock in-process event queues become distributed just because the task store is shared.

💡 Sticky sessions (LB session affinity) can paper over this for a single uninterrupted stream, but they do **not** survive a replica restart or a reconnect after the affinity cookie expires. Use durable task state plus push notifications or a shared broker; treat affinity as an optimization, not a correctness mechanism.

---

## 3. Long-running tasks — decouple execution from the request

A2A tasks routinely outlive a sane HTTP request: research jobs, multi-step tool chains, human-in-the-loop approvals. If task execution is awaited inside the request handler, you get:

- web workers blocked for minutes, throughput collapsing under load;
- a dropped connection or a deploy killing in-flight work;
- load-balancer and proxy idle timeouts (often 30–60s) severing the request mid-task.

> **Principle**: The HTTP request's job is to *accept the task and return a `taskId`*. The actual work belongs to a background tier.

```
SendMessage  ──▶  web tier: persist Task(state=TASK_STATE_SUBMITTED), enqueue job, return taskId
                                          │
                                          ▼
                              ┌───────────────────────┐
                              │  worker pool / job q   │  Celery, Arq, RQ, Dramatiq,
                              │  picks up the job      │  or a cloud queue (SQS/PubSub)
                              └───────────┬───────────┘
                                          │ executes agent, persists task updates
                                          │ to TaskStore and sends push events
                                          ▼
                          on completion: state=TASK_STATE_COMPLETED
                                          │
                                          ▼
                            push notification (webhook) ──▶ client
```

The worker should emit the same durable state changes an in-request executor would — `TASK_STATE_WORKING`, artifact updates, and exactly one terminal state. Because those updates are persisted through the shared `TaskStore`, progress is visible to `GetTask`; because push configs are shared, completion can be delivered by webhook. If you also need live SSE, publish the same events to your broker-backed streaming layer.

### A crash and reclaim, step by step

The lease is a deadline on *execution ownership*, not a statement that a Task row exists. Here `task-7` has an external invoice-posting step; its provider request uses idempotency key `tenant-A/agent-A/task-7/step-5`.

```mermaid
sequenceDiagram
  participant W as Web tier
  participant DB as jobs/tasks/outbox DB
  participant A as Worker A
  participant B as Worker B
  W->>DB: transaction: task-7 SUBMITTED + job READY + outbox
  A->>DB: claim task-7, epoch 1, lease until t=60
  A->>DB: WORKING + checkpoint step-4
  A-xDB: crashes before step-5 result
  B->>DB: t=61 claim expired lease, epoch 2
  DB-->>B: checkpoint step-4 + task-7
  B->>DB: retry step-5 with same provider idempotency key
  B->>DB: COMPLETED + push outbox in one transaction
```

At t=40, Worker B must not claim while A's lease is current. At t=61, B can claim but cannot assume step-5 never reached the provider: A may have crashed after sending it. B's claim increments a **fencing epoch** from 1 to 2. If A wakes after t=61, its epoch-1 checkpoint or completion transaction must affect zero rows and roll back; otherwise an expired worker can overwrite B's newer state. The stable provider key prevents a second invoice posting; the checkpoint identifies the last *durably confirmed* step. Event IDs and a uniqueness constraint keep replay from emitting duplicate status or push rows. If the provider lacks idempotency, stop for reconciliation instead of automatic replay.

**Failure drill for an assembled deployment:** create a long-running `task-7`, verify `GetTask` reports `WORKING`, and record its owner, job ID, checkpoint, claim epoch, lease owner/deadline, event count, and outbox count. Kill the worker after checkpoint step-4 and before completion. Confirm another worker cannot claim before expiry, claims after expiry with a larger epoch, resumes from step-4, uses the same external idempotency key, and records exactly one terminal result and push intent. Also delay Worker A until after B reclaims and prove A's stale-epoch commit changes zero rows and emits no event. Reconnect through a different web replica and check the snapshot plus any broker-backed events for the same tenant/owner. This drill requires your actual worker, database, provider stub, and broker; the snippets in this note are design excerpts and do not themselves constitute a deployable application.

### Run the bounded crash drill locally

The [complete SQLite fixture](../examples/production/failover_fixture.py) executes the same sequence with two processes and a temporary database. Run it from the repository root with `python3 examples/production/failover_fixture.py`; it needs only the Python standard library. Worker A claims epoch 1, commits checkpoint 4, writes a provider-stub result under the stable step-5 key, and exits hard before recording completion. The controller proves B cannot claim at virtual t=40, then can at t=61 with epoch 2. A stale epoch-1 completion rolls back. B reuses the provider key, commits the terminal Task and one outbox row, and dispatches that row twice to an idempotent local receiver. The fixture asserts exactly one provider action, one outbox intent, and one delivery.

Expected output:

```text
worker A killed after provider call; checkpoint=4
t=40: B denied while lease current
t=61: B reclaimed epoch=2, checkpoint=4
stale A epoch=1 completion denied
terminal task=COMPLETED; provider=1, outbox=1, delivery=1
```

This verifies transaction and fencing behavior on SQLite. Virtual time makes the lease boundary deterministic; it does not test clock skew. The local `deliveries` table models receiver deduplication, not a webhook or shared broker. Continue with the assembled deployment drill above for gateway routing, SDK TaskStore updates, broker replay, push authentication, and network failure recovery.

| Symptom | Inspect | Recovery |
|---|---|---|
| `SUBMITTED` grows with no claims | READY jobs, dispatcher lag, worker health | Restore dispatch/worker, then retry unsent outbox rows |
| Lease expired but no reclaim | claim predicate, database clock, worker poll loop | repair poller and reclaim; do not duplicate an uncertain external step |
| Duplicate external action | provider idempotency key and reservation log | stop replay, reconcile provider state, then advance checkpoint |
| Snapshot advances but stream stalls | event log/broker lag and proxy buffering | serve `GetTask`, repair event path, then allow resubscribe |

Alert on oldest READY age, expired RUNNING lease count, outbox age, duplicate provider attempts, task terminal latency, and event replay lag. Drain worker claims before deploying a new worker version; maintain schema compatibility until old leases expire. Roll back the worker binary only while it can read current checkpoints and write the current schema.

### The durable acceptance/lease path

A queue message alone is not ownership. Use one database transaction to create the submitted task, a durable job record, and an outbox row. A dispatcher publishes the outbox row and marks it sent. Workers claim jobs with a renewable lease and persist each state/event idempotently:

```sql
BEGIN;
INSERT INTO tasks(owner, id, state, version) VALUES (:owner, :task, 'SUBMITTED', 1);
INSERT INTO jobs(owner, task_id, message_id, state, claim_epoch)
VALUES (:owner, :task, :message, 'READY', 0);
INSERT INTO outbox(event_id, topic, payload)
VALUES (:event_id, 'a2a.jobs', :job_payload);
COMMIT;

-- Worker claim; only one worker obtains the lease.
UPDATE jobs SET state='RUNNING', lease_owner=:worker,
                claim_epoch=claim_epoch + 1,
                lease_until=NOW() + INTERVAL '60 seconds'
WHERE owner=:owner AND task_id=:task
  AND state IN ('READY','RUNNING')
  AND (lease_until IS NULL OR lease_until < NOW())
RETURNING *;

-- Before writing checkpoint, Task status, or outbox, lock this job row.
-- The application must ROLLBACK the entire transaction if zero rows return.
BEGIN;
UPDATE jobs SET checkpoint=:checkpoint
WHERE owner=:owner AND task_id=:task
  AND lease_owner=:worker AND claim_epoch=:claimed_epoch
  AND lease_until > NOW() AND state='RUNNING'
RETURNING claim_epoch;
-- Only after one row returns: update Task and insert unique event/outbox rows.
COMMIT;
```

The SQL is a design excerpt: provision a `claim_epoch` counter and checkpoint column before using it. The web response is observable immediately: `GetTask` returns `SUBMITTED`. After a successful claim, the worker transaction changes it to `WORKING`; artifact/status events use a unique event ID so retries become no-ops; completion stores `COMPLETED` and a push-outbox row in the same guarded transaction. A zero-row epoch guard aborts all Task and outbox writes. Because the guarded update holds the job row lock through commit, a competing reclaim cannot interleave a terminal write. If the worker crashes, its lease expires, another worker claims the durable job, loads the last checkpoint, and replays idempotently. If no checkpoint exists, restart from the beginning only when tools and writes have idempotency keys.

Push notifications close the loop without the client holding a connection open: the client registers a webhook (`TaskPushNotificationConfig`), and the sender POSTs `StreamResponse` task/message/status/artifact updates. The protocol requires at least one delivery attempt per configured webhook; retry/backoff is optional at protocol level but should be a bounded production policy. See [Streaming & Push](../02_protocol/04_streaming_and_push.md) for the payload and authentication mechanics.

⚠️ Webhook delivery is a network call to an untrusted endpoint — it must be retried with backoff, time-limited, and authenticated (signed token / mTLS). Never let a slow webhook block a worker; dispatch it as its own job.

---

### SDK 1.2.x cluster mode changes the choice

The [1.2.0 release](https://github.com/a2aproject/a2a-python/releases/tag/v1.2.0) added opt-in multi-replica support: `VersionedDatabaseTaskStore` checks concurrent revisions, `DatabaseTaskEventStream` shares events, and `DefaultRequestHandlerV2(event_stream=...)` can serve resubscribe and cancel from another replica. It adds `task_versions` and `task_events` tables. The [merged design and sample](https://github.com/a2aproject/a2a-python/pull/1281) show the cross-replica behavior; [1.2.2](https://github.com/a2aproject/a2a-python/releases/tag/v1.2.2) is the newest checked release on 2026-10-12.

| Need | 1.1.2 teaching baseline | 1.2.x cluster path |
|---|---|---|
| Read task snapshot on any replica | Shared `DatabaseTaskStore` | Versioned store |
| Continue SSE after reconnect to another replica | Separate broker/event path | Shared `TaskEventStream` |
| Concurrent cancel/update | Application coordination | Revision check in versioned store |
| Survive worker-process death during an external action | Durable job, lease, checkpoint, idempotency still required | Same application requirement; cluster event replay alone cannot safely repeat a side effect |

**Upgrade gate:** apply the cluster migrations in a staged environment, switch one isolated agent to the versioned store/event stream, run cross-replica send/get/subscribe/cancel and the crash drill above, then compare task/event counts and owner denials. Preserve old schema and binaries until mixed-version behavior is tested. The following local smoke test uses the [official SDK 1.2.2 cluster sample](https://github.com/a2aproject/a2a-python/tree/v1.2.2/samples/clustermode) in a separate checkout. It needs Python 3.12 and `uv`:

```bash
git clone --depth 1 --branch v1.2.2 https://github.com/a2aproject/a2a-python a2a-python-1.2.2
cd a2a-python-1.2.2
uv venv --python 3.12
uv pip install --python .venv/bin/python 'a2a-sdk[http-server,sqlite]==1.2.2' fastapi uvicorn
```

In one shell, start the three replicas. In a second shell in the same checkout, run the exercise. The cluster process keeps running until you stop it with Ctrl+C.

```bash
./.venv/bin/python -m samples.clustermode.run_cluster --replicas 3 --base-port 41241
# In another shell, from that same checkout:
./.venv/bin/python -m samples.clustermode.exercise --host 127.0.0.1 --ports 41241,41242,41243
```

On 2026-10-12, this exact exercise exited 0: it started a Task on replica 0, read `TASK_STATE_WORKING` on replica 1, canceled through replica 2, and read `TASK_STATE_CANCELED` again on replica 0. That proves the sample's cross-replica Task visibility and cancellation with one shared SQLite file on one host. It does not prove a remote database, multi-host network failure, tenant isolation, push delivery, or your application's worker failover. A production upgrade still needs the owner and failure drill for your own tools and stores.

## 4. Deployment

### Dockerfile

A lean image for an `a2a-sdk` + `uvicorn` agent. Multi-stage keeps build tooling out of the runtime layer; non-root user is table stakes.

```dockerfile
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    "a2a-sdk[postgresql,telemetry,encryption]" \
    "opentelemetry-exporter-otlp-proto-grpc" -r requirements.txt

FROM python:3.12-slim
WORKDIR /app
COPY --from=build /install /usr/local
COPY . .
RUN useradd --no-create-home --uid 10001 agent
USER agent
EXPOSE 8080
# Single uvicorn worker per container — scale with replicas, not in-process
# workers, so each replica has one clean async event loop.
CMD ["uvicorn", "app:server", "--host", "0.0.0.0", "--port", "8080", \
     "--timeout-graceful-shutdown", "30"]
```

> **Rule**: Scale out with **container replicas**, not uvicorn `--workers`. One process per container keeps connection pools, metrics, and graceful-shutdown logic simple, and lets the orchestrator do the scaling.

### Behind a reverse proxy / load balancer

SSE is a long-lived streaming response. Proxies optimized for request/response will quietly ruin it:

```nginx
location / {
    proxy_pass http://a2a_backend;
    proxy_http_version 1.1;

    # SSE essentials — without these the stream is broken or buffered.
    proxy_buffering off;          # don't hold events until the buffer fills
    proxy_cache off;
    proxy_set_header Connection '';
    chunked_transfer_encoding on;

    # Generous timeouts: a streamed task may emit nothing for minutes.
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

⚠️ The classic SSE failure: events arrive at the client in one burst at the end instead of incrementally. Cause is almost always proxy buffering left on (`proxy_buffering`, or an upstream CDN/ingress buffer).

### Kubernetes notes

```yaml
spec:
  replicas: 3
  template:
    spec:
      terminationGracePeriodSeconds: 45   # > drain window in section 5
      containers:
        - name: a2a-agent
          image: registry.internal/a2a-agent:1.4.0
          ports: [{ containerPort: 8080 }]
          readinessProbe:                  # gates LB traffic
            httpGet: { path: /health/ready, port: 8080 }
            periodSeconds: 5
          livenessProbe:                   # restarts a wedged process
            httpGet: { path: /health/live, port: 8080 }
            periodSeconds: 10
            failureThreshold: 3
```

- **Readiness vs liveness**: readiness should check that the DB engine and Redis are reachable — a replica that can't reach shared state must not receive traffic. Liveness should be a cheap in-process check; don't fail liveness on a transient DB blip or Kubernetes will restart-loop the whole fleet.
- **Horizontal Pod Autoscaler (HPA)**: scale the web tier on CPU or requests per second (RPS). Scale the **worker tier** on **queue depth** (a custom/external metric)—that, not CPU, is the true signal of task backlog. A web-tier HPA cannot see work piling up in the job queue.
- Ingress controllers need the same `proxy-buffering: "off"` and timeout annotations as the Nginx block above.

---

## 5. Observability

You cannot operate a multi-hop agent system blind. A single user request may fan out across three or four agents; when it's slow, you need to see *which hop*.

### Distributed tracing with OpenTelemetry

The SDK ships first-class OTel support behind an extra:

```bash
pip install "a2a-sdk[telemetry]" opentelemetry-exporter-otlp-proto-grpc
```

`a2a.utils.telemetry` provides `trace_function` and `trace_class` decorators for span creation and exception recording. It does **not** inject or extract W3C Trace Context for you. Instrument the HTTP/gRPC carrier or write interceptors that explicitly inject outbound `traceparent`/`tracestate` headers and extract them before the server span begins.

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.context import attach, detach
from opentelemetry.propagate import extract, inject
from a2a.utils.telemetry import trace_function

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # -> collector
trace.set_tracer_provider(provider)

def inject_a2a_headers(headers: dict[str, str]) -> None:
    """Call from the outbound HTTP interceptor before sending."""
    inject(headers)


async def dispatch_inbound(request):
    """Call at ingress before the SDK handler creates server spans."""
    token = attach(extract(dict(request.headers)))
    try:
        return await dispatch_to_a2a_handler(request)
    finally:
        detach(token)


class MyAgentExecutor(AgentExecutor):
    @trace_function(attributes={"agent": "research"})
    async def execute(self, context, event_queue):
        # Parent linkage exists because dispatch_inbound extracted it explicitly.
        ...
```

### Structured logging

Log JSON, and **key every line by `taskId` and `contextId`**. That is what makes logs joinable to traces and lets you reconstruct the full life of one task across replicas and workers.

```python
logger.info(
    "task.state_changed",
    extra={"task_id": task.id, "context_id": task.context_id,
           "state": task.status.state, "trace_id": current_trace_id()},
)
```

### Metrics

| Metric | Type | Why it matters |
|---|---|---|
| Task latency (submit → terminal) | histogram | Service-level objective (SLO) tracking; p99 catches tail stalls |
| Task state distribution | gauge | A growing `working` count = stuck/leaking tasks |
| Error rate (`failed` / total) | counter ratio | Primary alerting signal |
| Event queue depth | gauge | Worker-tier HPA input; backlog early warning |
| Webhook delivery success rate | counter ratio | Silent push-notification failures hide here |

---

## 6. Resilience

A2A is a network of remote agents; every call is a chance to fail. Build for it on both sides.

**Client-side timeouts** — never an unbounded call. Bound the connect, the overall request, and (for streaming) the inter-event gap.

```python
import httpx
client = httpx.AsyncClient(
    timeout=httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
)
```

**Retries with backoff** — retry only operations known to be idempotent and failures likely to be transient: timeouts, connection resets, selected `5xx`, and conditionally `408`, `425`, or `429`. Honor `Retry-After` where defined, use exponential backoff with jitter and bounded attempts, and treat other `4xx` responses as permanent.

> **Rule**: A2A says `SendMessage` **MAY** be idempotent and a server **MAY** use `messageId`; a stable ID is not a guarantee by itself. Retry only when the server advertises or contractually promises durable deduplication. Its acceptance transaction stores `(owner, messageId) → taskId/result` under a uniqueness constraint; a duplicate returns that stored result instead of enqueueing another job.

**Circuit breakers** — wrap each remote agent. After a threshold of failures, open the breaker and fail fast for a cooldown instead of hammering a downed agent and exhausting your own connection pool. One slow dependency should not cascade into a fleet-wide stall.

**Graceful shutdown** — on `SIGTERM`: stop accepting new tasks (fail readiness so the LB drains you), drain the SDK handler, let owned worker jobs finish or checkpoint and release leases, flush telemetry, then close shared clients. Set `terminationGracePeriodSeconds` longer than the drain window. A `TaskStore` snapshot alone cannot transfer execution: failover also requires a durable job record, lease/claim protocol, checkpoint, and idempotent worker as shown in §3.

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app):
    yield
    app.state.draining = True          # /health/ready now returns 503
    await handler.aclose()             # drains 1.1.2 ActiveTask background work
    await release_or_checkpoint_worker_leases(timeout=30)
    provider.force_flush()
    await http_client.aclose()
    await engine.dispose()
    await redis_client.aclose()
```

---

## 7. Production-readiness checklist

| Area | Item | Done |
|---|---|---|
| State | `InMemoryTaskStore` replaced with `DatabaseTaskStore` / shared store | ☐ |
| State | Schema created via migrations, not `create_table=True` at boot | ☐ |
| State | `PushNotificationConfigStore` is shared **and** encrypted at rest | ☐ |
| Streaming | Live SSE limitations understood; broker/push/polling strategy chosen | ☐ |
| Streaming | `SubscribeToTask` behavior verified under your load-balancer topology | ☐ |
| Execution | Long tasks offloaded to a worker/job tier, not the request | ☐ |
| Execution | Completion delivered via authenticated, retried webhooks | ☐ |
| Deploy | One uvicorn process per container; scale by replicas | ☐ |
| Deploy | Proxy buffering off + generous timeouts for SSE | ☐ |
| Deploy | Readiness checks shared-state reachability; liveness is cheap | ☐ |
| Deploy | Worker tier HPA scales on queue depth | ☐ |
| Observability | OTel tracing on with trace-context propagation across hops | ☐ |
| Observability | Structured logs keyed by `taskId` / `contextId` | ☐ |
| Observability | Metrics + alerts on error rate, latency p99, queue depth | ☐ |
| Resilience | Client timeouts, backoff retries, circuit breakers in place | ☐ |
| Resilience | Durable `(owner, messageId)` deduplication exists before retrying `SendMessage` | ☐ |
| Resilience | Graceful shutdown drains in-flight tasks, flushes telemetry | ☐ |

> **Key insight**: Shared snapshots make tasks visible across replicas; they do not make execution durable. A disposable web tier needs owner-scoped state plus a durable job, lease, checkpoint, idempotent event log, and shutdown contract before a task can safely survive failover.

## Retain the failover model

- A shared TaskStore makes snapshots readable from any replica; a shared event stream or broker supplies reconnectable events.
- A Task row does not transfer work. A durable job, lease, checkpoint, and idempotent side-effect contract do.
- A crashed worker may have sent a request without recording its result, so reclaim must reuse an idempotency key or reconcile.
- Cluster mode in SDK 1.2.x addresses cross-replica task revisions and events; the application still owns external side-effect recovery.

**Q:** A client reconnects to Replica B while the 1.1.2 live queue remains on A. What can B return from shared storage?

<details><summary>Answer</summary>

B can return the persisted Task snapshot through `GetTask`. It cannot replay A's process-local queue through `SubscribeToTask` without a shared event path.

</details>

**Q:** A died after posting an invoice but before saving step-5. What should B do at lease expiry?

<details><summary>Answer</summary>

B resumes from the durable step-4 checkpoint and uses the *same* provider idempotency key for step-5. If the provider cannot deduplicate, B must reconcile the uncertain result before issuing another post.

</details>

**Try it:** Extend the failure drill for a push webhook. Which records should be written with `COMPLETED`, and what unique key prevents two notifications after reclaim?

<details><summary>Worked answer</summary>

Write the terminal Task transition, terminal event, and push outbox intent in one database transaction. Give the intent a stable event ID unique per task/terminal transition; the dispatcher may retry delivery but must not create a second intent on worker replay. The webhook receiver should also deduplicate that event ID.

</details>

---

**Next**: [Back to the repo overview](../README.md)
