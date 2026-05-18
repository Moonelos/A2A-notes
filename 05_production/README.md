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

---

## Reading Order

1. **Authentication** — never expose an unauthenticated agent endpoint
2. **Security Hardening** — defend against the documented threat model
3. **Scaling & Deployment** — run multiple replicas with shared state

---

## Prerequisites

- [The Agent Card](../02_protocol/01_agent_card.md) — where security schemes are declared
- [Task Lifecycle](../02_protocol/03_task_lifecycle.md) — task stores must persist these states
- [Building a Server](../03_python/02_building_a_server.md) — the deployable unit
