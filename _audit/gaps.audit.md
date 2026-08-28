# 02_protocol/
Suggested new notes: 3

GAP: Extension negotiation and custom protocol bindings — readers see extension URIs in Agent Cards, Messages, and Artifacts but never learn declaration, required-vs-optional behavior, per-request activation, dependency handling, or the boundary between an extension and a new binding.
  SIGNAL: leaned-on
  EVIDENCE: `01_fundamentals/02_core_concepts.md:Message` and `:Artifact` list `extensions` as protocol URIs, while `02_protocol/01_agent_card.md:AgentCapabilities` only says they are declared capabilities; the current official mechanism uses `AgentExtension` plus the `A2A-Extensions` service parameter and now has formal extension/binding governance (https://a2a-protocol.org/latest/topics/extensions/ and https://a2a-protocol.org/latest/topics/extension-and-binding-governance/, checked 2026-08-28).

GAP: Protocol-version negotiation and staged v0.3-to-v1.0 migration — the collection depends on automatic compatibility behavior without teaching how a client selects an advertised version, sends it on every request, handles rejection, or safely runs a mixed-version rollout.
  SIGNAL: leaned-on
  EVIDENCE: `03_python/01_sdk_setup.md:Version Compatibility` says the SDK can “negotiate down,” `03_python/03_building_a_client.md:Resolving an Agent Card` warns that some methods then disappear, and `02_protocol/02_transport_and_rpc.md:The three first-class transport bindings` repeatedly advertises `protocolVersion` but never explains the required `A2A-Version` service parameter or `VersionNotSupportedError`; the released v1.0 specification defines those responsibilities (https://a2a-protocol.org/v1.0.0/specification/, checked 2026-08-28).

GAP: Agent payments over A2A with AP2 — add a bounded guide showing where payment mandates and authorization evidence extend an ordinary A2A task, because AP2 v0.2 is now an adjacent protocol explicitly available as an A2A extension (https://github.com/google-agentic-commerce/AP2/blob/main/docs/index.md, checked 2026-08-28).
  SIGNAL: domain-expectation
  EVIDENCE: none — domain expectation

# 05_production/
Suggested new notes: 2

GAP: Multi-tenant routing and resource authorization scoping — readers are shown tenant-bearing interfaces and contexts but never get the end-to-end isolation model that prevents cross-tenant task, subscription, and push-configuration disclosure.
  SIGNAL: leaned-on
  EVIDENCE: `02_protocol/01_agent_card.md:AgentInterface` names an optional `tenant`, `03_python/03_building_a_client.md:Resolving an Agent Card` sends an unexplained `X-Tenant`, and `03_python/02_building_a_server.md:What RequestContext exposes` exposes tenant context; A2A v1.0 requires request-level tenant propagation and authorization scoping for every resource operation (https://a2a-protocol.org/v1.0.0/specification/, checked 2026-08-28).

GAP: Conformance and interoperability validation with Inspector, TCK, and cross-binding tests — a production path needs a repeatable pre-release proof that the Agent Card, declared capabilities, and all advertised transports behave consistently.
  SIGNAL: domain-expectation
  EVIDENCE: none — domain expectation; the official project now ships the A2A Inspector and a three-transport Technology Compatibility Kit (https://github.com/a2aproject/a2a-inspector and https://github.com/a2aproject/a2a-tck, checked 2026-08-28).

# 01_fundamentals/
NO-GAPS: The folder establishes A2A's problem, vocabulary, and MCP boundary without leaning on another unexplained foundational concept; AP2 belongs with the protocol extension mechanism rather than here.

# 03_python/
NO-GAPS: The SDK setup, server, and client sequence covers the folder's declared baseline; extension activation and tenant isolation first need canonical protocol and production owners rather than duplicate Python-only notes.

# 04_frameworks/
NO-GAPS: The adapter pattern plus native and hand-written examples cover the declared framework-integration scope, and no missing framework is promised or repeatedly assumed by the collection.
