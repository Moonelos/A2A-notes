# Building an A2A Client with `a2a-sdk`

<!-- length-justification: This implementation note keeps discovery, transport selection, send/stream recovery, authentication, and cleanup in one client lifecycle so identity captured in one stage is visible in the next. -->

> **Who this is for**: Python engineers who have built or read about an A2A server and now need to *call* one. You know `async`/`await` and `httpx`. By the end you can discover a remote agent, send it work, stream results, resume an `input-required` pause, and attach credentials — all against `a2a-sdk==1.1.2`.

Before reading this, understand the server side: **[Building a Server](02_building_a_server.md)**. The streaming event model is covered in **[Streaming & Push](../02_protocol/04_streaming_and_push.md)**.

> **Rule**: Everything here targets `a2a-sdk` **`1.1.2`**. The wire model uses Protocol Buffers types. A protobuf **`oneof`** is a group in which exactly one field may be active, so response code uses `HasField()` before reading `message`, `task`, `status_update`, or `artifact_update`. **gRPC** is A2A's typed remote-procedure-call binding over HTTP/2; **Server-Sent Events (SSE)** is the HTTP stream used by JSON-RPC and HTTP+JSON.

## Quick start: discover, create, send, interpret

Start the echo server from [Building a Server](02_building_a_server.md), then save this as `echo_client.py`:

```python
import asyncio
from uuid import uuid4

import httpx

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState
from a2a.utils import TransportProtocol


async def main() -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        card = await A2ACardResolver(
            httpx_client=http, base_url="http://127.0.0.1:9999"
        ).get_agent_card()
        client = ClientFactory(ClientConfig(
            httpx_client=http,
            supported_protocol_bindings=[TransportProtocol.JSONRPC],
        )).create(card)

        request = SendMessageRequest(message=Message(
            message_id=f"msg-{uuid4()}",
            role=Role.ROLE_USER,
            parts=[Part(text="hello")],
        ))
        async with client:
            async for event in client.send_message(request=request):
                if event.HasField("message"):
                    print("reply:", event.message.parts[0].text)
                elif event.HasField("task"):
                    print("task:", TaskState.Name(event.task.status.state))
                    for artifact in event.task.artifacts:
                        print("artifact:", artifact.parts[0].text)


asyncio.run(main())
```

Run `python echo_client.py`. The baseline server produces `task: TASK_STATE_COMPLETED` and `artifact: echo: hello`. A card-resolution error means the server or well-known route is unavailable; `no compatible transports found` means the card and `ClientConfig` share no binding.

> **Production:** this baseline is deliberately local and unauthenticated. Streaming recovery, secure gRPC, credentials, timeouts, and bounded retries follow after the working round trip.

---

## 1. The Client Pipeline

A client is built in three stages. You rarely touch the transport directly — the **`ClientFactory`** picks it from the agent's card.

```
  base URL
     │
     ▼
┌──────────────────┐   GET /.well-known/agent-card.json
│ A2ACardResolver  │ ─────────────────────────────────────►  AgentCard
└──────────────────┘
     │ AgentCard
     ▼
┌──────────────────┐   reads card.supported_interfaces,
│  ClientFactory   │   matches against ClientConfig bindings,
│  + ClientConfig  │   selects JSONRPC / HTTP+JSON / gRPC transport
└──────────────────┘
     │ Client  (transport-agnostic)
     ▼
┌──────────────────┐   send_message()  -> AsyncIterator[StreamResponse]
│      Client      │   get_task()      -> Task
│                  │   subscribe()     -> AsyncIterator[StreamResponse]
└──────────────────┘
```

The public surface lives in `a2a.client`:

```python
from a2a.client import (
    A2ACardResolver,      # base URL  -> AgentCard
    ClientFactory,        # AgentCard -> Client
    ClientConfig,         # transport prefs, streaming, polling, httpx client
    Client,               # transport-agnostic abstract client
    create_client,        # one-shot convenience: URL/card -> Client
    AuthInterceptor,      # attaches credentials to every outbound call
    CredentialService, InMemoryContextCredentialStore,
    A2AClientError, A2AClientTimeoutError, AgentCardResolutionError,
)
```

