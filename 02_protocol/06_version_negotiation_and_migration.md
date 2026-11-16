# Protocol-Version Negotiation & Migration

> **Who this is for**: Teams rolling A2A 1.0 into a fleet that still contains v0.3 clients or servers.

Wire compatibility is declared as Major.Minor (`1.0`), while this repository is checked against specification patch release 1.0.1. The client selects an advertised interface/version and sends `A2A-Version: 1.0` on every HTTP request. An empty header is interpreted as legacy `0.3`; it is not a safe way to request “latest.”

## The request contract

This is the HTTP+JSON binding; its A2A JSON media type differs from the `application/json` used by JSON-RPC examples.

```http
POST /message:send HTTP/1.1
Host: agent.example
A2A-Version: 1.0
Content-Type: application/a2a+json
Authorization: Bearer <a2a-client-token>

{"message":{"messageId":"msg-version-1","role":"ROLE_USER","parts":[{"text":"What is 2 + 2?"}]}}
```

The server either processes that version or returns the binding-specific `VersionNotSupportedError`. Clients must not retry the same interface without a version or reinterpret a 1.0 response as 0.3.

### What the version failure actually looks like

Suppose this HTTP+JSON interface accepts `1.0`, but a test client changes only the header above to `A2A-Version: 0.5`. A representative version failure is:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/a2a+json

{
  "error": {
    "code": 400,
    "status": "FAILED_PRECONDITION",
    "message": "Requested A2A version 0.5 is not supported",
    "details": [{
      "@type": "type.googleapis.com/google.rpc.ErrorInfo",
      "reason": "VERSION_NOT_SUPPORTED",
      "domain": "a2a-protocol.org"
    }]
  }
}
```

This follows the [1.0 HTTP+JSON error binding](https://a2a-protocol.org/v1.0.0/specification/#116-error-handling) and [SDK 1.1.2 error serializer](https://github.com/a2aproject/a2a-python/blob/v1.1.2/src/a2a/utils/error_handlers.py), checked 2026-11-16: `error.code` is the HTTP numeric code and `status` carries the mapped status name. The human wording is illustrative; `details` identifies the A2A-specific failure. This body is neither a JSON-RPC `error` envelope nor a Task in `FAILED`: version selection failed before a Task exchange. For the JSON-RPC binding the corresponding native code is `-32009` inside an HTTP 200 JSON-RPC error response.

### Compare one legacy exchange with its 1.0 equivalent

A header change alone cannot migrate serialized data. Below are complete illustrative JSON-RPC bodies for the same calculation, sent to **separately selected** endpoints. Each request uses that endpoint's version/authentication configuration; readable IDs stand in for generated IDs. These are alternative runs, not two turns of one conversation.

**v0.3 request** — legacy JSON-RPC method and discriminated Part/Message shapes:

```json
{"jsonrpc":"2.0","id":"legacy-math-1","method":"message/send","params":{"message":{"kind":"message","messageId":"msg-math-001","role":"user","parts":[{"kind":"text","text":"What is 2 + 2?"}]}}}
```

**v0.3 direct reply** — the Message itself is `result`:

```json
{"jsonrpc":"2.0","id":"legacy-math-1","result":{"kind":"message","messageId":"msg-math-002","contextId":"ctx-math-001","role":"agent","parts":[{"kind":"text","text":"2 + 2 = 4"}]}}
```

**v1.0 request** — PascalCase operation, enum role and unified Part:

```json
{"jsonrpc":"2.0","id":"v1-math-1","method":"SendMessage","params":{"message":{"messageId":"msg-math-001","role":"ROLE_USER","parts":[{"text":"What is 2 + 2?"}]}}}
```

**v1.0 direct reply** — `result` is now a SendMessageResponse containing `message`:

```json
{"jsonrpc":"2.0","id":"v1-math-1","result":{"message":{"messageId":"msg-math-002","contextId":"ctx-math-001","role":"ROLE_AGENT","parts":[{"text":"2 + 2 = 4"}]}}}
```

Follow the four changes: `message/send` → `SendMessage`, `user`/`agent` → enum names, removal of `kind`, and addition of `result.message`. Task-producing replies likewise need version-specific decoding; 1.0 streaming uses typed `StreamResponse` variants instead of the old discriminators/final flag. The Message ID and text keep their purpose while their surrounding schema changes. The [v0.3 schema](https://github.com/a2aproject/A2A/blob/v0.3.0/specification/json/a2a.json) and [v1.0.1 protobuf contract](https://github.com/a2aproject/A2A/blob/v1.0.1/specification/a2a.proto) define these shapes (checked 2026-11-16). Use the [cross-binding comparison](02_transport_and_rpc.md#the-same-message-over-httpjson-and-grpc) when the migration also changes transport.

## A dual-stack selection trace

Suppose the cached Agent Card contains these two `supportedInterfaces` entries (an excerpt from a larger card):

```json
[
  {"url":"https://agent.example/v1","protocolBinding":"HTTP+JSON","protocolVersion":"1.0"},
  {"url":"https://agent.example/v03","protocolBinding":"HTTP+JSON","protocolVersion":"0.3"}
]
```

A 1.0 client selects `/v1`, serializes a 1.0 Message, and sends `A2A-Version: 1.0`. If `/v1` has been retired since the card was cached, a version-not-supported response means the *selected endpoint and cached advertisement* disagree. The client refetches the card, then selects again from what is currently advertised. It does not remove the header and retry `/v1`: an absent header selects the legacy interpretation and could deserialize the same bytes under a different schema. The [A2A specification's version negotiation and HTTP+JSON rules](https://a2a-protocol.org/latest/specification/) describe the service parameter and binding (checked 2026-10-12).

Follow the decision branches when a mixed fleet changes under a client.

```mermaid
flowchart TD
  A[Read supportedInterfaces] --> B{Advertised 1.0 HTTP+JSON interface?}
  B -- yes --> C[Select /v1; send A2A-Version: 1.0]
  B -- no --> D{Client explicitly supports 0.3?}
  D -- yes --> E[Select /v03 and 0.3 serializer]
  D -- no --> F[Stop: incompatible version]
  C --> G{VersionNotSupportedError?}
  G -- yes --> H[Refetch card; reselect or stop]
  G -- no --> I[Process 1.0 response]
