# Protocol

> The A2A wire protocol: how agents are discovered, how requests are transported, and how work is modelled as Tasks.

[![A2A](https://img.shields.io/badge/A2A-spec_1.0.0-4285F4.svg)](https://a2a-protocol.org/latest/specification/)
[![JSON-RPC](https://img.shields.io/badge/JSON--RPC-2.0-F7DF1E.svg)](https://www.jsonrpc.org/specification)

---

## Contents

| File | Topic | Description |
|------|-------|-------------|
| [01_agent_card.md](01_agent_card.md) | Discovery | Agent Card schema, skills, well-known URI discovery, signed and extended cards |
| [02_transport_and_rpc.md](02_transport_and_rpc.md) | Transport | JSON-RPC 2.0, gRPC, and HTTP+JSON bindings; the full RPC method set |
| [03_task_lifecycle.md](03_task_lifecycle.md) | Task model | The Task state machine, terminal states, input/auth pauses, and error codes |
| [04_streaming_and_push.md](04_streaming_and_push.md) | Async results | SSE streaming and push-notification webhooks for long-running work |

---

## Reading Order

1. **The Agent Card** — discovery comes before any call
2. **Transport & RPC** — how a request actually travels
3. **Task Lifecycle** — the unit of work and its states
4. **Streaming & Push** — delivering results that take time

---

## Prerequisites

- [Core Concepts](../01_fundamentals/02_core_concepts.md) — the vocabulary used throughout
- Working knowledge of HTTP request/response and status codes
