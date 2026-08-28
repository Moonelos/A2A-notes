# README.md :: Path 1 — New to A2A
Outcome: Explain the interoperability problem, use the core A2A vocabulary, distinguish A2A from MCP, and inspect the first concrete protocol artifact.
Files: 01_fundamentals/01_what_is_a2a.md → 01_fundamentals/02_core_concepts.md → 01_fundamentals/03_a2a_vs_mcp.md → 02_protocol/01_agent_card.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 0 med, 1 low

FIX-LOW: README.md `Path 1 — New to A2A` has no milestone or stop-point label — mark entry 3 as the conceptual stop for readers who only need to choose A2A versus MCP, and entry 4 as the continuation for readers who will implement discovery.
NO-ACTION: The path opens with a concrete travel-agent interoperability failure, builds only the vocabulary needed for the next step, and uses linked excerpts rather than competing with the Agent Card note's canonical schema ownership; by entry 4 the reader can teach back the problem, default interaction, first contract failure, and reason to continue to transport.

# README.md :: Path 2 — Implementing in Python
Outcome: Install the Python SDK, expose a working A2A server, and call it from a client.
Files: 01_fundamentals/02_core_concepts.md → 02_protocol/02_transport_and_rpc.md → 03_python/01_sdk_setup.md → 03_python/02_building_a_server.md → 03_python/03_building_a_client.md
PAYOFF: entry 3 (FAIL; threshold 2)
Summary: 1 high, 1 med, 1 low

FIX-HIGH: README.md `Path 2 — Implementing in Python` delays the first runnable Python result until entry 3 and the first live agent until entry 4 — reorder as SDK Setup → a minimal server quickstart within the first two entries, then place Core Concepts, Transport & RPC, lifecycle explanation, and the hardened server/client material after that baseline so the path reads do → understand → harden.
FIX-MED: README.md `Path 2 — Implementing in Python` omits Task Lifecycle even though `03_python/02_building_a_server.md` declares it as required and expects the reader to drive terminal and interrupted states — add it immediately after the runnable baseline, before lifecycle hardening and client continuation behavior.
FIX-LOW: README.md `Path 2 — Implementing in Python` gives no confident stop point — label the completed-server milestone for server-only readers and make Building a Client the explicit continuation for callers and orchestrators.

# README.md :: Path 3 — Integrating an existing framework
Outcome: Expose an existing framework agent over A2A and, when needed, consume a remote A2A agent from that framework.
Files: 01_fundamentals/02_core_concepts.md → 02_protocol/01_agent_card.md → 04_frameworks/README.md → one selected 04_frameworks guide → 03_python/03_building_a_client.md
PAYOFF: entry 3 (FAIL; threshold 2)
Summary: 1 high, 2 med, 0 low

FIX-HIGH: README.md `Path 3 — Integrating an existing framework` spends its first two entries on vocabulary and schema and reaches the first framework-specific working outcome only at entry 3 — split it into direct framework branches whose first two entries are the selected guide's minimal exposure path and its required SDK baseline, with Core Concepts and Agent Card linked as understand-after-do material.
FIX-MED: README.md `Path 3 — Integrating an existing framework` sends the reader to `04_frameworks/README.md`, whose default sequence starts with LangGraph regardless of the framework the reader knows — link directly to LangGraph, ADK, CrewAI, Semantic Kernel, LlamaIndex, or AG2 branch targets and state each branch's prerequisites.
FIX-MED: README.md `Path 3 — Integrating an existing framework` forces Building a Client after framework guides that already teach both exposure and consumption — add a stop point after successful exposure and make the client note a conditional continuation only when the reader needs lower-level consumption or custom client behavior.

# README.md :: Path 4 — Shipping to production
Outcome: Model long-running work, secure agent calls, harden trust boundaries, and scale a working A2A deployment.
Files: 02_protocol/03_task_lifecycle.md → 02_protocol/04_streaming_and_push.md → 05_production/01_authentication.md → 05_production/02_security_hardening.md → 05_production/03_scaling_deployment.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 1 med, 1 low

