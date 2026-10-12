# Authentication & Authorization for A2A in Production

> **Who this is for**: Engineers hardening an A2A deployment who have already built a working server and client and now need to lock down who can call what. Targets wire protocol **1.0**, specification release **1.0.1**, and `a2a-sdk` **1.1.2**. Retest integrations before widening that SDK pin because request-handler lifecycle behavior is version-sensitive.

Before reading this, understand how agents advertise themselves: **[The Agent Card](../02_protocol/01_agent_card.md)**, and how a request gets handled server-side: **[Building a Server](../03_python/02_building_a_server.md)**.

---

## 1. The A2A Auth Model: Standard Web Auth, Nothing New

A2A is deliberately boring about security. It does **not** define its own token format, login dance, or credential exchange. It reuses what HTTP already has.

> **Rule**: Authentication in A2A happens at the **HTTP transport layer**, *outside* the JSON-RPC body. The protocol layer (the `Message`, `Task`, and JSON-RPC envelope) never carries credentials.

```
┌─────────────────────────────────────────────────────────┐
│  HTTP request                                            │
│  POST /a2a  HTTP/1.1                                      │
│  Authorization: Bearer <access-token>  ◄── auth lives HERE│
│  Content-Type: application/json                           │
│  ┌─────────────────────────────────────────────────────┐ │
│  │  JSON-RPC body  ◄── NO credentials here, ever        │ │
│  │  { "jsonrpc": "2.0", "method": "SendMessage", ... }  │ │
│  └─────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────┘
```

Three consequences follow, and they are non-negotiable:

- **Credentials are obtained out-of-band.** The Agent Card *declares which scheme* a caller must satisfy. It never *contains* a usable secret. The client goes to an OAuth token endpoint, a secret manager, or an mTLS keystore on its own.
- ❌ A `client_secret`, bearer token, or API key embedded anywhere in the Agent Card or in a `Message` part is a **credential leak**. The card is public (it lives at a well-known URL).
- ✅ The card carries only *metadata about how to authenticate* — endpoint URLs, scheme types, scope names.

Think of the Agent Card like an OpenAPI document: it tells a client *how* to authenticate; acquiring the credential is the client's problem, solved with standard tooling.

---

## 2. Declaring Auth in the Agent Card

The Agent Card has two top-level fields inspired by the OpenAPI `SecurityScheme` model but encoded as A2A protobuf/ProtoJSON objects:

- `securitySchemes` — an object mapping a **scheme name** (you choose it) to a `SecurityScheme` definition.
- `securityRequirements` — a list of **security requirement objects**. Entries in the list are alternatives (**OR**). Schemes inside one entry are cumulative (**AND**): all of them must be satisfied.

### Supported scheme types

| Oneof field | Key fields | Use case |
|---|---|---|
| `apiKeySecurityScheme` | `name`, `location` (`header` / `query` / `cookie`) | Simple internal services, low-trust |
| `httpAuthSecurityScheme` | `scheme` (`Bearer` / `Basic`), `bearerFormat` | Opaque or JWT bearer tokens, basic auth |
| `oauth2SecurityScheme` | `flows` (an `OAuthFlows` object) | Service-to-service & delegated user auth |
| `openIdConnectSecurityScheme` | `openIdConnectUrl` | OAuth2 + identity, with OpenID Connect (OIDC) discovery |
| `mtlsSecurityScheme` | optional `description` only | Mutual TLS (mTLS), where both peers present certificates |

> **Rule**: An `OAuthFlows` object is a Protocol Buffers `oneof`: setting a second member overwrites the first in many generated APIs, and conforming parsers reject ambiguous JSON. Choose exactly one current flow: `authorizationCode`, `clientCredentials`, or `deviceCode`. The still-decodable `implicit` and `password` members are deprecated and should not appear in new cards.

A requirement that demands both a client certificate and a scoped token uses one entry:

```json
{
  "schemes": {
    "mesh-mtls": { "list": [] },
    "acme-sso": { "list": ["tasks:write"] }
  }
}
```