The `Client` is transport-agnostic by construction. The same `send_message` call runs over JSON-RPC, HTTP+JSON, or gRPC according to the card and `ClientConfig`.

---

## 2. Resolving an Agent Card

`A2ACardResolver` fetches and parses the card. It needs an `httpx.AsyncClient` you own — the SDK never creates a global HTTP client behind your back.

```python
import httpx
from a2a.client import A2ACardResolver, AgentCardResolutionError

async def discover(base_url: str) -> None:
    # One httpx client, owned by you, reused for the card fetch *and* the
    # client below. Always set an explicit timeout.
    async with httpx.AsyncClient(timeout=30.0) as http:
        resolver = A2ACardResolver(httpx_client=http, base_url=base_url)
        try:
            # No path arg => fetches <base_url>/.well-known/agent-card.json
            card = await resolver.get_agent_card()
        except AgentCardResolutionError as e:
            # Raised for HTTP errors, network failures, bad JSON, or a
            # payload that doesn't validate against the AgentCard schema.
            print(f"Could not resolve agent: {e}")
            return

        print(f"Agent: {card.name} v{card.version}")
        print(f"Streaming: {card.capabilities.streaming}")
        for iface in card.supported_interfaces:
            print(f"  {iface.protocol_binding} -> {iface.url}")
```

The well-known path is the SDK constant `AGENT_CARD_WELL_KNOWN_PATH` (`/.well-known/agent-card.json`). Pass `relative_card_path=` to `get_agent_card()` for agents that publish elsewhere, and `http_kwargs=` to forward headers to the underlying `httpx.get`:

```python
card = await resolver.get_agent_card(
    relative_card_path="/agent/card.json",
    http_kwargs={"headers": {"X-Tenant": "acme"}},
)
```

⚠️ The resolver follows the card's *backward-compatibility* rules: a legacy `url` + `preferredTransport` is auto-folded into `supported_interfaces`. So a card from a `0.3` agent still resolves — but you are talking to a `0.3` agent, and some methods (`list_tasks`, push-config) may raise `NotImplementedError`.

💡 For gRPC-only agents that expose no well-known HTTP path, skip the resolver and use `minimal_agent_card(url, transports=[TransportProtocol.GRPC])` — a stub card good enough to bootstrap the real card via `get_extended_agent_card()`.

---

## 3. Constructing a Client with `ClientFactory`

`ClientConfig` declares *your* preferences; `ClientFactory` reconciles them with the *card's* `supported_interfaces` and produces a `Client`.

```python
import httpx
from a2a.client import ClientFactory, ClientConfig
from a2a.utils import TransportProtocol

async def build_client(card, http: httpx.AsyncClient):
    config = ClientConfig(
        httpx_client=http,                 # reuse your client; don't let the SDK make one
        streaming=True,                    # consume server-sent events when the agent supports it
        polling=False,                     # see Section 6 for the polling alternative
        # Ordered preference. Empty list => JSON-RPC only.
        supported_protocol_bindings=[
            TransportProtocol.JSONRPC,     # 'JSONRPC'
            TransportProtocol.HTTP_JSON,   # 'HTTP+JSON'
        ],
        use_client_preference=False,       # honor the server's interface order (recommended)
        accepted_output_modes=["text/plain", "application/json"],
    )

    factory = ClientFactory(config)
    client = factory.create(card)          # -> Client; raises ValueError if no transport overlaps
    return client
```

How the factory selects a transport in `create(card)`:

| `use_client_preference` | Selection logic                                                              |
|-------------------------|------------------------------------------------------------------------------|
| `False` (default)       | Walk `card.supported_interfaces` in **server** order; pick the first binding also in your config. |
| `True`                  | Walk **your** `supported_protocol_bindings` in order; pick the first the card offers. |

