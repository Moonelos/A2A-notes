# The Agent Card

> **Who this is for**: Engineers implementing or consuming A2A who have already read the [Core Concepts](../01_fundamentals/02_core_concepts.md). You know what an agent, task, and message are — this file is the precise field-by-field reference for the document that makes an agent *discoverable*.

The **Agent Card** is A2A's "digital business card": a single JSON document that tells any client what an agent is, where to reach it, how to authenticate, and what it can do. Everything in an A2A interaction starts here — a client cannot send a task until it has resolved a card. This file targets wire protocol **1.0** and was checked against specification release **1.0.1**.

---

## 1. What the Agent Card Is

An Agent Card is a static (or near-static) JSON object. It is *not* an endpoint you call for work — it is metadata the client reads once, caches, and uses to construct every subsequent request.

```
┌──────────────┐   1. GET card     ┌────────────────────────────┐
│    Client    │ ────────────────→ │ /.well-known/agent-card.json│
│              │ ←──────────────── │      (AgentCard JSON)       │
└──────┬───────┘   2. card body    └────────────────────────────┘
       │
       │ 3. read `supportedInterfaces` + auth requirements
       ↓
┌──────────────┐   4. SendMessage  ┌────────────────────────────┐
│    Client    │ ────────────────→ │   Agent service endpoint    │
└──────────────┘   (authenticated) └────────────────────────────┘
```

> **Key insight**: The card is the *contract surface*. If a field is wrong here — a stale `url`, a missing security scheme, an unsupported transport — the client fails before it ever reaches your agent logic. Treat the card as production API surface, not documentation.

Cards change infrequently (a new skill, a changed auth requirement), so they are designed to be HTTP-cached aggressively with `Cache-Control` and `ETag`.

---

## 2. The Full AgentCard Schema (protocol 1.0)

Every field of the top-level `AgentCard` object:

| Field | Type | Req. | Purpose |
|---|---|:--:|---|
| `name` | string | yes | Human-readable agent name. |
| `description` | string | yes | What the agent does; shown in catalogs and to users. |
| `supportedInterfaces` | `AgentInterface[]` | yes | Ordered transport/interface list. The first entry is preferred. |
| `provider` | `AgentProvider` | no | Organization that operates the agent. |
| `version` | string | yes | Agent *implementation* version (your own semver, not the protocol). |
| `documentationUrl` | string (URI) | no | Link to human-readable docs. |
| `capabilities` | `AgentCapabilities` | yes | Optional protocol features the agent supports. |
| `defaultInputModes` | string[] | yes | Default accepted input media types (MIME), e.g. `text/plain`. |
| `defaultOutputModes` | string[] | yes | Default produced output media types (MIME). |
| `skills` | `AgentSkill[]` | yes | The discrete capabilities the agent exposes. |
| `securitySchemes` | map<string, `SecurityScheme`> | no | Named auth schemes, expressed as an OpenAPI-inspired protobuf oneof. |
| `securityRequirements` | `SecurityRequirement[]` | no | Which scheme(s) and scopes a client must satisfy. |
| `signatures` | `AgentCardSignature[]` | no | JWS signatures over the card (see §7). |
| `iconUrl` | string (URI) | no | Optional icon for catalogs and UIs. |

> **Rule**: `supportedInterfaces` is the v1.0 transport declaration. There is no top-level `url`, `preferredTransport`, or `additionalInterfaces` in the canonical v1.0 schema. Clients choose the first interface whose `protocolBinding` they support.

### 2.1 AgentCapabilities

```json
{
"capabilities": {
  "streaming": true,
  "pushNotifications": true,
  "extendedAgentCard": false,
  "extensions": []
}
}
```

| Field | Type | Meaning |
|---|---|---|
| `streaming` | boolean | Supports streaming operations and SSE-based incremental updates. |
| `pushNotifications` | boolean | Supports webhook push config for long-running tasks. |
| `extensions` | `AgentExtension[]` | Declared protocol extensions the agent honors. |
| `extendedAgentCard` | boolean | Supports the authenticated extended-card operation. |

All capability flags are optional and **default to `false`** when absent. A client must never assume streaming works just because the agent looks modern — check the flag.

### 2.2 AgentInterface