### Example: declaring an OAuth2 client-credentials scheme

This card tells a calling agent: "get a token from this token endpoint using the client-credentials grant, with the `tasks:write` scope."

```json
{
  "name": "Invoice Processing Agent",
  "version": "2.4.0",
  "supportedInterfaces": [
    {
      "url": "https://agents.acme.internal/invoice/a2a",
      "protocolBinding": "JSONRPC",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": { "streaming": true },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["application/json"],
  "skills": [
    { "id": "submit-invoice", "name": "Submit Invoice",
      "description": "Validate and queue an invoice for payment",
      "tags": ["finance"] }
  ],

  "securitySchemes": {
    "acme-sso": {
      "oauth2SecurityScheme": {
        "description": "Acme corporate OAuth2 server (Keycloak)",
        "flows": {
          "clientCredentials": {
            "tokenUrl": "https://sso.acme.internal/realms/agents/protocol/openid-connect/token",
            "refreshUrl": "https://sso.acme.internal/realms/agents/protocol/openid-connect/token",
            "scopes": {
              "tasks:read":  "Read task status and artifacts",
              "tasks:write": "Submit and cancel tasks"
            }
          }
        }
      }
    }
  },

  "securityRequirements": [
    {
      "schemes": {
        "acme-sso": { "list": ["tasks:write"] }
      }
    }
  ]
}
```

The `securityRequirements` list above means: *every* request to this agent must present an `acme-sso` token carrying the `tasks:write` scope.

---

## 3. The Client Flow: Read Card → Get Credential → Attach It

The client's job is three steps, and `a2a-sdk` automates the third one.

```
1. Fetch & parse the Agent Card  →  read .securitySchemes / .securityRequirements
2. Obtain a credential for the required scheme   (OUT-OF-BAND)
        e.g. POST grant_type=client_credentials to the tokenUrl
3. Attach the credential to every outgoing request
        e.g. Authorization: Bearer <access_token>
```

### The SDK mechanism: `AuthInterceptor` + `CredentialService`

`a2a-sdk` 1.1.2 exposes a `ClientCallInterceptor` hook. Interceptors run a `before()` method on every outbound call. The shipped `AuthInterceptor` pairs with a `CredentialService`: it selects the first usable credential for Bearer, OAuth/OIDC, or a header API key. It skips query/cookie API keys and does not assemble compound AND requirements such as mTLS plus OAuth; configure those at the HTTP/gRPC client and application layer.

`CredentialService` is an abstract base class with one method you must satisfy:

```python
async def get_credentials(
    security_scheme_name: str,
    context: ClientCallContext | None,
) -> str | None:
    ...
```

The SDK provides `InMemoryContextCredentialStore`, a session-keyed implementation. You populate it; the `AuthInterceptor` reads from it and sets the right header based on the card's declared scheme.

```python
from a2a.client import (
    AuthInterceptor,
    ClientCallContext,
    ClientConfig,
    ClientFactory,
    InMemoryContextCredentialStore,
)
import httpx

# --- Step 2: obtain a credential OUT-OF-BAND (standard OAuth2 client-credentials) ---
async def fetch_service_token(token_url: str, scope: str) -> str:
    async with httpx.AsyncClient() as http:
        resp = await http.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": SETTINGS.client_id,
                "client_secret": SETTINGS.client_secret,  # from a secret manager, NOT the card
                "scope": scope,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

# --- Wire the credential into the SDK ---
credential_store = InMemoryContextCredentialStore()
session_id = "billing-run-2026-05-18"

token = await fetch_service_token(
    "https://sso.acme.internal/realms/agents/protocol/openid-connect/token",
    scope="tasks:write",
)
# The scheme name MUST match the key in the card's securitySchemes object.
await credential_store.set_credentials(session_id, "acme-sso", token)

# --- Step 3: the AuthInterceptor attaches it automatically on every call ---
factory = ClientFactory(ClientConfig(httpx_client=httpx.AsyncClient()))
client = factory.create(
    agent_card,                      # card fetched in Step 1
    interceptors=[AuthInterceptor(credential_store)],
)

# Pass the session so the interceptor can resolve the credential.
context = ClientCallContext(state={"sessionId": session_id})
async for event in client.send_message(request=request, context=context):
    handle(event)
```

