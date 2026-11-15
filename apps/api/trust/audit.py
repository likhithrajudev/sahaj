"""One Trace per turn: every step is recorded (already masked) and saved to the ledger."""
import time
import uuid

from observability import metrics
from trust import ledger


class Trace:
    def __init__(self, subject: str):
        self.id = uuid.uuid4().hex
        self.subject = subject
        self.steps = []

    def add(self, step: str, **data) -> None:
        self.steps.append({"step": step, "t": round(time.time(), 3), **data})
        metrics.observe(step, data)

    def withhold(self, step: str, field: str) -> None:
        """Replace one recorded field with a marker. Used for turns where the person gave personal details."""
        for recorded in reversed(self.steps):
            if recorded["step"] == step and field in recorded:
                recorded[field] = "[withheld: personal details]"
                return

    def save(self) -> dict:
        return ledger.append("audit", self.subject, {"steps": self.steps}, self.id)