```

The 0.3 branch requires a client with a tested 0.3 serializer. A 1.0-only client stops even if a freshly fetched card offers `/v03`; H never means silently dropping `A2A-Version` on the same URL.

## A staged v0.3 → v1.0 rollout

1. Inventory clients, servers, cards, bindings, and SDK pins. Record which 0.3-only operations or field shapes are still used.
2. Add contract tests for both versions before changing routing. Keep separate serializers/models at the boundary; do not mix 0.3 and 1.0 objects inside business logic.
3. Publish explicit `supportedInterfaces` entries for the versions you truly serve. Prefer separate URLs when that makes routing and retirement observable.
4. Upgrade servers first while retaining a measured compatibility path. Require clients to send the version explicitly and emit metrics by version/interface/error.
5. Upgrade clients to select a compatible card interface and send the service parameter on every request.
6. Drain 0.3 traffic, announce a deadline, then remove the old interface and compatibility code. A stale card should fail clearly, not fall through to another schema.

## Mixed-fleet test matrix

| Client | Server | Expected result |
|---|---|---|
| 1.0 | advertises/accepts 1.0 | Success; response uses 1.0 shapes |
| 1.0 | 0.3 only | Client selects an explicitly supported 0.3 compatibility path or stops |
| 0.3 | dual-stack | Legacy path works and is counted |
| any | unsupported version header | Binding-native version-not-supported failure |
| any | stale interface URL/version | Clear failure; refetch card, then reselect |

Run lifecycle, streaming, push, auth, and error tests for each advertised version. A successful `SendMessage` alone does not prove that continuation or task resource operations are compatible.

> **Key insight**: Version negotiation is explicit selection, not hopeful fallback. Advertise only what the endpoint implements, send the chosen version on every call, and make legacy traffic measurable before removing it.

## What's changing

The [A2A roadmap](https://github.com/a2aproject/A2A/blob/main/docs/roadmap.md) (checked 2026-10-12) proposes 1.1 task timeline and event filtering semantics. A proposed version is not an advertised compatible interface; keep the explicit 1.0/0.3 selection and contract tests until a release and migration rules exist.

## Decision exercise

**Q: A cached card advertises `/v1`, but the endpoint returns `VersionNotSupportedError`. A refetched card advertises only `/v03`. What should a 1.0-only client do?**

<details><summary>Answer</summary>

Stop with an incompatible-version error. The refetch repairs stale discovery, but it does not add a 0.3 serializer or tested behavior to this client. Dropping the version header or reusing 1.0 shapes at `/v03` would reinterpret a request under the wrong contract.

</details>

---

**Next**: [Agent Payments with AP2](07_agent_payments_ap2.md)