`InMemoryContextCredentialStore` keys credentials by the `sessionId` it reads from `ClientCallContext.state`. Forget to pass the context and `get_credentials` returns `None`; fail closed before sending instead of relying on a later authentication error.

⚠️ For OAuth2, the token expires. Refresh it (or re-run the client-credentials grant) before expiry and call `set_credentials` again. The `InMemoryContextCredentialStore` does not refresh for you. For long-running clients, wrap a token cache around the fetch with a margin (e.g. refresh at 80% of `expires_in`).

---

## 4. The Server Flow: Validate Before You Process

The server MUST authenticate **every** incoming request before any business logic runs. The cleanest place is ASGI (Asynchronous Server Gateway Interface) middleware, so a rejected request never reaches the agent executor.

```
incoming request
      │
      ▼
┌──────────────────┐   no/invalid creds   ┌──────────────┐
│ Auth middleware  │ ───────────────────► │ 401 + WWW-   │
│  - parse header  │                      │ Authenticate │
│  - validate JWT  │   valid but wrong    ┌──────────────┐
│  - check scopes  │ ───── scope ───────► │     403      │
└────────┬─────────┘                      └──────────────┘
         │ authenticated identity attached to request.state
         ▼
   AgentExecutor.execute(...)
```

| Binding | Missing/invalid credential | Authenticated but forbidden |
|---|---|---|
| HTTP+JSON | HTTP `401` with `WWW-Authenticate` | HTTP `403` |
| gRPC | `UNAUTHENTICATED` | `PERMISSION_DENIED` |
| JSON-RPC over HTTP | The deployment may reject at HTTP with `401`/`403`, or return documented custom JSON-RPC errors after parsing | Same policy, consistently documented |

Authenticate before business logic regardless of binding. A gateway-level rejection is appropriate when the caller has not yet reached a valid protocol operation; binding-native errors are appropriate when authentication is integrated after transport parsing.

### The `auth-required` task state

Sometimes the *caller* is authenticated fine, but the agent needs **additional** credentials mid-task — e.g. it must call a downstream SaaS API on the user's behalf. That is not a 401 on the A2A request itself. Instead the agent moves the `Task` into the **`auth-required`** state (`TASK_STATE_AUTH_REQUIRED`), an interrupted state. The status message explains what authorization is needed, but credentials MUST arrive out of band unless both peers negotiated an in-band extension. Once the external credential store is updated, the agent may resume immediately; a follow-up A2A `Message` is not required.

```
auth-required  ≠  HTTP 401
─────────────────────────────────────────────
HTTP 401        : "I don't know who YOU are."          (transport layer)
auth-required   : "I know you; now I need a token to
                   reach a downstream system to finish
                   your task."                          (task lifecycle)
```

---

## 5. OAuth2 / OIDC in Depth

For service-to-service agent calls, the **client-credentials** grant is the right tool: no user is present, the calling agent *is* the principal. The flow has no redirect and no refresh-token dance — just `POST grant_type=client_credentials` to the `tokenUrl` and you get an access token.

When the issuer promises a JWT access-token profile, the server validates that JSON Web Token (JWT). Do not infer JWT from OIDC alone: an OAuth access token can be opaque. Use issuer-supported local JWT validation or RFC 7662 token introspection according to the authorization server's metadata and contract.

| Check       | What to verify                                              | If skipped                                  |
| ----------- | ----------------------------------------------------------- | -------------------------------------------- |
| `signature` | Verify against the issuer's JSON Web Key Set (JWKS)        | Anyone can forge a token                    |
| `iss`       | Matches your trusted issuer exactly                         | Tokens from any IdP are accepted            |
| `aud`       | Matches *this* agent's identifier                           | **Token confusion** — see §8                |
| `exp`       | Token is not expired (also `nbf` if present)                | Stolen tokens are valid forever             |

