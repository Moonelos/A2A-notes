# Scaling & Deploying A2A Servers

> **Who this is for**: Engineers taking an A2A agent from a single-process prototype to a horizontally-scaled production deployment. Before reading this, understand how a server is wired up: **[Building a Server](../03_python/02_building_a_server.md)**, and how streaming works on the wire: **[Streaming & Push](../02_protocol/04_streaming_and_push.md)**.

The default `a2a-sdk` server you build from the quickstart runs fine on one machine. The moment you put two replicas behind a load balancer, a pile of in-process assumptions break: Task state lives in one replica's RAM, a live SSE stream and its `SubscribeToTask` attempt may land on different replicas, and a 40-minute task is pinned to the lifetime of one HTTP request. This file is about fixing all of that.

---

## 1. Stateless servers + shared state

> **Rule**: A horizontally-scaled A2A server replica must hold **no Task state in process memory**. Every replica must be able to serve a request for any task — because the load balancer will route it to whichever replica it likes.

The `a2a-sdk` request handler delegates all persistence to three pluggable abstractions. In the quickstart they all default to in-memory implementations, which are **dev-only** — they make every replica an island.

| Abstraction | In-memory (dev-only) | Production implementation |
|---|---|---|
| `TaskStore` | `InMemoryTaskStore` | `DatabaseTaskStore` (SQLAlchemy) or a custom Redis/Postgres store |
| `PushNotificationConfigStore` | `InMemoryPushNotificationConfigStore` | `DatabasePushNotificationConfigStore` |

⚠️ **SDK v1.0 reality check**: `DefaultRequestHandler` persists task state through `TaskStore`, but its live active-task/event fan-out is process-local. The old `queue_manager=` constructor argument is kept for backward compatibility and is not the cross-replica solution in v1.0. Use shared task storage for polling and terminal recovery, and use push notifications or your own worker/broker layer for long-running, cross-replica execution.

### The TaskStore interface

`TaskStore` is a thin async ABC — `save()`, `get()`, `delete()`, `list()`. The SDK ships a SQLAlchemy-backed `DatabaseTaskStore`, gated behind install extras:

```bash
# Pick the driver matching your DB. 'sql' pulls all of them.
pip install "a2a-sdk[postgresql]"   # asyncpg
pip install "a2a-sdk[mysql]"        # aiomysql
pip install "a2a-sdk[sqlite]"       # aiosqlite — single-node only, not for scale-out
```

Wiring `DatabaseTaskStore` into the server:

```python
from sqlalchemy.ext.asyncio import create_async_engine
from a2a.server.tasks import DatabaseTaskStore, DatabasePushNotificationConfigStore
from a2a.server.request_handlers import DefaultRequestHandler

# One shared engine per replica; the connection pool is per-process.
engine = create_async_engine(
    "postgresql+asyncpg://a2a:secret@db.internal:5432/a2a",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # drops dead connections instead of erroring mid-request
)

task_store = DatabaseTaskStore(engine, create_table=True)
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
    push_config_store=push_store,
)
```

⚠️ `create_table=True` is convenient for dev but races when N replicas boot at once. In production set `create_table=False` and run schema migrations as a separate deploy step (Alembic, or a one-shot `db-cli` job).

### A custom Redis TaskStore

If you already run Redis and don't want a SQL dependency, implement `TaskStore` directly. The shape is small:

```python
import redis.asyncio as aioredis
from google.protobuf.json_format import MessageToJson, Parse
from a2a.server.tasks import TaskStore
from a2a.types import Task

class RedisTaskStore(TaskStore):
    """Tasks as JSON blobs keyed by task id, with a TTL so completed
    tasks don't accumulate forever."""

    def __init__(self, client: aioredis.Redis, ttl_seconds: int = 86_400):
        self._redis = client
        self._ttl = ttl_seconds

    def _key(self, task_id: str) -> str:
        return f"a2a:task:{task_id}"

    async def save(self, task: Task, context=None) -> None:
        # ProtoJSON keeps the stored representation aligned with the wire format.
        await self._redis.set(self._key(task.id), MessageToJson(task), ex=self._ttl)

    async def get(self, task_id: str, context=None) -> Task | None:
        raw = await self._redis.get(self._key(task_id))
        return Parse(raw.decode("utf-8"), Task()) if raw else None

    async def delete(self, task_id: str, context=None) -> None:
        await self._redis.delete(self._key(task_id))

    # Implement list(...) as well if you need ListTasks over Redis.
```

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

