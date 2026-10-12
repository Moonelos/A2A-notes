# A2A glossary

Use these definitions for lookup after reading the linked lesson.

| Term | One-line definition and teaching note |
|---|---|
| A2A client | The caller that discovers and sends work to an [A2A server](01_fundamentals/02_core_concepts.md). |
| A2A server | The agent endpoint that advertises a card and owns the response or [Task](01_fundamentals/02_core_concepts.md). |
| Agent Card | The server's discovery document describing interfaces, skills, capabilities, and security requirements; see [Agent Card](02_protocol/01_agent_card.md). |
| AgentSkill | One advertised capability inside an [Agent Card](02_protocol/01_agent_card.md). |
| Artifact | Server-produced Task output made of Parts; see [Core Concepts](01_fundamentals/02_core_concepts.md). |
| Binding | A mapping of A2A operations to JSON-RPC, HTTP+JSON, gRPC, or a custom transport; see [Transport & RPC](02_protocol/02_transport_and_rpc.md). |
| Context ID | An identifier grouping related Tasks and Messages, distinct from a single Task ID; see [Core Concepts](01_fundamentals/02_core_concepts.md). |
| Extension | Optional or required extra protocol behavior activated through a negotiated URI; see [Extensions](02_protocol/05_extensions_and_custom_bindings.md). |
| Message | One conversational turn sent by client or server, containing Parts; see [Core Concepts](01_fundamentals/02_core_concepts.md). |
| Part | One unit of text, file, or structured content inside a Message or Artifact; see [Core Concepts](01_fundamentals/02_core_concepts.md). |
| Push notification | A server-initiated webhook update to a registered client callback; see [Streaming & Push](02_protocol/04_streaming_and_push.md). |
| SSE | Server-Sent Events, the server-to-client HTTP event stream for updates; see [Streaming & Push](02_protocol/04_streaming_and_push.md). |
| Task | A server-owned, stateful unit of work with a stable ID, status, and possible Artifacts; see [Task Lifecycle](02_protocol/03_task_lifecycle.md). |
| Task store | Persistence for Task identity and status; see [Scaling & Deployment](05_production/03_scaling_deployment.md). |
| TCK | Technology Compatibility Kit used to check advertised A2A behavior; see [Conformance](05_production/05_conformance_and_interoperability.md). |
| Tenant scope | Verified tenant and owner predicates applied to Task, stream, and push resources; see [Multi-Tenant Scoping](05_production/04_multi_tenant_scoping.md). |
