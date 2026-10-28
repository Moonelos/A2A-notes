"""Connect the tutorial's response consumer to the local echo server.

Run from the repository root:
  uv run --with 'a2a-sdk==1.1.2' python -m examples.python.report_client

The echo server must already be running at http://127.0.0.1:9999.
This is an unauthenticated tutorial client; configure section 7's credentials
before adapting it to a protected service. Each observation is bounded, and
reconnecting never sends the user's original content again.
"""

import asyncio
import os
from uuid import uuid4

import httpx

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.client.errors import A2AClientError, A2AClientTimeoutError, AgentCardResolutionError
from a2a.types import Message, Part, Role, SendMessageRequest, StreamResponse
from a2a.utils import TransportProtocol

from .client_workflow import ClientView, consume, poll_task, render_parts, subscribe_or_get


def user_request(text: str, *, task_id: str = "", context_id: str = ""):
    return SendMessageRequest(message=Message(
        message_id=f"msg-{uuid4()}", role=Role.ROLE_USER,
        task_id=task_id, context_id=context_id, parts=[Part(text=text)],
    ))


def display(view: ClientView) -> None:
    print(f"outcome: {view.outcome}")
    print(f"task: {view.task_id or '(none)'}; context: {view.context_id or '(none)'}")
    for line in render_parts(view.message_parts or view.status_parts):
        print(line)
    for artifact_id, artifact in view.artifacts.items():
        print(f"artifact {artifact_id}: {artifact.name or '(unnamed output)'}")
        for line in render_parts(artifact.parts):
            print(line)


async def discover(http, base_url):
    resolver = A2ACardResolver(httpx_client=http, base_url=base_url)
    for attempt in range(3):
        try:
            return await resolver.get_agent_card()
        except AgentCardResolutionError:
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)


def transient_transport_error(error: Exception) -> bool:
    # SDK 1.1.2 wraps RequestError in A2AClientError; HTTP status/auth and
    # decode failures are different errors and must not be retried here.
    return (
        isinstance(error, (httpx.RequestError, A2AClientTimeoutError))
        or isinstance(error.__cause__, httpx.RequestError)
    )


async def observe_known_task(client, view: ClientView, *, streaming: bool):
    for attempt in range(3):
        try:
            if streaming:
                await subscribe_or_get(client, view, stop_on_interrupted=True)
            if view.outcome in {"active", "unknown"}:
                task = await poll_task(client, view.task_id, interval=2, max_wait=240)
                view.apply(StreamResponse(task=task))
            return view.outcome
        except (httpx.RequestError, A2AClientError) as error:
            if not transient_transport_error(error) or attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)


async def send_and_observe(client, request, view: ClientView, *, streaming: bool):
    try:
        await consume(client.send_message(request=request), view, stop_on_interrupted=True)
    except (httpx.RequestError, A2AClientError) as error:
        if not transient_transport_error(error):
            raise
        if not view.task_id:
            raise RuntimeError("Outcome unknown: no Task ID received; content was not resent") from error
        # A state may have arrived before the drop but not all output. Reconcile
        # even if that last observed state was terminal.
        return await observe_known_task(client, view, streaming=streaming)
    if view.task_id and view.outcome in {"active", "unknown"}:
        return await observe_known_task(client, view, streaming=streaming)
    return view.outcome


async def main() -> None:
    base_url = os.environ.get("A2A_AGENT_URL", "http://127.0.0.1:9999")
    async with httpx.AsyncClient(timeout=30) as http:
        card = await discover(http, base_url)
        if card.security_requirements:
            raise RuntimeError("Configure the advertised credentials before using this tutorial client")
        streaming = card.capabilities.streaming
        config = ClientConfig(
            httpx_client=http, streaming=streaming, polling=not streaming,
            supported_protocol_bindings=[TransportProtocol.JSONRPC, TransportProtocol.HTTP_JSON],
        )
        async with ClientFactory(config).create(card) as client:
            request = user_request("Generate a sales report for October 2026")
            for turn in range(3):
                view = ClientView()
                await asyncio.wait_for(
                    send_and_observe(client, request, view, streaming=streaming), timeout=300,
                )
                display(view)
                if view.outcome == "needs_input":
                    if turn == 2:
                        raise RuntimeError("Clarification limit reached; Task remains paused")
                    answer = await asyncio.to_thread(input, "Your answer: ")
                    request = user_request(answer, task_id=view.task_id, context_id=view.context_id)
                elif view.outcome == "needs_auth":
                    print("Complete the negotiated external authorization, then observe this Task again.")
                    return
                elif view.outcome in {"message", "completed", "failed", "canceled", "rejected"}:
                    return
                else:
                    raise RuntimeError(f"Observation ended without an actionable state: {view.outcome}")


if __name__ == "__main__":
    asyncio.run(main())
