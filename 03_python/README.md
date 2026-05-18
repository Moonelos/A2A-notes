# Python SDK

> Building real A2A servers and clients with the official `a2a-sdk` package.

[![a2a-sdk](https://img.shields.io/badge/a2a--sdk-1.0.3-3776AB.svg?logo=python&logoColor=white)](https://pypi.org/project/a2a-sdk/)
[![Python](https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-supported-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

---

## Contents

| File | Topic | Description |
|------|-------|-------------|
| [01_sdk_setup.md](01_sdk_setup.md) | Setup | Installing `a2a-sdk`, optional extras, project layout, and version compatibility |
| [02_building_a_server.md](02_building_a_server.md) | Server | Implementing `AgentExecutor`, request handlers, and serving over Starlette/FastAPI |
| [03_building_a_client.md](03_building_a_client.md) | Client | Resolving Agent Cards, `ClientFactory`, sending tasks, and consuming streams |

---

## Reading Order

1. **SDK Setup** — get the package and project skeleton in place
2. **Building a Server** — expose an agent over A2A
3. **Building a Client** — call other agents from your code

---

## Prerequisites

- [Transport & RPC](../02_protocol/02_transport_and_rpc.md) — what the SDK abstracts
- [Task Lifecycle](../02_protocol/03_task_lifecycle.md) — the states your executor must drive
- Python 3.10+, comfort with `async`/`await`