For completion, **push notifications** close the loop without the client holding a connection open: the client registers a webhook (`TaskPushNotificationConfig`) when it sends the task; on terminal state a push sender POSTs a `StreamResponse` update to that URL. This is the right pattern for fire-and-forget and for tasks measured in minutes or hours. See [Streaming & Push](../02_protocol/04_streaming_and_push.md) for the protocol-level mechanics.

⚠️ Webhook delivery is a network call to an untrusted endpoint — it must be retried with backoff, time-limited, and authenticated (signed token / mTLS). Never let a slow webhook block a worker; dispatch it as its own job.

---

## 4. Deployment

### Dockerfile

A lean image for an `a2a-sdk` + `uvicorn` agent. Multi-stage keeps build tooling out of the runtime layer; non-root user is table stakes.

```dockerfile
FROM python:3.12-slim AS build
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install \
    "a2a-sdk[postgresql,telemetry]" -r requirements.txt

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
- **HPA**: scale the web tier on CPU/RPS. Scale the **worker tier** on **queue depth** (a custom/external metric) — that, not CPU, is the true signal of task backlog. A web tier HPA can't see work piling up in the job queue.
- Ingress controllers need the same `proxy-buffering: "off"` and timeout annotations as the Nginx block above.

---

## 5. Observability

You cannot operate a multi-hop agent system blind. A single user request may fan out across three or four agents; when it's slow, you need to see *which hop*.

### Distributed tracing with OpenTelemetry

The SDK ships first-class OTel support behind an extra:

```bash
pip install "a2a-sdk[telemetry]"
```

`a2a.utils.telemetry` provides `trace_function` and `trace_class` decorators — automatic span creation, sync + async support, exception recording, and a `attribute_extractor` callback for dynamic span attributes. Crucially, the SDK **propagates W3C Trace Context** across the A2A protocol boundary, so a trace started in the client continues through every downstream agent hop as one connected trace.

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from a2a.utils.telemetry import trace_function

provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # -> collector
trace.set_tracer_provider(provider)

class MyAgentExecutor(AgentExecutor):
    @trace_function(attributes={"agent": "research"})
    async def execute(self, context, event_queue):
        # This span links to the parent span carried in the inbound
        # A2A request headers — no manual context plumbing needed.
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
| Task latency (submit → terminal) | histogram | SLO tracking; p99 catches tail stalls |
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

**Retries with backoff** — retry only idempotent, transient failures (timeouts, 5xx, connection resets). Exponential backoff with jitter; never retry a `4xx`.

> **Rule**: A retried `SendMessage` must be **idempotent**. Generate a stable `messageId` (a client-side UUID) and reuse it on retry, so a duplicate delivery can be recognized as the *same* message rather than starting a second task.

**Circuit breakers** — wrap each remote agent. After a threshold of failures, open the breaker and fail fast for a cooldown instead of hammering a downed agent and exhausting your own connection pool. One slow dependency should not cascade into a fleet-wide stall.

**Graceful shutdown** — on `SIGTERM`: stop accepting new tasks (fail readiness so the LB drains you), let in-flight tasks finish or checkpoint, flush the OTel span processor, close DB and Redis pools, then exit. Set `terminationGracePeriodSeconds` longer than your drain window. Because task state is in the shared `TaskStore`, a task interrupted by shutdown can be **resumed by another replica or worker** — provided your executor checkpoints progress rather than holding it in local variables.

```python
async def shutdown():
    app.state.draining = True          # /health/ready now returns 503
    await drain_in_flight(timeout=30)  # bounded wait for active tasks
    provider.force_flush()             # don't lose the last traces
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
| Resilience | `SendMessage` idempotent via stable `messageId` | ☐ |
| Resilience | Graceful shutdown drains in-flight tasks, flushes telemetry | ☐ |

> **Key insight**: Every production concern here reduces to one principle — **no replica may own anything**. Task state, event streams, and execution lifetime all live outside the process, so any replica is disposable and any task survives a restart. Get that right and horizontal scaling, rolling deploys, and failure recovery all fall out for free.

---

**Next**: [Back to the repo overview](../README.md)
