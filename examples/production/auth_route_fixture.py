"""Local A2A route isolation fixture, SDK 1.2.2. Run with its http-server extra."""
from dataclasses import dataclass
import asyncio
import threading
from contextlib import asynccontextmanager
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.testclient import TestClient
from a2a.auth.user import User
from a2a.helpers import new_task_from_user_message, new_text_part
from a2a.server.agent_execution import AgentExecutor
from a2a.server.context import ServerCallContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.routes.common import DefaultServerCallContextBuilder
from a2a.server.tasks import InMemoryTaskStore, InMemoryPushNotificationConfigStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
started = threading.Event()
release = threading.Event()
active_task = {}
PRINCIPALS = {"a-local-token": ("tenant-A", "agent-A"), "b-local-token": ("tenant-B", "agent-B")}
@dataclass(frozen=True)
class ScopedUser(User):
    key: str
    @property
    def is_authenticated(self) -> bool: return True
    @property
    def user_name(self) -> str: return self.key
class Ingress(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        identity = PRINCIPALS.get(token)
        if identity is None:
            return JSONResponse({"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"})
        requested = request.headers.get("x-tenant", identity[0])
        if requested != identity[0]:
            return JSONResponse({"error": "tenant forbidden"}, status_code=403)
        request.state.identity = identity
        return await call_next(request)
class VerifiedContextBuilder(DefaultServerCallContextBuilder):
    def build(self, request):
        tenant, subject = request.state.identity
        context = super().build(request)
        context.user = ScopedUser(f"{tenant}\x1f{subject}")
        context.tenant = tenant
        context.state["owner_id"] = subject
        context.state["headers"].pop("authorization", None)
        return context
class Echo(AgentExecutor):
    async def execute(self, context, event_queue):
        task = context.current_task or new_task_from_user_message(context.message)
        await event_queue.enqueue_event(task)
        updater = TaskUpdater(event_queue, task.id, task.context_id)
        await updater.start_work()
        active_task["id"] = task.id
        started.set()
        await asyncio.to_thread(release.wait)
        await updater.add_artifact([new_text_part("done")], name="result")
        await updater.complete()
    async def cancel(self, context, event_queue):
        task = context.current_task
        await TaskUpdater(event_queue, task.id, task.context_id).cancel()
card = AgentCard(name="Scoped Echo", description="Local identity handoff fixture", version="0.1.0", supported_interfaces=[AgentInterface(url="http://testserver/a2a", protocol_binding="JSONRPC", protocol_version="1.0")], capabilities=AgentCapabilities(streaming=True, push_notifications=True), default_input_modes=["text/plain"], default_output_modes=["text/plain"], skills=[AgentSkill(id="echo", name="Echo", description="Echo", tags=["test"])])
handler = DefaultRequestHandler(agent_executor=Echo(), task_store=InMemoryTaskStore(), push_config_store=InMemoryPushNotificationConfigStore(), agent_card=card)
@asynccontextmanager
async def lifespan(app):
    yield
    await handler.aclose()
app = Starlette(routes=create_jsonrpc_routes(handler, rpc_url="/a2a", context_builder=VerifiedContextBuilder()), lifespan=lifespan)
app.add_middleware(Ingress)
def rpc(client, token, method, params, tenant=None):
    headers={"Authorization": f"Bearer {token}", "A2A-Version": "1.0"}
    if tenant: headers["X-Tenant"] = tenant
    response=client.post("/a2a", headers=headers, json={"jsonrpc":"2.0","id":"test","method":method,"params":params})
    return response.status_code, response.json()
if __name__ == "__main__":
    with TestClient(app) as client:
        result = {}
        def send_b():
            result["sent"] = rpc(client,"b-local-token","SendMessage",{"message":{"messageId":"m-1","role":"ROLE_USER","parts":[{"text":"hello"}]}})
        sender = threading.Thread(target=send_b)
        sender.start()
        assert started.wait(5), "executor did not start"
        task_id = active_task["id"]
        for method,params in [
            ("GetTask", {"id": task_id}),
            ("CancelTask", {"id": task_id}),
            ("GetTaskPushNotificationConfig", {"taskId": task_id, "id": "cfg-1"}),
            ("SubscribeToTask", {"id": task_id}),
        ]:
            status, denied = rpc(client,"a-local-token",method,params)
            assert status == 200 and denied["error"]["code"] == -32001, (method, denied)
            print(f"{method}: tenant-A -> TASK_NOT_FOUND")
        status, denied = rpc(client,"a-local-token","GetTask",{"id":task_id},tenant="tenant-B")
        assert status == 403
        print("forged X-Tenant: 403")
        status, allowed = rpc(client,"b-local-token","GetTask",{"id":task_id})
        assert status == 200 and allowed["result"]["id"] == task_id
        print("GetTask: tenant-B -> WORKING")
        release.set()
        sender.join(timeout=5)
        assert not sender.is_alive(), "sender did not finish"
        assert result["sent"][1]["result"]["task"]["status"]["state"] == "TASK_STATE_COMPLETED"
        print("SendMessage: tenant-B -> COMPLETED")
