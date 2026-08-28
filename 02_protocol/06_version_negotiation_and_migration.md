# Protocol-Version Negotiation & Migration

> **Who this is for**: Teams rolling A2A 1.0 into a fleet that still contains v0.3 clients or servers.

Wire compatibility is declared as Major.Minor (`1.0`), while this repository is checked against specification patch release 1.0.1. The client selects an advertised interface/version and sends `A2A-Version: 1.0` on every HTTP request. An empty header is interpreted as legacy `0.3`; it is not a safe way to request “latest.”

## The request contract

```http
POST /message:send HTTP/1.1
Host: agent.example
A2A-Version: 1.0
Content-Type: application/json
```

The server either processes that version or returns the binding-specific `VersionNotSupportedError`. Clients must not retry the same interface without a version or reinterpret a 1.0 response as 0.3.

## A staged v0.3 → v1.0 rollout

1. Inventory clients, servers, cards, bindings, and SDK pins. Record which 0.3-only operations or field shapes are still used.
2. Add contract tests for both versions before changing routing. Keep separate serializers/models at the boundary; do not mix 0.3 and 1.0 objects inside business logic.
3. Publish explicit `supportedInterfaces` entries for the versions you truly serve. Prefer separate URLs when that makes routing and retirement observable.
4. Upgrade servers first while retaining a measured compatibility path. Require clients to send the version explicitly and emit metrics by version/interface/error.
5. Upgrade clients to select a compatible card interface and send the service parameter on every request.
6. Drain 0.3 traffic, announce a deadline, then remove the old interface and compatibility code. A stale card should fail clearly, not fall through to another schema.

## Mixed-fleet test matrix

| Client | Server | Expected result |
|---|---|---|
| 1.0 | advertises/accepts 1.0 | Success; response uses 1.0 shapes |
| 1.0 | 0.3 only | Client selects an explicitly supported 0.3 compatibility path or stops |
| 0.3 | dual-stack | Legacy path works and is counted |
| any | unsupported version header | Binding-native version-not-supported failure |
| any | stale interface URL/version | Clear failure; refetch card, then reselect |

Run lifecycle, streaming, push, auth, and error tests for each advertised version. A successful `SendMessage` alone does not prove that continuation or task resource operations are compatible.

> **Key insight**: Version negotiation is explicit selection, not hopeful fallback. Advertise only what the endpoint implements, send the chosen version on every call, and make legacy traffic measurable before removing it.

---

**Next**: [Agent Payments with AP2](07_agent_payments_ap2.md)