Within the chosen binding it prefers a `1.0` interface, then `>1.0`, then `>=0.3`. If nothing overlaps, `create()` raises `ValueError('no compatible transports found.')`.

> **Rule**: Keep `use_client_preference=False` unless you have a hard reason. The server knows which of its transports is fastest or most featureful; overriding that is how you end up on a degraded path.

The one-shot helper `create_client` folds resolution + factory into a single `await` — good for scripts, but it builds a throwaway `ClientFactory` each call, so reuse a factory when talking to many agents:

```python
from a2a.client import create_client

# Accepts a URL (resolves the card for you) or an AgentCard directly.
client = await create_client("https://agent.example.com", client_config=config)
```

⚠️ gRPC needs more: install `a2a-sdk[grpc]` and provide a channel factory with trusted Transport Layer Security (TLS) roots. Plaintext `grpc.aio.insecure_channel` is not a production default.

```python
from pathlib import Path

import grpc

trusted_roots = Path("/etc/my-agent/trusted-ca.pem").read_bytes()
credentials = grpc.ssl_channel_credentials(root_certificates=trusted_roots)
config.grpc_channel_factory = lambda target: grpc.aio.secure_channel(
    target, credentials
)
```

Success is a completed TLS handshake to the hostname from the selected card interface. `CERTIFICATE_VERIFY_FAILED` means the configured roots or hostname do not match; do not bypass verification to make it connect.

---

## 4. Sending a Message

A turn is a `Message` carrying one or more `Part`s. In `1.0` these are protobuf types: `role` is the `Role` enum, and `Part` is a `oneof` — set exactly one of `text` / `data` / `raw` / `url`.

```python
from uuid import uuid4
from a2a.types import Message, Part, Role, SendMessageRequest

msg = Message(
    role=Role.ROLE_USER,                       # enum, NOT the string "user"
    message_id=f"msg-{uuid4()}",               # client-generated; make it unique
    parts=[
        Part(text="Summarize Q3 revenue."),    # a text part
        # Part(url="https://.../report.pdf", media_type="application/pdf"),
        # Part(raw=b"...bytes...", media_type="application/octet-stream"),
    ],
)

request = SendMessageRequest(message=msg)      # no context/task id => start a new task
```

`Client.send_message()` is **always an async iterator**, even for a non-streaming agent — `BaseClient` wraps a single non-streaming reply into a one-item stream so your code has one shape. Each item is a `StreamResponse`, a `oneof` over four cases:

| `StreamResponse` field | Meaning                                              |
|------------------------|------------------------------------------------------|
| `message`              | A direct reply — a **quick answer**, no task created |
| `task`                 | A **`Task`** snapshot — long-running work            |
| `status_update`        | `TaskStatusUpdateEvent` — a state transition         |
| `artifact_update`      | `TaskArtifactUpdateEvent` — an output chunk          |

```python
async for event in client.send_message(request=request):
    if event.HasField("message"):
        # Quick reply: the agent answered inline, nothing to track.
        print("reply:", event.message.parts[0].text)
    elif event.HasField("task"):
        # Long-running: hold on to BOTH ids for follow-ups / polling.
        task = event.task
        print(f"task {task.id} ctx {task.context_id} -> {task.status.state}")
```

> **Rule**: Never assume the response is a `Task`. A `message`-only reply has **no `task.id`** — code that does `event.task.id` unconditionally crashes the first time an agent answers a trivial question inline. Branch on `HasField` every time.

❌ Anti-pattern — assuming a task always exists:

```python
event = await anext(client.send_message(request=request))
task_id = event.task.id          # AttributeError when the agent sent a `message`
```

✅ Branch, then capture identity:

```python
task_id = context_id = None
async for event in client.send_message(request=request):
    if event.HasField("task"):
        task_id, context_id = event.task.id, event.task.context_id
    elif event.HasField("status_update"):
        task_id, context_id = event.status_update.task_id, event.status_update.context_id
```