### Bearer-JWT validation at the FastAPI boundary

This dependency validates an inbound JWT and returns the authenticated identity plus scopes. It fetches signing keys via JWKS with caching, so it does not hit the IdP on every request.

```python
import logging
from dataclasses import dataclass

import jwt                                  # PyJWT
from jwt import PyJWKClient
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

ISSUER   = "https://sso.acme.internal/realms/agents"
AUDIENCE = "invoice-processing-agent"        # THIS agent's identifier
ALGS     = ["RS256"]
logger = logging.getLogger(__name__)

# PyJWKClient caches keys internally and refreshes on key rotation.
_jwks = PyJWKClient(f"{ISSUER}/protocol/openid-connect/certs", cache_keys=True)

bearer_scheme = HTTPBearer(auto_error=False)  # we craft our own 401


@dataclass(frozen=True)
class Principal:
    subject: str          # the calling agent's client_id / service account
    scopes: frozenset[str]


async def authenticated_principal(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        # 401 MUST advertise the scheme so the client knows how to retry.
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
            headers={"WWW-Authenticate": 'Bearer realm="a2a"'},
        )
    try:
        signing_key = _jwks.get_signing_key_from_jwt(creds.credentials)
        claims = jwt.decode(
            creds.credentials,
            signing_key.key,
            algorithms=ALGS,
            issuer=ISSUER,            # validates `iss`
            audience=AUDIENCE,        # validates `aud` — prevents token confusion
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        # Do not reflect parser/key details or any token material to the caller.
        logger.info("Bearer token rejected", extra={"reason_type": type(exc).__name__})
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
        ) from exc

    scopes = frozenset(claims.get("scope", "").split())
    subject = claims["sub"]
    if not isinstance(subject, str) or not subject.strip():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
    return Principal(subject=subject, scopes=scopes)


def require_scope(scope: str):
    """Authorization gate — 403 when authenticated but under-scoped."""
    def _gate(principal: Principal = Depends(authenticated_principal)) -> Principal:
        if scope not in principal.scopes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail=f"Token lacks required scope '{scope}'",
            )
        return principal
    return _gate
```

### Pass that principal through the SDK route

SDK **1.2.2** uses `create_jsonrpc_routes(..., context_builder=...)`. The builder's `build(request)` method is synchronous, so validate the bearer token and membership in asynchronous ingress middleware first. This assembly reuses `authenticated_principal` above and the `handler`/`card` pattern from [Building a Server](../03_python/02_building_a_server.md), rebuilt under SDK 1.2.2. Set that card's JSON-RPC interface URL to `https://your-host/invoice/a2a` to match the route below; the echo card's `/` URL cannot be reused. The membership map is a small teaching fixture; a deployed service reads memberships from trusted storage and tests revocation. Install `a2a-sdk[http-server]==1.2.2`, `fastapi`, and `PyJWT[crypto]` for these imports. [Route source](https://github.com/a2aproject/a2a-python/blob/v1.2.2/src/a2a/server/routes/jsonrpc_routes.py), [default builder](https://github.com/a2aproject/a2a-python/blob/v1.2.2/src/a2a/server/routes/common.py).

