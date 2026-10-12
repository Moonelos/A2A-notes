"""Local, model-free LangGraph to A2A integration fixture.

Pinned environment: a2a-sdk[http-server,sql]==1.1.2, langgraph==1.2.14,
langgraph-checkpoint-sqlite==3.0.3, uvicorn. Set FRAMEWORK_FIXTURE_DB to
the same SQLite file for both server processes.
"""

import os
from contextlib import asynccontextmanager
from typing import TypedDict

import uvicorn
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from sqlalchemy.ext.asyncio import create_async_engine
from starlette.applications import Starlette

from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import DatabaseTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, TaskState

DB = os.environ.get("FRAMEWORK_FIXTURE_DB", "/tmp/a2a-langgraph-fixture.sqlite")
PORT = int(os.environ.get("FRAMEWORK_FIXTURE_PORT", "10081"))


class ApprovalState(TypedDict):
    request: str
    answer: str


def approve(state: ApprovalState) -> dict[str, str]:
    answer = interrupt({"question": "Approve " + state["request"] + "?"})
    return {"answer": str(answer)}


builder = StateGraph(ApprovalState)
builder.add_node("approve", approve)
builder.add_edge(START, "approve")
builder.add_edge("approve", END)


class GraphExecutor(AgentExecutor):
    graph = None

    async def execute(self, context, event_queue) -> None:
        task = context.current_task
        if task is None:
            task = new_task_from_user_message(context.message)
            await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        config = {"configurable": {"thread_id": task.context_id}}
        saved = await self.graph.aget_state(config)
        if saved.next:
            result = await self.graph.ainvoke(Command(resume=context.get_user_input()), config)
        else:
            await updater.start_work()
            result = await self.graph.ainvoke(
                {"request": context.get_user_input(), "answer": ""}, config
            )
        if "__interrupt__" in result:
            await updater.update_status(
                TaskState.TASK_STATE_INPUT_REQUIRED,
                updater.new_agent_message([new_text_part("Approval required")]),
            )
        else:
            await updater.add_artifact(
                [new_text_part("approved=" + result["answer"])], name="approval"
            )
            await updater.complete()

    async def cancel(self, context, event_queue) -> None:
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel()


executor = GraphExecutor()
card = AgentCard(
    name="LangGraph Approval Fixture",
    description="Pauses for one approval and resumes the same Task.",
    version="0.1.0",
    supported_interfaces=[AgentInterface(
        url=f"http://127.0.0.1:{PORT}", protocol_binding="JSONRPC", protocol_version="1.0"
    )],
    capabilities=AgentCapabilities(),
    default_input_modes=["text/plain"],
    default_output_modes=["text/plain"],
    skills=[AgentSkill(id="approval", name="Approval", description="Approval fixture", tags=["test"])],
)
engine = create_async_engine("sqlite+aiosqlite:///" + DB)
handler = DefaultRequestHandler(executor, DatabaseTaskStore(engine), card)


@asynccontextmanager
async def lifespan(app):
    async with AsyncSqliteSaver.from_conn_string(DB) as saver:
        executor.graph = builder.compile(checkpointer=saver)
        yield
    await handler.aclose()
    await engine.dispose()


app = Starlette(
    routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, rpc_url="/")],
    lifespan=lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT)
