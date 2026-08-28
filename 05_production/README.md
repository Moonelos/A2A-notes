# Production

> Taking A2A from a working prototype to a secure, observable, horizontally-scaled deployment.

[![Auth](https://img.shields.io/badge/Auth-OAuth2_/_OIDC_/_mTLS-EB5424.svg?logo=auth0&logoColor=white)](https://a2a-protocol.org/latest/topics/enterprise-ready/)
[![Docker](https://img.shields.io/badge/Docker-deploy-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)

---

## Contents

| File | Topic | Description |
|------|-------|-------------|
| [01_authentication.md](01_authentication.md) | Authentication | Declaring and enforcing API key, OAuth2, OIDC, and mTLS auth between agents |
| [02_security_hardening.md](02_security_hardening.md) | Security | Agent Card signing, input validation, the A2A threat model, defensive patterns |
| [03_scaling_deployment.md](03_scaling_deployment.md) | Scale & ops | Stateless servers, shared task stores, push infrastructure, observability |
| [04_multi_tenant_scoping.md](04_multi_tenant_scoping.md) | Isolation | Verified tenant routing and owner-scoped resources, jobs, events, and push configs |
| [05_conformance_and_interoperability.md](05_conformance_and_interoperability.md) | Release proof | Inspector/TCK and cross-binding contract tests |

---

## Reading Order

1. **Authentication** — establish and carry a verified principal
2. **Security Hardening** + **Multi-Tenant Scoping** — secure single-replica milestone
3. **Scaling & Deployment** — continue for replicas, durable jobs, or operational reliability
4. **Conformance & Interoperability** — release gate the deployed Agent Card and all advertised bindings

---

## Prerequisites

- [The Agent Card](../02_protocol/01_agent_card.md) — where security schemes are declared
- [Task Lifecycle](../02_protocol/03_task_lifecycle.md) — task stores must persist these states
- [Building a Server](../03_python/02_building_a_server.md) — the deployable unit