```python
from fastapi.security import HTTPAuthorizationCredentials
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from a2a.auth.user import User
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder

MEMBERSHIPS = {"agent-A": {"tenant-A"}, "agent-B": {"tenant-B"}}
METHOD_SCOPES = {
    "SendMessage": "tasks:write", "SendStreamingMessage": "tasks:write",
    "CancelTask": "tasks:write", "CreateTaskPushNotificationConfig": "tasks:write",
    "DeleteTaskPushNotificationConfig": "tasks:write",
    "GetTask": "tasks:read", "ListTasks": "tasks:read",
    "SubscribeToTask": "tasks:read",
    "GetTaskPushNotificationConfig": "tasks:read",
    "ListTaskPushNotificationConfigs": "tasks:read",
    "GetExtendedAgentCard": "tasks:read",
}

class ScopedUser(User):
    def __init__(self, key: str): self.key = key
    @property
    def is_authenticated(self) -> bool: return True
    @property
    def user_name(self) -> str: return self.key

class VerifiedIngress(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path != "/invoice/a2a":
            return await call_next(request)  # public Agent Card
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse({"error": "unauthorized"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        try:
            principal = await authenticated_principal(
                request, HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
            )
        except HTTPException as exc:
            return JSONResponse({"error": exc.detail}, status_code=exc.status_code,
                                headers=exc.headers)
        try:
            method = (await request.json())["method"]
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "invalid request"}, status_code=400)
        required = METHOD_SCOPES.get(method)
        if required is None:
            return JSONResponse({"error": "unsupported method"}, status_code=400)
        if required not in principal.scopes:
            return JSONResponse({"error": "insufficient scope"}, status_code=403)
        requested = request.headers.get("x-tenant", "")
        if requested not in MEMBERSHIPS.get(principal.subject, set()):
            return JSONResponse({"error": "tenant forbidden"}, status_code=403)
        request.state.verified_identity = (requested, principal.subject, principal.scopes)
        return await call_next(request)

class VerifiedContextBuilder(DefaultServerCallContextBuilder):
    def build(self, request):
        tenant, subject, scopes = request.state.verified_identity
        context = super().build(request)  # keeps A2A-Version and extension headers
        context.user = ScopedUser(f"{tenant}\x1f{subject}")
        context.tenant = tenant
        context.state["scopes"] = scopes
        context.state["headers"].pop("authorization", None)
        return context

@asynccontextmanager
async def lifespan(app):
    yield
    await handler.aclose()

app = Starlette(routes=[
    *create_agent_card_routes(card),
    *create_jsonrpc_routes(handler, rpc_url="/invoice/a2a",
                           context_builder=VerifiedContextBuilder()),
], lifespan=lifespan)
app.add_middleware(VerifiedIngress)
```

The route factory calls the builder and passes its result to the real SDK handler. The default builder preserves `A2A-Version`; constructing only `ServerCallContext(user=...)` would accidentally make a 1.0 call look like legacy 0.3. The owner key combines trusted tenant and subject, which the SDK's `resolve_user_scope` reads from `context.user.user_name`. The method map is an application policy for this card; update and test it whenever a binding or method is added. This block is an integration excerpt because `handler`, `card`, and production membership storage come from the application; the linked route fixture below is complete and executable. [Multi-Tenant Scoping](04_multi_tenant_scoping.md) develops the row predicate.

Run the [two-principal route fixture](../examples/production/auth_route_fixture.py) with `a2a-sdk[http-server]==1.2.2`. It uses local test tokens to isolate the route-to-handler handoff from JWT network setup, starts a Beta task, and proves Acme gets task-not-found for live `GetTask`, `CancelTask`, `SubscribeToTask`, and push-config read. The fixture is local evidence for SDK context propagation, not a test of your issuer, database, broker, or callback delivery.

OIDC discovery supplies issuer metadata such as `jwks_uri` and `token_endpoint`; it does not dictate access-token format. Validate JWT access tokens only when the issuer documents that profile. Otherwise call the issuer's authenticated introspection endpoint and enforce `active`, issuer/audience/resource, subject, expiry, and scopes.

---

## 6. mTLS for Zero-Trust Enterprise Deployments

In a zero-trust mesh, bearer tokens are still bearer tokens — steal one and you are in. **Mutual TLS** binds the connection itself to a verified client certificate, so a leaked token alone is not enough. Declare it in the card with the `mtlsSecurityScheme` oneof:

```json
{
"securitySchemes": {
  "mesh-mtls": {
    "mtlsSecurityScheme": {
      "description": "Caller must present a cert from the Acme internal CA"
    }
  }
}
}
```

mTLS is enforced at the TLS-termination layer, not in application code. Two patterns:

