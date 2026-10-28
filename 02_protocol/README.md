# Protocol

> The A2A wire protocol: how agents are discovered, how requests are transported, and how work is modelled as Tasks.

[![A2A](https://img.shields.io/badge/A2A-wire_1.0_%7C_spec_1.0.1-4285F4.svg)](https://a2a-protocol.org/latest/specification/)
[![JSON-RPC](https://img.shields.io/badge/JSON--RPC-2.0-F7DF1E.svg)](https://www.jsonrpc.org/specification)

---

## Contents

| File | Topic | Description |
|------|-------|-------------|
| [00_client_server_walkthrough.md](00_client_server_walkthrough.md) | Worked interaction | Exact client Messages, replies, streaming frames, custom progress and a local network lab |
| [01_agent_card.md](01_agent_card.md) | Discovery | Agent Card schema, skills, well-known URI discovery, signed and extended cards |
| [02_transport_and_rpc.md](02_transport_and_rpc.md) | Transport | JSON-RPC 2.0, gRPC, and HTTP+JSON bindings; the full RPC method set |
| [03_task_lifecycle.md](03_task_lifecycle.md) | Task model | The Task state machine, terminal states, input/auth pauses, and error codes |
| [04_streaming_and_push.md](04_streaming_and_push.md) | Async results | Polling, first subscription/reconnect, SSE, push and terminal-race recovery |
| [05_extensions_and_custom_bindings.md](05_extensions_and_custom_bindings.md) | Extensibility | Declaration, request activation, dependencies, and custom-binding boundary |
| [06_version_negotiation_and_migration.md](06_version_negotiation_and_migration.md) | Compatibility | Required version selection and a staged v0.3-to-v1.0 rollout |
| [07_agent_payments_ap2.md](07_agent_payments_ap2.md) | Payments | A bounded map of AP2 mandates layered onto A2A tasks |

---

## Reading Order

Start with **[Follow the Messages](00_client_server_walkthrough.md)** if you want to see actual exchanges before the reference chapters. It uses the local lab endpoint; the discovery chapter explains how real callers find other agents.

1. **The Agent Card** — discovery comes before any call
2. **Transport & RPC** — sufficient stop for synchronous message exchange
3. **Task Lifecycle** — continue for durable or multi-turn work
4. **Streaming & Push** — continue for disconnected or incremental delivery
5. **Extensions & Bindings** and **Version Migration** — continue when the baseline protocol is not enough or a fleet is mixed-version
6. **Agent Payments with AP2** — optional domain branch for commerce systems

---

## Prerequisites

- [Core Concepts](../01_fundamentals/02_core_concepts.md) — the vocabulary used throughout
- Working knowledge of HTTP request/response and status codes