FIX-MED: README.md `Path 4 — Shipping to production` begins with hardening mechanisms but never states the baseline it assumes, while its notes require Agent Card and Building a Server knowledge — add an entry contract that requires a working server/client and links those prerequisites as a short preflight, so a prototype-owning reader can teach back why each production layer is next without treating production complexity as the entry price.
FIX-LOW: README.md `Path 4 — Shipping to production` has no milestone stops — label Authentication + Security Hardening as the single-replica secure-deployment stop and Scaling & Deployment as the continuation triggered by replicas, durable long tasks, or operational SLOs.
NO-ACTION: Given the missing prerequisite label is repaired, the sequence moves coherently from task-state correctness through disconnected delivery, identity, hostile-peer defenses, and externalized state, with operational symptoms and recovery owned by the later notes rather than duplicated into the foundation.

# 01_fundamentals/README.md :: Reading Order
Outcome: Build the conceptual model and vocabulary needed to decide whether A2A belongs in a system.
Files: 01_fundamentals/01_what_is_a2a.md → 01_fundamentals/02_core_concepts.md → 01_fundamentals/03_a2a_vs_mcp.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 0 med, 0 low

NO-ACTION: The stated HTTP/JSON/agent prerequisites are sufficient, entry 1 provides a concrete interoperability outcome, entry 2 adds one vocabulary layer, and entry 3 turns it into a decision; the reader can stop knowing when not to use A2A or follow the final link to the Agent Card when implementation begins.

# 02_protocol/README.md :: Reading Order
Outcome: Inspect discovery and a complete wire exchange, then reason about task states and asynchronous delivery.
Files: 02_protocol/01_agent_card.md → 02_protocol/02_transport_and_rpc.md → 02_protocol/03_task_lifecycle.md → 02_protocol/04_streaming_and_push.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 0 med, 1 low

FIX-LOW: 02_protocol/README.md `Reading Order` does not label its natural stop points — mark entry 2 as sufficient for synchronous message exchange, entry 3 as the continuation for durable or multi-turn tasks, and entry 4 as the continuation for disconnected or incremental delivery.
NO-ACTION: The Core Concepts prerequisite supplies the entry vocabulary; the path then progresses from a concrete card and request/response to state and delivery hardening, preserves canonical schema ownership, and lets the reader teach back the success signal, the first stale-card/task-state failures, and why each later mechanism exists.

# 03_python/README.md :: Reading Order
Outcome: Verify the SDK, run an A2A server, and call it with the official Python client.
Files: 03_python/01_sdk_setup.md → 03_python/02_building_a_server.md → 03_python/03_building_a_client.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 0 med, 0 low

NO-ACTION: The path's declared protocol and Python prerequisites are sufficient, the first entry produces an observable install result, the second produces a discoverable live server, and the third closes the round trip; its progression gives the reader a usable stop after either the server or the full client/server pair and a clear production continuation through linked hardening notes.

# 04_frameworks/README.md :: Reading Order
Outcome: Expose an agent from the reader's chosen framework over A2A and consume remote A2A peers where that framework supports it.
Files: 04_frameworks/01_langchain_langgraph.md → 04_frameworks/02_google_adk.md → 04_frameworks/03_crewai_and_others.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 1 med, 0 low

FIX-MED: 04_frameworks/README.md `Reading Order` forces a reader who knows only ADK, CrewAI, Semantic Kernel, LlamaIndex, or AG2 through LangGraph-specific types before reaching their own framework, despite requiring familiarity with only one framework — replace the linear order with a choose-your-framework branch map, make each selected guide its own entry and stop point, and route advanced custom adapters back to the canonical Python server/client owners.

# 05_production/README.md :: Reading Order
Outcome: Turn a working single-process A2A prototype into a secure and horizontally scalable deployment.
Files: 05_production/01_authentication.md → 05_production/02_security_hardening.md → 05_production/03_scaling_deployment.md
PAYOFF: entry 1 (PASS; threshold 2)
Summary: 0 high, 0 med, 1 low

FIX-LOW: 05_production/README.md `Reading Order` does not expose a safe stop point — label completion of Authentication + Security Hardening as the secure single-replica milestone, and make Scaling & Deployment conditional on multiple replicas, durable execution, or operational reliability requirements.
NO-ACTION: The prerequisites establish the working baseline before production complexity, and the path then moves from caller identity to hostile-peer defenses to externalized state and operations; by each milestone the reader can state the control, visible success, first failure symptom, and reason for the next layer.