---

## 5. Consuming a Stream

When the agent advertises `capabilities.streaming` and your `ClientConfig.streaming=True`, `send_message()` yields events live as the agent produces them. You consume the same `StreamResponse` `oneof`, plus the two update events.

```python
from dataclasses import dataclass

from a2a.types import TaskState


@dataclass
class StreamProgress:
    task_id: str = ""
    context_id: str = ""


async def run_streaming(client, request, progress: StreamProgress):

    async for event in client.send_message(request=request):
        if event.HasField("task"):
            # Initial snapshot — usually the first event of a long task.
            progress.task_id = event.task.id
            progress.context_id = event.task.context_id

        elif event.HasField("status_update"):
            upd = event.status_update          # TaskStatusUpdateEvent
            progress.task_id, progress.context_id = upd.task_id, upd.context_id
            print(f"state -> {TaskState.Name(upd.status.state)}")
            if upd.status.state == TaskState.TASK_STATE_INPUT_REQUIRED:
                return "needs_input"

        elif event.HasField("artifact_update"):
            upd = event.artifact_update        # TaskArtifactUpdateEvent
            for part in upd.artifact.parts:
                if part.text:
                    print(part.text, end="", flush=True)
            # `append` => concatenate onto a prior chunk; `last_chunk` => artifact done.

        elif event.HasField("message"):
            print("inline reply:", event.message.parts[0].text)

    return "done"
```

A typical long-task stream:

```
task            (status = TASK_STATE_SUBMITTED)
status_update   (TASK_STATE_WORKING)
artifact_update (append=False)            ← first chunk
artifact_update (append=True)             ← more chunks
artifact_update (append=True, last_chunk=True)
status_update   (TASK_STATE_COMPLETED)    ← terminal
```

`artifact_update.append` and `last_chunk` are the chunking protocol. Buffer per `artifact.artifact_id` or parallel artifacts will interleave.

⚠️ **Connection drops mid-stream.** A long SSE connection *will* be cut by a proxy idle timeout or a network blip. The `async for` then raises `httpx.ReadError` / `httpx.RemoteProtocolError` — it does **not** end cleanly. Catch it and **resume** with `subscribe()` using the `task_id` you captured, rather than re-sending the message (which would start a *new* task):

```python
import httpx
from a2a.types import SubscribeToTaskRequest

progress = StreamProgress()  # caller-owned: survives an exception inside the drain
try:
    status = await run_streaming(client, request, progress)
except (httpx.ReadError, httpx.RemoteProtocolError):
    if progress.task_id:                         # identity was captured before the drop
        async for event in client.subscribe(
            request=SubscribeToTaskRequest(id=progress.task_id)
        ):
            ...  # same StreamResponse handling as above
```

If the connection fails before any Task or status event populates `progress.task_id`, there is no safe subscription target. Do not resend unless the server documents durable deduplication for the original `messageId`; surface the indeterminate outcome instead.

---

## 6. Polling a Non-Streaming Task

Not every agent streams, and not every caller wants a held-open connection. Set `ClientConfig.polling=True`: the client sends `return_immediately`, so `send_message()` yields once with the *initial* `Task`, then you poll `get_task()` yourself.

```python
import asyncio
from a2a.types import GetTaskRequest, TaskState

TERMINAL = {
    TaskState.TASK_STATE_COMPLETED,
    TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED,
    TaskState.TASK_STATE_REJECTED,
}

async def poll_until_done(client, task_id, *, interval=2.0, max_wait=300.0):
    """Poll GetTask until the task reaches a terminal or input-required state."""
    waited = 0.0
    while waited < max_wait:
        task = await client.get_task(request=GetTaskRequest(id=task_id))
        state = task.status.state
        if state in TERMINAL or state == TaskState.TASK_STATE_INPUT_REQUIRED:
            return task
        await asyncio.sleep(interval)
        waited += interval
    raise TimeoutError(f"task {task_id} not done after {max_wait}s")
```

