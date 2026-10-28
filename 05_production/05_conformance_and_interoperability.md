# Prove the deployed Agent Card before release

> **Role:** production release decision. **Reader:** you can start an A2A server and read its Agent Card. The command line below follows the official TCK `run_tck.py` checked on 2026-10-12; pin the TCK commit for repeatable CI. This repository contains notes, not a running System Under Test (SUT).

An Agent Card is a promise about the endpoint behind it. If the invoice agent says `capabilities.streaming: true`, a client may choose `SendStreamingMessage`. Passing ordinary `SendMessage` tests cannot establish that streaming works. The release proof has to pair each declared capability and binding with an observed request on the deployed artifact.

## Preflight the exact SUT

Start the assembled invoice agent on `127.0.0.1:9999` in a separate shell using its own application startup command, and keep it running during the test. `http://127.0.0.1:9999/.well-known/agent-card.json` must serve the same card as production, with reachable `supportedInterfaces` URLs. If the server requires auth, configure the TCK credentials for that deployment before running; an unauthenticated 401 is not a useful conformance verdict. No SUT startup command is supplied here because this collection does not contain the complete authenticated production application.

Fetch the card and record its body hash, image digest, wire protocol version, SDK version, deployment config, and timestamp. Check binding URLs, security requirements, input/output modes, and `streaming`/`pushNotifications` declarations. Remove a declaration only if clients can safely stop relying on it; otherwise implement and test it. A card that advertises a route unreachable by the test runner needs environment repair before interpreting failures.

## Run the official TCK against it

The [official runner](https://github.com/a2aproject/a2a-tck/blob/main/run_tck.py) accepts `--sut-host`, `--level must`, and `--transport` values such as `jsonrpc`, `grpc`, and `http_json`. From a pinned clone of that repository, with Python 3.11+ and `uv` available:

```bash
git clone https://github.com/a2aproject/a2a-tck.git
cd a2a-tck
uv venv
uv pip install -e .
./.venv/bin/python run_tck.py --sut-host http://127.0.0.1:9999 --level must
./.venv/bin/python run_tck.py --sut-host http://127.0.0.1:9999 --transport jsonrpc,grpc,http_json
```

Record `git rev-parse HEAD` in the test evidence. The runner writes `reports/compatibility.json`, `reports/tck_report.html`, and `reports/junitreport.xml` (plus compatibility HTML). Read the command exit status, JUnit failures, and the compatibility report. Archive them immediately; a later run can overwrite the same paths. A transport filter is a diagnostic subset, not permission to ignore another advertised binding. See the runner source for the exact current options and report names.

### Diagnose a real local echo run

The [Python echo server](../03_python/02_building_a_server.md) is a deliberately narrow SUT: it advertises one JSON-RPC interface and returns a completed text Task for every input. On 2026-10-12, we started that exact server on loopback port 9999 and ran `run_tck.py --sut-host http://127.0.0.1:9999 --level must --transport jsonrpc` from TCK commit `263b9cfaf16a554bdfb166a7ba5b67716e946349`. The runner exited **1**: pytest reported 59 passed, 5 failed, and 171 skipped. These are historical recorded results, not a run reproduced during this update. The raw local compatibility/JUnit reports are not distributed with the notes. Reproduce the command against the pinned TCK commit and archive your own `reports/compatibility.json` and `reports/junitreport.xml` before treating individual case outcomes as release evidence.

One failure, `DM-ART-001`, expected the scenario's file Artifact with `filename=output.txt` and `mediaType=text/plain`; EchoExecutor always emits `Part(text="echo: ...")`. Another, `DM-MSG-001`, expected a direct Message response; EchoExecutor always starts a Task. The observed card and JSON-RPC route worked, but this SUT does not implement the TCK's scenario-specific output behaviors. Fixing the TCK command cannot make a text-only echo agent satisfy those cases. A real release candidate must implement its claimed behaviors in the controlled SUT, rerun the failing cases, and archive a clean report for each advertised binding. This local failure is a diagnostic exercise, not a conformance verdict on the Python SDK or an assembled invoice deployment.

## Interpret one failure

This is an **illustrative pytest/JUnit-style excerpt**, not a report produced by this notes repository:

```text
Agent Card: capabilities.streaming = true
JSON-RPC SendMessage: PASSED
JSON-RPC SendStreamingMessage (MUST when advertised): FAILED
AssertionError: advertised streaming endpoint returned UnsupportedOperationError
TCK exit status: 1
```

The failed assertion follows directly from the card declaration. The server accepted ordinary requests but cannot deliver the promised streaming method. Diagnose the binding endpoint, SSE response, proxy buffering, and handler capability wiring. Either implement and retest the feature or correct the card and treat removal as a compatibility change. Do not call the run compliant because the non-streaming tests passed.

A TCK failure can also be a test-harness or environment defect. Reproduce the failing request directly, compare it with the versioned specification, and record the issue and evidence. A known test issue does not silently become a pass; the release record needs an explicit disposition and independent contract evidence.

## Compare every advertised binding

For each binding in `supportedInterfaces`, send equivalent semantic cases: direct Message, Task creation, Get/List/Cancel, history and artifacts, stream order and terminal event, push config and authenticated delivery, errors, auth, and tenant isolation. Normalize only the transport envelope. Task state, artifacts, authorization outcome, and terminal meaning should agree. For an inaccessible `task-7`, all bindings must return the appropriate task-not-found behavior and never leak a live event or push configuration. A binding-specific protocol mapping may change an HTTP status or gRPC code, but not the authorization decision.

Run these cases against the deployed image through the same gateway, not only a mocked handler. Record each advertised surface in a matrix with card field, test case, observed result, and report artifact. Repeat after a card, SDK, proxy, or schema change.

## Decide whether to release

Block release on an unexplained MUST failure, any advertised capability that cannot be exercised, semantic differences between advertised bindings, tenant/owner isolation failure, or a failed durable recovery drill. Investigate SHOULD failures and record a reasoned disposition. An optional MAY feature is relevant when the card actually advertises it.

**Decision exercise:** JSON-RPC passes; advertised HTTP+JSON has one unexplained MUST failure; the deployment works in a manual browser demo. Release?

<details><summary>Answer</summary>

No. HTTP+JSON is part of the card's external contract. The unexplained MUST failure blocks release until fixed or shown with evidence to be a test/environment defect and independently tested. The browser demo exercises another path.

</details>

---

**Next:** [Back to the repository overview](../README.md)
