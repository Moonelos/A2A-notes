# Conformance & Interoperability Validation

> **Who this is for**: Release engineers who need evidence that an Agent Card and every advertised binding behave consistently before deployment.

Unit tests prove your implementation logic; conformance tests prove the external contract. Use the official Inspector for interactive diagnosis and the Technology Compatibility Kit (TCK) as a repeatable CI gate.

## Preflight the advertised surface

Fetch `/.well-known/agent-card.json` and verify its schema, cache headers, signatures under your local policy, `protocolVersion`, bindings/URLs, modes, skills, security requirements, and capabilities. A declaration is a promise: do not advertise streaming, push, extended cards, an extension, or a binding that the deployed endpoint cannot exercise.

## Run the TCK

The current TCK requires Python 3.11+ and `uv`:

```bash
git clone https://github.com/a2aproject/a2a-tck.git
cd a2a-tck
uv venv
source .venv/bin/activate
uv pip install -e .
./run_tck.py --sut-host http://localhost:9999 --level must
./run_tck.py --sut-host http://localhost:9999 --transport grpc,jsonrpc,http_json
```

The kit discovers transports from `supportedInterfaces` and writes machine-readable JSON, HTML, pytest HTML, and JUnit reports under `reports/`. Archive the report with the server image digest, Agent Card hash, spec/SDK versions, and test timestamp.

## Add cross-binding contract tests

For each advertised binding, send the same semantic cases and compare normalized results:

- direct `Message` and task-returning `SendMessage`;
- lifecycle transitions, history length, artifacts, cancellation, and not-found behavior;
- streaming order/terminal event and reconnect behavior;
- push configuration and authenticated `StreamResponse` delivery;
- version/extension negotiation and binding-native error mappings;
- authentication plus tenant/owner isolation.

Normalize only transport envelopes. Task IDs, context IDs, states, artifacts, authorization decisions, and terminal semantics should agree. Include negative cases and malformed input; happy-path parity is not conformance.

## Release gate

Block release on MUST failures, unexplained regressions, card-to-runtime mismatch, cross-binding semantic differences, or isolation failures. Review SHOULD failures explicitly and record the reason; optional MAY tests apply only to capabilities you declare.

> **Key insight**: The Agent Card is an executable compatibility claim. Test every declared version, binding, capability, extension, and security boundary against the deployed artifact—not merely against mocks or one preferred transport.

---

**Next**: [Back to the repository overview](../README.md)