Handling `input-required` — the agent paused and needs more from you. Send a follow-up `Message` carrying the **same `task_id` and `context_id`** so the agent resumes the existing task instead of opening a new one:

```python
from uuid import uuid4
from a2a.types import Message, Part, Role, SendMessageRequest

async def answer_input_required(client, task, answer: str):
    followup = Message(
        role=Role.ROLE_USER,
        message_id=f"msg-{uuid4()}",
        task_id=task.id,                # <-- resumes THIS task
        context_id=task.context_id,     # <-- keeps the conversation thread
        parts=[Part(text=answer)],
    )
    async for event in client.send_message(
        request=SendMessageRequest(message=followup)
    ):
        if event.HasField("task"):
            return event.task
```

> **Rule**: `context_id` is the conversation thread; `task_id` is the unit of work. Drop either on a follow-up and the agent treats your message as a brand-new request — losing all prior context. The agent assigns both on the first response; **you echo them back**, never invent them.

❌ Dropping the ids — the agent forgets everything and starts over:

```python
followup = Message(role=Role.ROLE_USER, message_id=str(uuid4()),
                   parts=[Part(text=answer)])   # no task_id, no context_id
```

---

## 7. Passing Auth Credentials

Outgoing calls are authenticated with **interceptors**. `AuthInterceptor` reads the resolved card's `security_schemes` / `security_requirements` and attaches the right header per scheme — Bearer for `http`/`oauth2`/`openIdConnect`, an API-key header for `apiKey`.

It pulls the secret from a `CredentialService` you implement. `InMemoryContextCredentialStore` is the built-in, session-keyed implementation:

```python
import os

from a2a.client import (
    ClientFactory, AuthInterceptor, InMemoryContextCredentialStore, ClientCallContext,
)

# 1. Stock the store: keyed by sessionId, then by the card's security-scheme name.
store = InMemoryContextCredentialStore()
await store.set_credentials(
    session_id="session-abc",
    security_scheme_name="bearerAuth",        # MUST match a key in card.security_schemes
    credential=os.environ["A2A_BEARER_TOKEN"], # raw token; never log or hard-code it
)

# 2. Build the client with the interceptor wired in.
client = factory.create(card, interceptors=[AuthInterceptor(store)])

# 3. Each call carries a context whose state names the session to look up.
ctx = ClientCallContext(state={"sessionId": "session-abc"}, timeout=30.0)
async for event in client.send_message(request=request, context=ctx):
    ...
```

For service credentials, map each advertised scheme name to its own secret and fail closed when no credential was configured:

```python
import os

from a2a.client import CredentialService

class SchemeCredentialService(CredentialService):
    def __init__(self, credentials: dict[str, str]):
        self._credentials = credentials

    async def get_credentials(self, security_scheme_name, context):
        try:
            return self._credentials[security_scheme_name]
        except KeyError as exc:
            raise RuntimeError(
                f"No credential configured for scheme {security_scheme_name!r}"
            ) from exc

credentials = SchemeCredentialService({
    "bearerAuth": os.environ["A2A_BEARER_TOKEN"],
    "partnerKey": os.environ["A2A_PARTNER_API_KEY"],
})
client = factory.create(card, interceptors=[AuthInterceptor(credentials)])
```

The stock `AuthInterceptor` uses the first usable scheme, supports Bearer/OAuth/OpenID Connect and header API keys, and does not assemble every scheme in a compound AND requirement. For a requirement containing both `mtls` and `bearerAuth`, preflight the card and either configure the TLS client certificate plus Bearer header in a custom interceptor or reject that interface before sending:

```text
card requirement:  mtls AND bearerAuth
configured call:   client certificate + Authorization: Bearer <access-token>  -> send
missing mTLS cert:  Authorization header only                                -> reject locally
```

