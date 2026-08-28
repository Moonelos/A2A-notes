# 01_fundamentals/01_what_is_a2a.md (203 lines)
ORDERING: role foundation/tutorial; payoff line 11/203 (0.05, PASS); opening payoff PASS; length budget PASS.
EXPLANATION: register 10:17 (PASS; 10 markers/17 explanatory paragraphs); restatement PASS; unglossed first uses 4; unexplained rules/defenses 0; concrete-carrier gaps 0; intuition-building explanation yes.
Summary: 0 critical, 3 high, 2 med, 1 low

FIX-HIGH: Line 26 asks a first-time reader to understand the interoperability analogy through unexplained `ODBC` and `AMQP` — expand both at first use and state that the analogy stops at standardizing connectivity, because A2A also defines agent-specific task and message semantics.
FIX-HIGH: Lines 50–60 use `RPC` before explaining what kind of interaction it is, and line 143 uses `MCP` ten lines before its expansion — add an inline “remote procedure call” gloss at the transport table and expand Model Context Protocol at its first appearance.
FIX-HIGH: Lines 124–129 claim that opaque execution itself provides security and prevents a caller from reaching another agent's tools or data — separate interface opacity from access control, explain that A2A does not enforce the remote implementation boundary, and name authentication, authorization, least privilege, and server-side isolation as the controls that prevent access.
FIX-MED: Lines 50–60 present HTTP + JSON-RPC as the protocol's sole plumbing, but A2A v1.0 has three standard bindings: JSON-RPC, gRPC, and HTTP+JSON; revise the table and the “just HTTP and JSON” conclusion so the baseline can still default to JSON-RPC without erasing the other standard bindings. Source: https://github.com/a2aproject/A2A/blob/main/docs/topics/custom-protocol-bindings.md (checked 2026-08-28).
FIX-MED: Lines 168–180 say there are five official SDKs and omit Rust; update the count and table to six languages and add the official Rust SDK without implying that all six have identical maturity. Source: https://github.com/a2aproject/A2A/blob/main/docs/roadmap.md (checked 2026-08-28).
FIX-LOW: The file contains six separate `> **Key insight**:` blocks even though the house contract requires one transferable insight per note — retain the strongest protocol-vs-framework insight and demote the other takeaways to ordinary prose or claim-style headers.

# 01_fundamentals/02_core_concepts.md (324 lines)
ORDERING: role foundation/glossary; payoff line 5/324 (0.02, PASS); opening payoff PASS; length budget PASS.
EXPLANATION: register 1:20 (PASS; 1 marker/20 explanatory paragraphs); restatement PASS; unglossed first uses 1; unexplained rules/defenses 0; concrete-carrier gaps 0; intuition-building explanation yes.
Summary: 0 critical, 1 high, 2 med, 2 low

FIX-HIGH: Line 143 introduces `ProtoJSON` as the governing enum representation without saying what it is or why it changes the wire values — gloss it as Protocol Buffers' canonical JSON mapping and connect that mapping to the `TASK_STATE_*` strings the reader must send or inspect.
FIX-MED: The `json` fences at lines 50–74, 129–140, and 189–215 contain comments, placeholder array entries, or several top-level documents and therefore are not valid JSON — move annotations outside the fences and present each carrier as either one parseable minimal object or a clearly labelled non-JSON explanatory excerpt.
FIX-MED: Line 77 equates an Agent Card with an OpenAPI specification without marking the analogy's boundary — state that a card advertises coarse skills, interfaces, and security requirements but does not define each operation's request/response schema like OpenAPI.
FIX-LOW: Line 7 calls specification release 1.0.0 the current vocabulary target although 1.0.1 is the latest patch — retain protocol compatibility as `1.0` and record 1.0.1 as the checked specification release. Source: https://github.com/a2aproject/A2A/releases/tag/v1.0.1 (checked 2026-08-28).
FIX-LOW: The file contains ten `> **Key insight**:` blocks — choose one transferable relationship among Message, Artifact, Part, Task, and context, then turn the remaining summaries into normal prose so the marker remains a useful retrieval signal.

# 01_fundamentals/03_a2a_vs_mcp.md (147 lines)
ORDERING: role decision guide; payoff line 11/147 (0.07, PASS); opening payoff PASS; length budget PASS.
EXPLANATION: register 20:13 (PASS; 20 markers/13 explanatory paragraphs); restatement FAIL; unglossed first uses 0; unexplained rules/defenses 0; concrete-carrier gaps 0; intuition-building explanation yes.
Summary: 0 critical, 1 high, 0 med, 1 low

FIX-HIGH: Sections 3 and 5 say MCP tool calls have no task lifecycle, progress, or input-required pause and necessarily flatten those semantics; replace that obsolete discriminator with the current boundary: MCP's official Tasks extension can now provide durable long-running operations, polling, progress metadata, and `input_required`, while A2A still supplies peer-agent discovery, messages/artifacts, and cross-agent collaboration semantics. Include a changed decision row showing when MCP Tasks is sufficient and when an autonomous peer still warrants A2A. Sources: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx and https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/extensions/tasks/overview.mdx (checked 2026-08-28).
FIX-LOW: The file uses four `> **Key insight**:` blocks — keep one bounded, current decision insight and convert the remaining conclusions into prose or claim-style headers.

# 01_fundamentals/README.md (30 lines)
ORDERING: role subfolder index/link map; payoff line n/a (n/a, n/a); opening payoff n/a; length budget n/a (pure index).
EXPLANATION: register n/a (n/a; 0 markers/0 explanatory paragraphs); restatement n/a; unglossed first uses n/a; unexplained rules/defenses n/a; concrete-carrier gaps n/a; intuition-building explanation n/a.
Summary: 0 critical, 0 high, 0 med, 1 low

FIX-LOW: Line 5 badges specification release 1.0.0 as current although 1.0.1 is the latest patch — badge the negotiated protocol line as `1.0` or explicitly show checked release 1.0.1. Source: https://github.com/a2aproject/A2A/releases/tag/v1.0.1 (checked 2026-08-28).