```json
{
"supportedInterfaces": [
  {
    "url": "https://api.example.com/a2a/jsonrpc",
    "protocolBinding": "JSONRPC",
    "protocolVersion": "1.0"
  },
  {
    "url": "https://api.example.com/a2a/grpc",
    "protocolBinding": "GRPC",
    "protocolVersion": "1.0"
  },
  {
    "url": "https://api.example.com/a2a/rest",
    "protocolBinding": "HTTP+JSON",
    "protocolVersion": "1.0"
  }
]
}
```

Each `AgentInterface` declares a URL, an optional `tenant`, and the A2A protocol version at that interface. `protocolBinding` is an extensible string: `JSONRPC`, `GRPC`, and `HTTP+JSON` are the three core identifiers, while custom bindings use URI identifiers. A client skips a custom identifier it does not support and continues through the ordered list; it does not reject the whole card.

### 2.3 AgentProvider

```json
{
"provider": {
  "organization": "Acme FinOps Inc.",
  "url": "https://acme-finops.example.com"
}
}
```

`organization` and `url` only — identity of who runs the agent, useful for trust decisions and catalog grouping.

---

## 3. The AgentSkill Object

A **skill** is a discrete capability. The `skills` array is what makes an agent useful in capability-based discovery — registries index on skill `tags`.

```json
{
  "id": "reconcile-invoices",
  "name": "Invoice Reconciliation",
  "description": "Matches vendor invoices against purchase orders and ERP payment records, flagging discrepancies.",
  "tags": ["finance", "accounts-payable", "reconciliation", "erp"],
  "examples": [
    "Reconcile all open invoices for vendor ACME-2024 against PO batch Q1.",
    "Why was invoice INV-88213 flagged as a mismatch?"
  ],
  "inputModes": ["text/plain", "application/json", "text/csv"],
  "outputModes": ["application/json", "text/markdown"],
  "securityRequirements": [
    { "schemes": { "oauth2-clientcreds": { "list": ["invoices:reconcile"] } } }
  ]
}
```

| Field | Type | Req. | Purpose |
|---|---|:--:|---|
| `id` | string | yes | Unique skill identifier within the card. |
| `name` | string | yes | Human-readable skill name. |
| `description` | string | yes | What the skill does. |
| `tags` | string[] | yes | Searchable categories — the primary discovery key. |
| `examples` | string[] | no | Sample prompts/inputs that exercise the skill. |
| `inputModes` | string[] | no | MIME types this skill accepts; **overrides** `defaultInputModes`. |
| `outputModes` | string[] | no | MIME types this skill produces; **overrides** `defaultOutputModes`. |
| `securityRequirements` | `SecurityRequirement[]` | no | Schemes/scopes required for this skill; overrides the card-level default for this skill. |

Skill-level input/output modes and security requirements specialize that skill only. Put the common case at card level, then override the exception — for example a bulk reconciliation skill that accepts `text/csv` and requires `invoices:reconcile`.

---

## 4. Discovery

A client must obtain a card before doing anything. A2A defines three discovery strategies.

### 4.1 Well-Known URI (RFC 8615)

The standard, recommended path for publicly discoverable agents:

```
https://{domain}/.well-known/agent-card.json
```

```bash
curl -i https://acme-finops.example.com/.well-known/agent-card.json
```

Success is `HTTP/2 200`, a schema-valid card, and at least one `supportedInterfaces` entry the client can select. A `404` usually means the server still publishes the legacy path or the reverse proxy did not route `/.well-known/agent-card.json`. If the fetch succeeds but clients keep using old metadata, inspect `ETag`/`Cache-Control` and invalidate the stale cached card.

> ⚠️ **The `agent.json` gotcha**: A2A **0.2.x** and a large amount of third-party blog content, tutorials, and SDK examples still reference `/.well-known/agent.json`. **That path was renamed to `agent-card.json`.** As of v1.0.0 the canonical path is `agent-card.json` — treat `agent.json` as **legacy**. If you are consuming a third-party agent and the new path 404s, the agent may be old; if you are *publishing*, serve `agent-card.json` (optionally also serving the legacy path as a redirect for backward compatibility). Do not copy `agent.json` from an old blog post.

### 4.2 Registry / Catalog Discovery

A centralized intermediary holds many Agent Cards. Clients query a registry API by criteria — skill `tags`, provider, capabilities — enabling **capability-based discovery** ("find me an agent that can do `reconciliation`"). Best for ecosystems where agents come and go.

### 4.3 Direct Configuration

The client is handed the card (or its URL) out-of-band: a config file, environment variable, or hardcoded value. Best for tightly coupled, private deployments where discovery flexibility is unnecessary.