A `401` or `403` despite one attached credential is the tell that the server required the full compound set.

`AuthInterceptor` is a no-op when the card declares no security schemes. If authenticated calls return `401`, inspect the card and the exact scheme-name mapping first.

For OAuth2 client-credentials flows, token caching, and per-scope tokens, see **[Authentication](../05_production/01_authentication.md)**.

---

## 8. Complete Example

Discover an agent, send a streaming task, handle an `input-required` pause, and resume — production shape with an owned `httpx` client, timeouts, auth, and a bounded retry on resolution.

```python
"""a2a_client_demo.py — discover, send, stream, resume an A2A task."""
import asyncio
from dataclasses import dataclass
import os
from uuid import uuid4

import httpx

from a2a.client import (
    A2ACardResolver, ClientFactory, ClientConfig,
    AuthInterceptor, CredentialService,
    AgentCardResolutionError, A2AClientError,
)
from a2a.types import (
    Message, Part, Role, SendMessageRequest, SubscribeToTaskRequest, TaskState,
)
from a2a.utils import TransportProtocol

AGENT_URL = "https://agent.example.com"

TERMINAL = {
    TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED,
    TaskState.TASK_STATE_CANCELED, TaskState.TASK_STATE_REJECTED,
}


class SchemeCredentialService(CredentialService):
    def __init__(self, credentials: dict[str, str]):
        self._credentials = credentials

    async def get_credentials(self, security_scheme_name, context):
        if security_scheme_name not in self._credentials:
            raise RuntimeError(f"No credential for {security_scheme_name!r}")
        return self._credentials[security_scheme_name]


@dataclass
class StreamProgress:
    task_id: str = ""
    context_id: str = ""


def user_message(text: str, *, task_id: str = "", context_id: str = "") -> SendMessageRequest:
    """Build a SendMessageRequest. Echo task_id/context_id to continue a task."""
    return SendMessageRequest(
        message=Message(
            role=Role.ROLE_USER,
            message_id=f"msg-{uuid4()}",
            task_id=task_id,            # empty string => new task
            context_id=context_id,
            parts=[Part(text=text)],
        )
    )


async def drain_stream(stream, progress: StreamProgress) -> str:
    """Consume an event stream while exposing captured identity to the caller."""
    async for event in stream:
        if event.HasField("task"):
            progress.task_id = event.task.id
            progress.context_id = event.task.context_id

        elif event.HasField("status_update"):
            upd = event.status_update
            progress.task_id, progress.context_id = upd.task_id, upd.context_id
            state = upd.status.state
            print(f"  [status] {TaskState.Name(state)}")
            if state == TaskState.TASK_STATE_INPUT_REQUIRED:
                return "needs_input"
            if state in TERMINAL:
                return "done"

        elif event.HasField("artifact_update"):
            for part in event.artifact_update.artifact.parts:
                if part.text:
                    print(f"  [artifact] {part.text}")

        elif event.HasField("message"):
            print(f"  [reply] {event.message.parts[0].text}")
            return "done"

    return "stream_ended"


async def resolve_with_retry(resolver: A2ACardResolver, attempts: int = 3):
    """Resolve the card with a bounded exponential backoff on transient failure."""
    for attempt in range(1, attempts + 1):
        try:
            return await resolver.get_agent_card()
        except AgentCardResolutionError as e:
            if attempt == attempts:
                raise
            backoff = 2 ** attempt
            print(f"resolve failed ({e}); retry in {backoff}s")
            await asyncio.sleep(backoff)


async def main() -> None:
    # One httpx client for the whole session: card fetch + every RPC. Always timed.
    async with httpx.AsyncClient(timeout=30.0) as http:
        # 1. Discover the agent.
        resolver = A2ACardResolver(httpx_client=http, base_url=AGENT_URL)
        card = await resolve_with_retry(resolver)
        print(f"Discovered: {card.name} (streaming={card.capabilities.streaming})")

        # 2. Build a transport-agnostic client with auth wired in.
        config = ClientConfig(
            httpx_client=http,
            streaming=card.capabilities.streaming,   # stream only if the agent can
            supported_protocol_bindings=[
                TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON,
            ],
        )
        factory = ClientFactory(config)
        credential_service = SchemeCredentialService({
            "bearerAuth": os.environ["A2A_BEARER_TOKEN"],
        })
        client = factory.create(card, interceptors=[AuthInterceptor(credential_service)])

        async with client:                          # closes transport on exit
            # 3. Send the initial task and stream its events.
            print("Sending task...")
            progress = StreamProgress()
            try:
                outcome = await drain_stream(
                    client.send_message(request=user_message(
                        "Generate a Q3 revenue report for the EMEA region."
                    )), progress
                )
            except (httpx.ReadError, httpx.RemoteProtocolError) as e:
                # 3b. Connection dropped mid-stream — resume, don't re-send.
                if not progress.task_id:
                    raise RuntimeError("stream outcome unknown; no task id captured") from e
                print(f"stream dropped ({e}); resubscribing to {progress.task_id}")
                outcome = await drain_stream(
                    client.subscribe(request=SubscribeToTaskRequest(id=progress.task_id)),
                    progress,
                )

            # 4. Handle an input-required pause with a follow-up on the SAME ids.
            if outcome == "needs_input":
                print(f"Agent needs input on task {progress.task_id}")
                outcome = await drain_stream(
                    client.send_message(request=user_message(
                        "Use calendar quarters; revenue in EUR.",
                        task_id=progress.task_id, context_id=progress.context_id,
                    )), progress
                )

            print(f"Final outcome: {outcome} (task {progress.task_id or 'n/a'})")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except A2AClientError as e:
        print(f"A2A call failed: {e}")
```

