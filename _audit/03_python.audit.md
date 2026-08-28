# 03_python/README.md (33 lines)
ORDERING: role pure index/link list; payoff line n/a/33 (n/a, n/a); opening payoff n/a; length budget n/a.
EXPLANATION: register n/a (n/a; pure index/link-list role); restatement n/a; unglossed first uses 0; unexplained rules/defenses 0; concrete-carrier gaps 0; intuition-building explanation n/a.
Summary: 0 critical, 0 high, 0 med, 1 low

FIX-LOW: The `a2a-sdk` badge on line 5 still advertises `1.0.3` although the latest published PyPI release is `1.1.2` — update the badge to `1.1.2`; source: https://pypi.org/project/a2a-sdk/ (checked 2026-08-28).

# 03_python/01_sdk_setup.md (274 lines)
ORDERING: role implementation/setup; payoff line 213/274 (0.777, FAIL); opening payoff FAIL; length budget PASS.
EXPLANATION: register 4:18 (PASS; 4 markers/18 explanatory paragraphs); restatement PASS; unglossed first uses 2; unexplained rules/defenses 0; concrete-carrier gaps 0; intuition-building explanation yes.
Summary: 0 critical, 3 high, 1 med, 0 low

FIX-HIGH: The verified-install payoff does not begin until line 213, after installation options, project layout, package reference, and compatibility detail — move a minimal pinned install plus the smoke test and its observable `install OK` output immediately after the opening, then continue with extras, layout, and reference material.
FIX-HIGH: `protobuf` first appears on line 11 without a plain-language cue — expand it as Protocol Buffers and state that these generated classes enforce the wire schema rather than behaving like ordinary Python data classes.
FIX-HIGH: `ASGI` first appears on line 106 without a gloss — expand it as Asynchronous Server Gateway Interface and connect it to why Starlette/FastAPI can host the SDK's generated routes.
FIX-MED: Lines 13, 114, 198, 207, and 263 call `1.0.3` current or pin/output that version, but the latest published package is `1.1.2`; retarget the supported baseline, compatibility table, project dependency, pinning example, and smoke output to `1.1.2`, while preserving the deliberate-upgrade rule; sources: https://pypi.org/project/a2a-sdk/ and https://github.com/a2aproject/a2a-python/blob/main/CHANGELOG.md (checked 2026-08-28).

# 03_python/02_building_a_server.md (597 lines)
ORDERING: role implementation; payoff line 315/597 (0.528, FAIL); opening payoff FAIL; length budget FAIL.
EXPLANATION: register 18:20 (PASS; 18 markers/20 explanatory paragraphs); restatement PASS; unglossed first uses 1; unexplained rules/defenses 0; concrete-carrier gaps 0; intuition-building explanation yes.
Summary: 1 critical, 3 high, 2 med, 0 low

FIX-CRITICAL: The `TaskUpdater` example calls `new_text_part` on line 240 without importing or defining it, so the advertised ergonomic alternative raises `NameError` when copied — import `new_text_part` from `a2a.helpers` in that self-contained block and show the expected terminal task result.
FIX-HIGH: The first assembled runnable server is deferred to line 315 after five component/reference sections — put a minimal card → executor → handler → routes server with its live-check directly after the four-piece mental model, then unpack each component and hardening concern below it.
FIX-HIGH: The complete example constructs `FxClient` and `DefaultRequestHandler` inline on lines 450–454 and never closes either; under the current `1.1.2` lifecycle this omits `DefaultRequestHandler.aclose()` draining of background tasks and also leaks the owned `httpx.AsyncClient` — retain both objects and add a Starlette lifespan shutdown that awaits `handler.aclose()` and `fx_client.aclose()`; source: https://github.com/a2aproject/a2a-python/blob/main/CHANGELOG.md (checked 2026-08-28).
FIX-HIGH: `SSE` first appears in prose on line 126 without expansion — introduce it as Server-Sent Events and explain that the transport serializes each queued event into one streamed HTTP frame.
FIX-MED: Lines 3 and 320 label `1.0.3` as the target although the latest published package is `1.1.2`; update the declared baseline and runnable-example label, and note the `1.1.2` shutdown/failure-persistence changes that affect this server example; sources: https://pypi.org/project/a2a-sdk/ and https://github.com/a2aproject/a2a-python/blob/main/CHANGELOG.md (checked 2026-08-28).
FIX-MED: The note is 597 lines with no `<!-- length-justification: ... -->` — split the minimal card/executor/handler/routes build from the streaming, lifecycle, and failure-mode hardening, or add a concrete justification for keeping those layers together.

