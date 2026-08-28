# Multi-Tenant Routing & Resource Scoping

> **Who this is for**: Operators serving multiple organizations, users, or workloads from one A2A endpoint.

Multi-tenancy has two independent steps: route the request to a tenant and authorize every resource access within that tenant. A header or Agent Card interface may help route, but only a verified identity-to-tenant mapping establishes the security boundary.

## Establish the tenant once

```text
TLS/gateway authentication
  → verified principal (issuer, subject, scopes)
  → server-side membership lookup
  → tenant_id + owner_id in ServerCallContext
  → owner-scoped stores and executor policy
```

Treat `X-Tenant`, hostnames, path segments, and an interface's optional `tenant` value as routing hints. Validate the requested tenant against the authenticated principal's memberships. Never accept tenant/owner from a `Message`, task metadata, or unverified header and pass it directly to storage.

## Scope every operation

Use composite identity in keys and predicates:

```sql
SELECT task_json FROM tasks
WHERE tenant_id = :verified_tenant
  AND owner_id = :verified_owner
  AND task_id = :task_id;
```

Apply the same predicate to `GetTask`, `ListTasks`, `CancelTask`, `SubscribeToTask`, continuation messages, updates/deletes, and create/get/list/delete push-configuration operations. Page tokens must be opaque, integrity-protected, and bound to tenant, owner, query filters, and expiry.

Return the same task-not-found response for absent and inaccessible resources. Otherwise a caller can enumerate IDs through error differences, timing, stream behavior, or push-config existence.

## Execution and events

Persist tenant and owner on the task, durable job, checkpoints, event log, deduplication record, and push outbox. Workers derive scope from the claimed job record rather than caller-supplied payload. Broker topics can be shared only when consumers re-check the stored scope before publication/subscription.

## Isolation tests

For tenants A and B, use known IDs to assert that A cannot get, list, continue, cancel, subscribe to, overwrite, delete, or configure push for B's tasks. Repeat with valid broad scopes, guessed page tokens, stale subscriptions, duplicate `messageId` values, and every advertised binding. Verify logs contain tenant/owner identifiers but no credentials or artifact bodies.

> **Key insight**: Tenant routing chooses a partition; resource authorization protects each row and stream. Carry one verified tenant/owner identity through every store, queue, event, and push operation, and never rebuild it from protocol payload data.

---

**Next**: [Conformance & Interoperability](05_conformance_and_interoperability.md)