> **Rule**: Wrap the `Client` in `async with` (or call `await client.close()`). It owns transport-level resources — gRPC channels, SSE connections — that leak if you don't release them.

---

## 9. Failure Modes Checklist

| Mistake | Symptom | Fix |
|---|---|---|
| Treating the response as always a `Task` | `AttributeError` on `event.task.id` for a `message` reply | Branch on `event.HasField("message" / "task")` every time |
| Dropping `context_id` / `task_id` on a follow-up | Agent ignores history, starts a fresh task | Echo both ids from the prior response into the new `Message` |
| No `timeout` on `httpx.AsyncClient` | A hung agent hangs your process forever | `httpx.AsyncClient(timeout=30.0)`; set `ClientCallContext.timeout` per call |
| No retry on card resolution | One transient `5xx`/DNS blip aborts the run | Bounded exponential backoff around `get_agent_card()` |
| Not handling a mid-stream drop | `httpx.ReadError` ends the `async for` uncleanly | Catch it, `subscribe()` with the captured `task_id` to resume |
| Re-sending the message to "retry" a stream | A duplicate task runs on the agent | Resume with `subscribe()`, never re-`send_message()` |
| Letting the SDK create its own `httpx` client | No connection reuse; resources leak | Pass your own `httpx_client` into `ClientConfig` and reuse it |
| Not closing the `Client` | Leaked gRPC channels / open SSE sockets | `async with client:` or `await client.close()` |
| Auth scheme name mismatch | Silent `401` — `AuthInterceptor` attaches nothing | The `security_scheme_name` must match a key in `card.security_schemes` |
| Polling with no upper bound | A stuck task loops forever | Cap total wait (`max_wait`) and treat the cap as `TimeoutError` |

> **Key insight**: The two failures that bite hardest are both about **identity and shape** — assuming `Task` vs `Message`, and losing `task_id`/`context_id`. Get those right and the rest is ordinary networking hygiene: timeouts, bounded retries, and resuming instead of re-sending.

---

**Next**: [Part 1: LangChain & LangGraph](../04_frameworks/01_langchain_langgraph.md)