- **Service mesh (Istio/Linkerd)** — sidecars negotiate mTLS transparently; A2A code never sees certs. Preferred for large fleets.
- **App-terminated TLS** — the agent's web server (or a reverse proxy) requests a client cert and verifies it against the internal CA. The verified cert subject (`CN`/`SPIFFE ID`) becomes the agent identity.

```python
# Uvicorn terminating mTLS directly (small deployments / no mesh).
uvicorn.run(
    app,
    host="0.0.0.0", port=8443,
    ssl_certfile="server.crt", ssl_keyfile="server.key",
    ssl_ca_certs="internal-ca.crt",
    ssl_cert_reqs=ssl.CERT_REQUIRED,   # REQUIRED — CERT_OPTIONAL silently allows no-cert clients
)
```

✅ Combine mTLS with OAuth2 when both are declared in one security-requirement entry: mTLS proves which workload connected; the access token carries the delegated identity and scopes.

⚠️ `ssl.CERT_OPTIONAL` accepts connections with **no** client cert at all. Always use `CERT_REQUIRED` when mTLS is the security boundary.

---

## 7. Authorization: Beyond "Who Are You?"

Authentication answers *who*. **Authorization** answers *what may they do* — and A2A pushes this entirely onto your application.

- **Scope operations and resources per caller.** A caller with `tasks:read` may inspect only tasks it owns; `tasks:write` does not grant access to another tenant's task.
- **Per-agent identity.** The JWT `sub` (or the mTLS cert subject) is a stable identity for the *calling agent*. Use it for allow-lists ("only the `procurement-agent` may submit invoices over $50k"), rate limiting, and audit trails.
- **Least privilege.** Issue each agent its own OAuth client with the minimum scope set. Never share one client across a fleet — you lose per-agent attribution and blast-radius control.

```python
# Skill routing is application policy: core Message has no invoked-skill field.
# This service negotiated and validates `urn:acme:routing:v1`, whose DataPart
# carries {"skillId": "..."}. Reject missing/unknown extension payloads.
SKILL_SCOPE = {
    "submit-invoice": "tasks:write",
    "invoice-status": "tasks:read",
}

def authorize_skill(validated_routing_part: dict, principal: Principal) -> None:
    skill_id = validated_routing_part["skillId"]
    needed = SKILL_SCOPE.get(skill_id)
    if needed is None or needed not in principal.scopes:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            detail="Operation is not permitted")
```

Resource ownership is mandatory even after scope checks. Resolve the owner from the verified principal, never from request data:

```python
async def get_owned_task(task_id: str, principal: Principal) -> Task:
    task = await tasks.get_by_owner(owner_id=principal.subject, task_id=task_id)
    if task is None:
        # Same response for absent and inaccessible IDs: do not disclose existence.
        raise TaskNotFound()
    return task

# Apply the same owner/tenant predicate before:
# GetTask, ListTasks, CancelTask, SubscribeToTask,
# Get/List/DeleteTaskPushNotificationConfig, and every update/delete.
```

Attack trace: `agent-a` has a valid `tasks:read` token and guesses `agent-b`'s task ID. The scope check passes, but `get_by_owner("agent-a", guessed_id)` returns no row, so the response is indistinguishable from an unknown ID and no status, artifact, history, subscription, or push target leaks.

> **Principle**: Authentication is a gate at the door; authorization is a guard at every room. A2A gives you the gate (HTTP + OpenAPI schemes); the guards are yours to build.

---

## 8. The Authenticated Extended Card

The public Agent Card at `/.well-known/agent-card.json` is intentionally minimal — anyone can read it. An agent may also expose an **extended card** with additional skills, capabilities, or configuration visible only to authenticated callers.

It is fetched via the `GetExtendedAgentCard` operation. The catch:

> **Rule**: A client MUST authenticate the `GetExtendedAgentCard` call using a scheme declared in the **public** card's `securitySchemes`. The extended card is gated by the same auth machinery as every other RPC — the public card bootstraps trust.

