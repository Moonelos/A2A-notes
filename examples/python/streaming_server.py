"""Deterministic local A2A report agent: real JSON-RPC and SSE, no LLM.

Run from the repository root:
  uv run --with 'a2a-sdk[http-server]==1.1.2' --with uvicorn python -m examples.python.streaming_server

This unauthenticated loopback lab uses an in-memory TaskStore. It does not
provide durable execution, external sales data or production authentication.
"""

import argparse
import asyncio
import re
from contextlib import asynccontextmanager

import uvicorn
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message, new_text_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState


PROGRESS_KEY = "com.example.reportProgress.v1"


class ReportExecutor(AgentExecutor):
    def __init__(self, delay: float = 0.15):
        self.delay = delay

    async def execute(self, context, event_queue) -> None:
        text = context.get_user_input()
        if text == "What is 2 + 2?" and context.current_task is None:
            # A direct reply still has its server-issued Message and context IDs.
            # The SDK request context allocates a context even without a Task.
            await event_queue.enqueue_event(new_text_message(
                "2 + 2 = 4", context_id=context.context_id,
            ))
            return

        existing = context.current_task
        task = existing or new_task_from_user_message(context.message)
        if existing is None:
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)

        def agent_message(message):
            return new_text_message(message, context_id=task.context_id, task_id=task.id)

        match = re.search(r"\b(October|November)\s+2026\b", text, flags=re.IGNORECASE)
        if match is None:
            await updater.requires_input(agent_message(
                "For which month should I generate the report? Use October 2026 or November 2026."
            ))
            return
        month = match.group(1).title()

        await updater.start_work(agent_message("Fetching sales"))
        for completed, step, message in (
            (1, "fetch_sales", "Fetched sales"),
            (2, "build_report", "Built report"),
        ):
            await asyncio.sleep(self.delay)
            # An application convention inside a standard statusUpdate event.
            # This is not a new protocol event type or negotiated extension.
            await updater.update_status(
                TaskState.TASK_STATE_WORKING,
                message=agent_message(message),
                metadata={PROGRESS_KEY: {
                    "event": "step_completed", "step": step,
                    "completed": completed, "total": 2,
                }},
            )

        await updater.add_artifact(
            [new_text_part(f"{month} sales: ")], artifact_id="art-report",
            name="sales-report", append=False, last_chunk=False,
        )
        await asyncio.sleep(self.delay)
        await updater.add_artifact(
            [new_text_part("$150,000.")], artifact_id="art-report",
            append=True, last_chunk=True,
        )
        await asyncio.sleep(self.delay)
        await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        task = context.current_task
        if task is not None:
            await TaskUpdater(event_queue, task.id, task.context_id).cancel()


def create_app(port: int = 9998, delay: float = 0.15) -> Starlette:
    card = AgentCard(
        name="Streaming Report Lab",
        description="A deterministic report agent for learning Messages, Tasks and streaming.",
        version="0.1.0",
        supported_interfaces=[AgentInterface(
            url=f"http://127.0.0.1:{port}", protocol_binding="JSONRPC", protocol_version="1.0",
        )],
        capabilities=AgentCapabilities(streaming=True),
        default_input_modes=["text/plain"], default_output_modes=["text/plain"],
        skills=[AgentSkill(
            id="report", name="Sales report", description="Generate a deterministic monthly report.",
            tags=["tutorial", "report"],
        )],
    )
    handler = DefaultRequestHandler(
        agent_executor=ReportExecutor(delay), task_store=InMemoryTaskStore(), agent_card=card,
    )

    @asynccontextmanager
    async def lifespan(app):
        yield
        await handler.aclose()

    return Starlette(
        routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")],
        lifespan=lifespan,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=9998)
    parser.add_argument("--delay", type=float, default=0.15, help="Seconds between observable updates")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay must be nonnegative")
    uvicorn.run(create_app(args.port, args.delay), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
