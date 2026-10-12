"""Dependency-free contract fixture for framework-event to A2A-task projection.

This models the adapter boundary; it does not import or test any framework or SDK.
Run: python3 _meta/delegation/frameworks/adapter_contract.py
"""

from dataclasses import dataclass, field


@dataclass
class Task:
    task_id: str
    context_id: str
    state: str = "TASK_STATE_WORKING"
    artifact: str = ""
    events: list[str] = field(default_factory=list)


class Adapter:
    def __init__(self, task: Task, checkpoint: dict[str, str]):
        self.task = task
        self.checkpoint = checkpoint

    def project(self, event: str, value: str) -> None:
        if event == "progress":
            self.task.events.append("working: " + value)
        elif event == "pause":
            self.checkpoint[self.task.context_id] = value
            self.task.state = "TASK_STATE_INPUT_REQUIRED"
            self.task.events.append("input-required: " + value)
        elif event == "result":
            self.task.artifact = value
            self.task.state = "TASK_STATE_COMPLETED"
            self.task.events.append("artifact: " + value)
            self.task.events.append("completed")
        else:
            raise ValueError(event)

    def resume(self, task_id: str, context_id: str, answer: str) -> None:
        if (task_id, context_id) != (self.task.task_id, self.task.context_id):
            raise ValueError("continuation identity mismatch")
        pending = self.checkpoint.pop(context_id, None)
        if self.task.state != "TASK_STATE_INPUT_REQUIRED" or pending is None:
            raise ValueError("no saved pause")
        self.task.state = "TASK_STATE_WORKING"
        self.task.events.append("resumed: " + answer)
        self.project("result", "approved " + pending + " with " + answer)


def main() -> None:
    task = Task("task-7", "ctx-7")
    checkpoint: dict[str, str] = {}
    first_replica = Adapter(task, checkpoint)
    first_replica.project("progress", "approval ticket ticket-9 created")
    first_replica.project("pause", "ticket-9")
    assert task.state == "TASK_STATE_INPUT_REQUIRED"
    second_replica = Adapter(task, checkpoint)
    try:
        second_replica.resume("task-8", "ctx-8", "yes")
    except ValueError as exc:
        assert str(exc) == "continuation identity mismatch"
    else:
        raise AssertionError("changed identity was accepted")
    second_replica.resume("task-7", "ctx-7", "yes")
    assert task.state == "TASK_STATE_COMPLETED"
    assert task.artifact == "approved ticket-9 with yes"
    assert checkpoint == {}
    print("task-7 ctx-7: " + " -> ".join(task.events))
    print("changed task/context rejected; final state TASK_STATE_COMPLETED")


if __name__ == "__main__":
    main()