# 03_python/03_building_a_client.md (562 lines)
ORDERING: role implementation; payoff line 389/562 (0.692, FAIL); opening payoff FAIL; length budget FAIL.
EXPLANATION: register 11:17 (PASS; 11 markers/17 explanatory paragraphs); restatement PASS; unglossed first uses 3; unexplained rules/defenses 0; concrete-carrier gaps 2; intuition-building explanation yes.
Summary: 3 critical, 4 high, 2 med, 0 low

FIX-CRITICAL: Line 146 recommends `grpc.aio.insecure_channel` without limiting it to an isolated localhost test, giving readers a plaintext gRPC transport for real agents — use `grpc.aio.secure_channel` with explicitly constructed trusted channel credentials in the default example and keep any insecure variant out of the production path.
FIX-CRITICAL: Lines 356 and 411 use the real-looking JWT prefix `eyJhbGciOi...` as a credential — load the token from an environment/secret-store variable in executable examples and use only an unmistakable non-credential placeholder in non-executable prose.
FIX-CRITICAL: The mid-stream recovery snippets on lines 268–275 and 506–517 assign `task_id` only from the awaited drain result, so an exception before the return leaves `task_id` unbound and the promised resume path itself raises `UnboundLocalError` — expose captured identity incrementally through caller-owned progress state or a typed interruption carrying `task_id`, and call `subscribe()` only after that state is populated.
FIX-HIGH: The first composed discover → create → send → interpret client is deferred to line 389 after transport selection, streaming, polling, and auth detail — open with a minimal runnable client and observable reply/task branch, then unpack streaming recovery, polling, auth, and production hardening.
FIX-HIGH: `oneof`, `gRPC`, and `SSE` first appear without local glosses on lines 7, 94, and 262 — add an opening wire-terms sentence defining a protobuf `oneof` as exactly one active field, gRPC as the HTTP/2 RPC binding, and SSE as Server-Sent Events.
FIX-HIGH: `StaticTokenService.get_credentials()` on lines 373–380 returns one secret for every `security_scheme_name`, so a card with a different or additional scheme can receive the wrong credential — use a scheme-keyed credential map backed by environment/secret-store values and fail closed when the requested scheme has no configured credential.
FIX-HIGH: Line 342 claims `AuthInterceptor` attaches the right header per scheme without stating that the current implementation stops after the first scheme in a multi-scheme AND `SecurityRequirement`, which leaves valid compound-auth cards returning `401`/`403` — document the boundary, preflight-reject unsupported compound requirements or supply a custom interceptor that attaches every required credential, and add a two-scheme request/header trace; source: https://github.com/a2aproject/a2a-python/issues/1138 (closed as not planned; checked 2026-08-28).
FIX-MED: Lines 3 and 7 target `1.0.3`/`1.0.x` although the latest published package is `1.1.2`; update the pinned baseline and verify each public import and client call against `1.1.2`; sources: https://pypi.org/project/a2a-sdk/ and https://github.com/a2aproject/a2a-python/blob/main/CHANGELOG.md (checked 2026-08-28).
FIX-MED: The note is 562 lines with no `<!-- length-justification: ... -->` — split the minimal discovery/factory/send path from streaming recovery, polling, authentication, and failure hardening, or add a concrete justification for keeping the complete client lifecycle together.
