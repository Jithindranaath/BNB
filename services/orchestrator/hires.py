"""In-process hire manager (T-061).

A hire runs `harness.run_hire` in a worker thread; phase callbacks are pushed to
an asyncio.Queue per hire so `GET /hires/{id}/stream` can emit SSE. This replaces
a separate arq worker — one fewer process on a memory-tight box (deviation from
architecture.md §2, noted).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents.manifest import Manifest

from . import harness, queries
from .agents_factory import build_agent


@dataclass
class Hire:
    id: str
    agent_id: str
    tier: int
    inputs: dict[str, Any]
    status: str = "queued"           # queued|running|ok|failed|halted|cancelled
    phase: str | None = None
    error: str | None = None
    run_id: str | None = None
    receipt_id: str | None = None
    outcome: Any = None
    cancelled: bool = False
    _events: asyncio.Queue = field(default_factory=asyncio.Queue)

    def snapshot(self) -> dict[str, Any]:
        d = {"hire_id": self.id, "agent_id": self.agent_id, "tier": self.tier,
             "status": self.status, "phase": self.phase, "error": self.error}
        if self.outcome is not None:
            o = self.outcome
            d["delta"] = o.delta
            d["favorable"] = o.favorable
            d["result"] = {
                "metric": o.agent_run.result.metric, "unit": o.agent_run.result.unit,
                "value": o.agent_value, "baseline_value": o.baseline_value,
                "outputs": o.agent_run.result.outputs,
            }
        if self.receipt_id:
            r = queries.receipt_by_id(self.receipt_id)
            d["receipt"] = r.model_dump(mode="json") if r else None
        return d


_HIRES: dict[str, Hire] = {}
# asyncio.create_task() only holds a *weak* ref to the task; if nothing else
# references it, the event loop can garbage-collect it mid-run. Keep a strong
# ref here and drop it on completion (see the "important" note in the asyncio
# docs for create_task).
_BACKGROUND_TASKS: set[asyncio.Task] = set()


def get(hire_id: str) -> Hire | None:
    return _HIRES.get(hire_id)


def validate(manifest: Manifest, inputs: dict) -> dict[str, str]:
    return manifest.validate_inputs(inputs)


async def start(agent_id: str, tier: int, inputs: dict, manifest: Manifest) -> Hire:
    hire = Hire(id=str(uuid.uuid4()), agent_id=agent_id, tier=tier, inputs=inputs)
    _HIRES[hire.id] = hire
    task = asyncio.create_task(_run(hire))
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return hire


def cancel(hire_id: str) -> bool:
    h = _HIRES.get(hire_id)
    if not h or h.status not in ("queued", "running"):
        return False
    h.cancelled = True
    return True


async def _run(hire: Hire) -> None:
    loop = asyncio.get_running_loop()

    def on_phase(phase: str, message: str) -> None:
        hire.phase = phase
        loop.call_soon_threadsafe(
            hire._events.put_nowait, {"phase": phase, "message": message}
        )

    hire.status = "running"
    on_phase("start", f"hiring {hire.agent_id} (tier {hire.tier})")
    try:
        agent = build_agent(hire.agent_id)

        def _blocking():
            if hire.cancelled:
                raise RuntimeError("cancelled before start")
            return harness.run_hire(agent, hire.tier, hire.inputs,
                                    persist=True, on_phase=on_phase)

        outcome = await loop.run_in_executor(None, _blocking)
        hire.outcome = outcome
        hire.run_id = str(outcome.agent_run.run_id) if outcome.agent_run.run_id else None
        hire.receipt_id = str(outcome.receipt_id) if outcome.receipt_id else None
        hire.status = "cancelled" if hire.cancelled else "ok"
        on_phase("done", f"delta {outcome.delta:+.4f} ({'favorable' if outcome.favorable else 'unfavorable'})")
    except Exception as e:  # noqa: BLE001
        hire.status = "failed"
        hire.error = str(e)[:400]
        on_phase("error", hire.error)
    finally:
        loop.call_soon_threadsafe(hire._events.put_nowait, None)  # stream sentinel


async def stream(hire: Hire):
    """Yield SSE-shaped dicts until the hire finishes."""
    yield {"phase": hire.phase or "queued", "message": "connected", "status": hire.status}
    while True:
        try:
            evt = await asyncio.wait_for(hire._events.get(), timeout=30)
        except TimeoutError:
            yield {"phase": hire.phase, "message": "keepalive", "status": hire.status}
            if hire.status not in ("queued", "running"):
                break
            continue
        if evt is None:
            break
        yield {**evt, "status": hire.status}
    yield {"phase": "closed", "status": hire.status,
           "delta": getattr(hire.outcome, "delta", None)}


@contextlib.contextmanager
def _noop():
    yield
