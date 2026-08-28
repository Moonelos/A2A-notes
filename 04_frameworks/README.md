# Frameworks

> Exposing agents built with popular frameworks over A2A — and consuming remote A2A agents from inside them.

[![LangGraph](https://img.shields.io/badge/LangGraph-integrated-1C3C3C.svg)](https://langchain-ai.github.io/langgraph/)
[![Google ADK](https://img.shields.io/badge/Google_ADK-integrated-4285F4.svg?logo=googlecloud&logoColor=white)](https://google.github.io/adk-docs/)
[![CrewAI](https://img.shields.io/badge/CrewAI-integrated-FF5A50.svg)](https://www.crewai.com/)

---

## Contents

| File | Topic | Description |
|------|-------|-------------|
| [01_langchain_langgraph.md](01_langchain_langgraph.md) | LangChain/LangGraph | Wrapping a LangGraph agent as an A2A server; calling remote agents as tools |
| [02_google_adk.md](02_google_adk.md) | Google ADK | ADK's native A2A support — `to_a2a()` exposure and `RemoteA2aAgent` consumption |
| [03_crewai_and_others.md](03_crewai_and_others.md) | CrewAI & others | A2A integration patterns for CrewAI, Semantic Kernel, LlamaIndex, and AG2/AutoGen |

---

## Choose Your Framework

- **LangChain/LangGraph** → [run its minimal adapter](01_langchain_langgraph.md), then stop after exposure or continue to its remote-tool section.
- **Google ADK** → [use ADK's native branch](02_google_adk.md), then stop after `to_a2a()` or continue to `RemoteA2aAgent`.
- **CrewAI, Semantic Kernel, Microsoft Agent Framework, LlamaIndex, or AG2** → jump to the [branch table](03_crewai_and_others.md#choose-a-branch-before-you-read-the-implementations) and read only your framework plus the shared gotchas.

For an adapter beyond those branches, return to [Building a Server](../03_python/02_building_a_server.md). For custom low-level consumption, use [Building a Client](../03_python/03_building_a_client.md).

---

## Prerequisites

- [The Agent Card](../02_protocol/01_agent_card.md) — what every framework must publish
- [Building a Server](../03_python/02_building_a_server.md) — the SDK primitives these integrations build on
- Familiarity with at least one of the frameworks covered
