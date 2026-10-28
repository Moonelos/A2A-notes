"""Print what a real SDK client sends and receives in the streaming lab.

Start examples.python.streaming_server, then run from the repository root:
  uv run --with 'a2a-sdk==1.1.2' python -m examples.python.streaming_client

Use --scenario conversation for a clarification and a new Task in the same
context, or --scenario direct for a direct Message. Default: --scenario stream.
"""

import argparse
import asyncio
import json
from uuid import uuid4

import httpx
from google.protobuf.json_format import MessageToDict

from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.types import Message, Part, Role, SendMessageRequest
from a2a.utils import TransportProtocol

from .client_workflow import ClientView, render_parts


PROGRESS_KEY = "com.example.reportProgress.v1"


def user_message(text, *, task_id="", context_id="", reference_task_ids=()):
    return Message(
        message_id=f"msg-{uuid4()}", role=Role.ROLE_USER, parts=[Part(text=text)],
        task_id=task_id, context_id=context_id, reference_task_ids=reference_task_ids,
    )


async def run_turn(client, message: Message) -> ClientView:
    # This is the Message payload, not a hand-built JSON-RPC wire envelope.
    # The SDK selects SendMessage/SendStreamingMessage and creates its RPC ID.
    print("SEND Message " + json.dumps(MessageToDict(message), ensure_ascii=False), flush=True)
    view = ClientView()
    stream = client.send_message(request=SendMessageRequest(message=message))
    try:
        async for event in stream:
            payload = event.WhichOneof("payload")
            view.apply(event)
            print("RECEIVED " + str(payload) + " " + json.dumps(MessageToDict(event), ensure_ascii=False), flush=True)
            if payload == "status_update":
                metadata = MessageToDict(event.status_update.metadata)
                if PROGRESS_KEY in metadata:
                    print("PROGRESS " + json.dumps(metadata[PROGRESS_KEY], sort_keys=True), flush=True)
            for artifact in view.artifacts.values():
                text = "".join(part.text for part in artifact.parts if part.WhichOneof("content") == "text")
                print(f"ACCUMULATED {artifact.artifact_id}: {text}", flush=True)
            for line in render_parts(view.message_parts or view.status_parts):
                print("CONTENT " + line, flush=True)
    finally:
        await stream.aclose()
    print(f"OUTCOME {view.outcome}; task={view.task_id or '(none)'}; context={view.context_id or '(none)'}", flush=True)
    return view


async def run_scenario(client, scenario: str):
    if scenario == "direct":
        return await run_turn(client, user_message("What is 2 + 2?"))
    if scenario == "stream":
        return await run_turn(client, user_message("Generate a sales report for October 2026"))

    waiting = await run_turn(client, user_message("Generate a sales report"))
    if waiting.outcome != "needs_input":
        raise RuntimeError("Expected the lab's month clarification")
    completed = await run_turn(client, user_message("October 2026", task_id=waiting.task_id))
    if completed.outcome != "completed":
        raise RuntimeError("The clarified report did not complete")
    return await run_turn(client, user_message(
        "Generate a sales report for November 2026",
        context_id=completed.context_id, reference_task_ids=[completed.task_id],
    ))


async def main(url: str, scenario: str):
    async with httpx.AsyncClient(timeout=10) as http:
        card = await A2ACardResolver(httpx_client=http, base_url=url).get_agent_card()
        if card.security_requirements:
            raise RuntimeError("This tutorial client does not configure protected-agent credentials")
        config = ClientConfig(
            httpx_client=http, streaming=scenario == "stream",
            supported_protocol_bindings=[TransportProtocol.JSONRPC],
        )
        async with ClientFactory(config).create(card) as client:
            await asyncio.wait_for(run_scenario(client, scenario), timeout=30)


def cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:9998")
    parser.add_argument("--scenario", choices=["stream", "conversation", "direct"], default="stream")
    args = parser.parse_args()
    asyncio.run(main(args.url, args.scenario))


if __name__ == "__main__":
    cli()
