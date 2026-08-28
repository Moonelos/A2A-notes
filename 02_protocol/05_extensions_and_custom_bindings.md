# Extensions & Custom Protocol Bindings

> **Who this is for**: Implementers who need domain-specific metadata, behavior, or transport while preserving the A2A 1.0 core contract.

An **extension** changes semantics above an existing binding. A **custom protocol binding** maps A2A operations onto a different transport. If HTTP+JSON still carries your message but a `DataPart` gains a purchase mandate, that is an extension; if A2A operations are mapped onto a new message bus, that is a binding.

## Declare support in the Agent Card

Extensions are URI-identified `AgentExtension` entries under `capabilities.extensions`:

```json
{
  "capabilities": {
    "extensions": [{
      "uri": "https://example.com/a2a/extensions/routing/v1",
      "description": "Selects a validated application route",
      "required": false,
      "params": {"carrier": "Message.metadata"}
    }]
  }
}
```

`required: true` means a client must understand and activate the extension to interact correctly. Use it only when the baseline interaction cannot work without the extension. A data-only annotation normally remains optional.

## Activate per request

Declarations describe capability; they do not activate behavior. For HTTP transports, the client sends a comma-separated `A2A-Extensions` service parameter and the server echoes only the URIs it activated:

```http
POST /a2a HTTP/1.1
A2A-Version: 1.0
A2A-Extensions: https://example.com/a2a/extensions/routing/v1
Content-Type: application/json
```

The request may then carry extension data in the location its specification defines, commonly a core `metadata` map or a schema-defined `DataPart`. The server validates the carrier before use. Unsupported optional URIs may be ignored; a missing required activation must fail with a documented error. Never silently substitute another extension version.

## Dependencies and versioning

An extension specification must define its URI, carriers and schemas, flows/methods, errors, authorization, and required dependencies. The client activates the extension plus all required dependencies. Give a breaking revision a new URI such as `/v2`; the URI is the negotiated version.

Extensions cannot add fields directly to core protobuf messages or invent enum values. Put additional data in defined metadata/data carriers. New RPC methods, if any, must pass through the same authentication, authorization, rate limits, and tenant scoping as core methods.

## When a custom binding is justified

Create a custom binding only when the transport mapping itself is different. Give it a stable identifier, define every core operation and error mapping, version header/service parameter behavior, streaming/cancellation semantics, security, and interoperability tests. Clients skip an unsupported binding and select another advertised `supportedInterfaces` entry.

Official and experimental artifacts follow the A2A [extension and binding governance](https://a2a-protocol.org/latest/topics/extension-and-binding-governance/); private URIs remain valid but are your compatibility responsibility.

> **Key insight**: Discovery declares an extension, the request activates it, and a validated carrier conveys its data. Treat those as three separate gates; an extension URI appearing in payload metadata is not proof that it was negotiated.

---

**Next**: [Protocol-Version Migration](06_version_negotiation_and_migration.md)