| Strategy | Best for | Trade-off |
|---|---|---|
| Well-known URI | Public agents, broad reach | One default card per domain path unless you add tenant/query routing |
| Registry/catalog | Dynamic ecosystems, search | Needs a registry service |
| Direct config | Private, fixed integrations | No runtime discovery |

---

## 5. Input / Output Modes

`defaultInputModes` and `defaultOutputModes` are **MIME-type arrays** declaring what content the agent can consume and produce by default. They are mandatory — a client uses them to decide whether it can even talk to the agent.

```json
{
"defaultInputModes":  ["text/plain", "application/json"],
"defaultOutputModes": ["application/json", "text/markdown"]
}
```

Resolution order for a given skill: skill-level `inputModes`/`outputModes` if present, otherwise the card-level defaults. A client constructing a message should pick a mode present in this set. An unsupported Message Part or Artifact media type maps to `ContentTypeNotSupportedError`; this is a defined protocol failure, not undefined behavior.

---

## 6. The Authenticated Extended Card

A public card at the well-known URI is, by definition, visible to anyone. You often want to expose *more* (internal skills, privileged endpoints, richer descriptions) only to authenticated clients.

A2A solves this with the **Authenticated Extended Card**:

1. The public card sets `"capabilities": { "extendedAgentCard": true }`.
2. An authenticated client calls **`GetExtendedAgentCard`** against the agent's service endpoint (or `GET /extendedAgentCard` on the HTTP+JSON binding).
3. The agent returns a fuller `AgentCard` — potentially with extra `skills`, internal interfaces, or more detailed metadata.

```
Public card (well-known)          Extended card (authenticated)
┌─────────────────────────┐       ┌─────────────────────────────┐
│ skills: [reconcile]     │       │ skills: [reconcile,          │
│ capabilities.extended   │  →    │          bulk-export,        │
│   AgentCard: true       │       │          admin-audit]       │
└─────────────────────────┘       └─────────────────────────────┘
        anyone can GET                 only authenticated clients
```

> **Rule**: `GetExtendedAgentCard` is an authenticated operation, not a public well-known URL. The client authenticates using a scheme from the public card's `securitySchemes`, then calls the operation. The response is a complete `AgentCard` and should be treated as authoritative for that authenticated session.

The extended card lets you keep the public surface minimal (good for security and signal-to-noise) while still serving internal consumers a complete picture.

---

## 7. Signed Cards (JWS)

A card fetched over HTTPS is confidential and tamper-resistant *in transit*, but a client may receive a card from a registry, a cache, or a third party. **Signed cards** prove the card was issued by a trusted key and has not been altered.

A2A uses **JSON Web Signature (JWS, RFC 7515)**. Signatures live in the top-level `signatures` array as `AgentCardSignature` objects, in JWS *detached* / flattened form:

```json
{
"signatures": [
  {
    "protected": "eyJhbGciOiJSUzI1NiIsImtpZCI6ImtleS0yMDI2LTAxIn0",
    "signature": "MEUCIQDxr...base64url-detached-signature...Qm0g"
  }
]
}
```

| Field | Type | Purpose |
|---|---|---|
| `protected` | string | base64url-encoded JWS protected header (`alg`, `kid`, etc.). |
| `signature` | string | base64url-encoded signature over the protected header + card payload. |
| `header` | object | Optional unprotected JWS header. |

Verification must reproduce the exact bytes that were signed:

1. Parse the card while preserving Protocol Buffers field presence. Omit unset optional fields; keep explicitly set optional defaults and every required field; omit empty/default non-required fields such as an empty repeated field.
2. Remove the top-level `signatures` field, then serialize the remaining object with **JSON Canonicalization Scheme (JCS, RFC 8785)**: lexicographically ordered keys, canonical numbers/strings, and no insignificant whitespace.
3. Decode the protected header but do not trust it as policy. Require `typ: "JOSE"`, require `alg` to be in the verifier's configured allowlist, and resolve `kid` from a trusted key store or from a validated HTTPS `jku`. A generic `provider.url` is not a key-discovery mechanism.
4. Reject an expired or revoked key. Construct the detached JWS signing input as `BASE64URL(protected-header-bytes) + "." + BASE64URL(canonical-card-bytes)` and verify with the selected trusted key.
5. Accept the card only when at least one complete signature verifies under that policy; otherwise reject it.