The flow: fetch the public card → see `capabilities.extendedAgentCard` → authenticate → call `GetExtendedAgentCard` → receive the richer card → use *its* skills and security requirements going forward.

✅ Use this to hide privileged or internal-only skills (e.g. `admin:reconcile-ledger`) from the public internet while still publishing a discoverable base card.

---

## 9. Failure Modes

Each of these has shipped to production somewhere. Audit your deployment against the list.

| ❌ Anti-pattern | Why it bites | ✅ Fix |
| --------------- | ------------ | ------ |
| **Credentials in the Agent Card** | The card is public at a well-known URL — a `client_secret` or token there is fully exposed | Card declares *schemes only*; fetch credentials out-of-band |
| **No `aud` validation** (token confusion) | A token minted for *another* agent is accepted here — an attacker replays a token they legitimately hold elsewhere | Always pass `audience=` to `jwt.decode` and `require` the `aud` claim |
| **Long-lived static API keys** | A leaked key is valid forever; no rotation, no expiry, no per-call attribution | Prefer short-lived OAuth2 tokens; if API keys are unavoidable, rotate them and scope them tightly |
| **Skipping signature verification** | `jwt.decode(..., options={"verify_signature": False})` left in "to debug" — anyone can forge any claim | Never disable signature checks; verify against JWKS |
| **401 on `/.well-known` but not the RPC endpoint** | Auth middleware mounted only on the well-known path. The RPC endpoint — where the *real* work happens — is wide open | Guard the **RPC endpoint** (`SendMessage`, `GetTask`, `CancelTask`, etc.); the public card path is *meant* to be unauthenticated |
| **`ssl.CERT_OPTIONAL` for mTLS** | Clients with no certificate are silently accepted | Use `ssl.CERT_REQUIRED` when mTLS is your boundary |
| **Bearer 401 without `WWW-Authenticate`** | Spec violation; well-behaved clients cannot discover how to retry | Always set the `WWW-Authenticate` header on a 401 |
| **One OAuth client shared across the fleet** | All agents share an identity — no per-agent allow-listing, no audit attribution, huge blast radius on leak | One OAuth client (and minimal scope set) per agent |

> **Key insight**: Authentication establishes a principal; it does not authorize a resource. Carry the verified owner/tenant identity into every task and push-configuration query, including reads and subscriptions, and return the same not-found result for missing and inaccessible IDs.

## Retain the authorization chain

- The card advertises acceptable schemes; credentials travel in HTTP or transport metadata, never in an A2A `Message`.
- JWT signature, issuer, audience, and expiry establish a principal. A valid token for another audience still fails before an A2A handler runs.
- Scopes permit operation types; a verified tenant/owner predicate decides which Task is accessible.
- Ingress validation has no effect on SDK storage unless the transport adapter carries that principal into `ServerCallContext`.

**Q:** A JWT has a valid signature and `tasks:read`, but its `aud` names a different agent. Does `GetTask` run?

<details><summary>Answer</summary>

No. This agent is not the token's intended receiver. The audience check fails at ingress before scope or row ownership checks.

</details>

**Q:** The FastAPI dependency succeeds, but `DatabaseTaskStore` sees an unauthenticated user. What boundary is missing?

<details><summary>Answer</summary>

The HTTP-to-SDK adapter did not put the verified principal into the `ServerCallContext` passed to the handler. A successful dependency only validates the route; it does not change SDK context by itself.

</details>

**Try it:** Adapt a `tasks:read` endpoint for a caller belonging to `tenant-A`. After JWT validation, what should `ServerCallContext.user.user_name` contain before `GetTask`? Use the construction in [Multi-Tenant Scoping](04_multi_tenant_scoping.md) as a hint.

<details><summary>Worked answer</summary>

It should contain a canonical key derived from the verified membership pair, such as `tenant-A\x1fagent-A`. The adapter must pass that context into the handler. The store's owner resolver then applies the same key on `GetTask`, so a guessed task from another tenant yields no row.

</details>

---

**Next**: [Part 2: Security Hardening](02_security_hardening.md)