This matters most when cards flow through untrusted registries, caches, or marketplaces. Multiple signatures support rotation and multi-party attestation, but an extra signature never excuses a failed algorithm, key-source, or canonicalization check.

For how `securitySchemes`/`securityRequirements` interact with actual request authentication (OAuth2, API keys, mTLS), see [Authentication](../05_production/01_authentication.md).

---

## 8. Complete Example: Invoice-Reconciliation Agent

A realistic, full protocol 1.0 Agent Card:

```json
{
  "name": "Invoice Reconciliation Agent",
  "description": "Reconciles vendor invoices against purchase orders and ERP payment records, flags discrepancies, and explains mismatches in plain language.",
  "supportedInterfaces": [
    {
      "url": "https://agents.acme-finops.example.com/a2a/jsonrpc",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    },
    {
      "url": "https://agents.acme-finops.example.com/a2a/grpc",
      "protocolBinding": "GRPC",
      "protocolVersion": "1.0"
    },
    {
      "url": "https://agents.acme-finops.example.com/a2a/rest",
      "protocolBinding": "HTTP+JSON",
      "protocolVersion": "1.0"
    }
  ],
  "provider": {
    "organization": "Acme FinOps Inc.",
    "url": "https://acme-finops.example.com"
  },
  "version": "2.4.1",
  "documentationUrl": "https://docs.acme-finops.example.com/agents/invoice-reconciliation",
  "capabilities": {
    "streaming": true,
    "pushNotifications": true,
    "extendedAgentCard": true,
    "extensions": []
  },
  "defaultInputModes": ["text/plain", "application/json"],
  "defaultOutputModes": ["application/json", "text/markdown"],
  "skills": [
    {
      "id": "reconcile-invoices",
      "name": "Invoice Reconciliation",
      "description": "Matches a batch of vendor invoices against purchase orders and recorded ERP payments, returning matched, mismatched, and unmatched line items.",
      "tags": ["finance", "accounts-payable", "reconciliation", "erp"],
      "examples": [
        "Reconcile all open invoices for vendor ACME-2024 against PO batch Q1-2026.",
        "Why was invoice INV-88213 flagged as a mismatch?"
      ],
      "inputModes": ["text/plain", "application/json", "text/csv"],
      "outputModes": ["application/json", "text/markdown"],
      "securityRequirements": [
        {
          "schemes": {
            "oauth2-clientcreds": { "list": ["invoices:reconcile"] }
          }
        }
      ]
    },
    {
      "id": "discrepancy-explainer",
      "name": "Discrepancy Explainer",
      "description": "Produces a plain-language explanation for a single flagged discrepancy, citing the conflicting source records.",
      "tags": ["finance", "explainability", "reconciliation"],
      "examples": [
        "Explain the $412.50 variance on invoice INV-88213."
      ]
    }
  ],
  "securitySchemes": {
    "oauth2-clientcreds": {
      "oauth2SecurityScheme": {
        "description": "Acme corporate OAuth2 server",
        "flows": {
          "clientCredentials": {
            "tokenUrl": "https://auth.acme-finops.example.com/oauth2/token",
            "scopes": {
              "invoices:read": "Read invoice and reconciliation data",
              "invoices:reconcile": "Trigger reconciliation runs"
            }
          }
        }
      }
    }
  },
  "securityRequirements": [
    {
      "schemes": {
        "oauth2-clientcreds": {
          "list": ["invoices:read", "invoices:reconcile"]
        }
      }
    }
  ],
  "signatures": [
    {
      "protected": "eyJhbGciOiJSUzI1NiIsImtpZCI6ImFjbWUtZmlub3BzLWtleS0yMDI2LTAxIn0",
      "signature": "QFdC8oZ3a1f...base64url-detached-jws-signature...kP9rXn2Qw"
    }
  ]
}
```

Note how this card combines every concept above: ordered `supportedInterfaces`, capability flags explicitly set, a skill that overrides input modes and narrows authorization, an OAuth2 entry referenced by card- and skill-level requirements, the extended-card opt-in, and a JWS signature for catalog trust.

> 💡 Validate your card against the published schema in CI, then run a selection test that proves a client can choose an advertised interface. Schema success alone does not catch a stale URL or unsupported binding. A discovery check should report the `200`, selected binding, and protocol `1.0`; a `404` or "no compatible interface" is the actionable failure.

---

**Next**: [Part 2: Transport & RPC](02_transport_and_rpc.md)
