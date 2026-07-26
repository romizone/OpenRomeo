"""Tool-call/result pairing — the invariant every provider enforces on history.

Regression suite for the owner-hit 2026-07-26 failure: a second turn started while one
was running, both assistant messages landed back to back, and every later turn 400'd with
"tool_call_ids did not have response messages" — permanently, because the bad thread
re-rides each request.
"""

from __future__ import annotations

import json

import pytest

from coworker.engine import _repair_tool_call_pairing
from coworker.permissions import Mode


def _assistant(*ids: str, name: str = "run_shell") -> dict:
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": name, "arguments": "{}"}}
            for i in ids
        ],
    }


def _result(tid: str, body: str = "ok") -> dict:
    return {"role": "tool", "tool_call_id": tid, "name": "run_shell", "content": body}


def _pairs_ok(messages: list[dict]) -> bool:
    """The provider's rule: each assistant tool_calls message is immediately followed by
    one tool message per id, in order."""
    i = 0
    while i < len(messages):
        msg = messages[i]
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            expected = [c["id"] for c in msg["tool_calls"]]
            following = messages[i + 1 : i + 1 + len(expected)]
            if [m.get("tool_call_id") for m in following] != expected:
                return False
            if any(m.get("role") != "tool" for m in following):
                return False
            i += len(expected)
        i += 1
    return True


def test_interleaved_concurrent_turns_are_reordered():
    """The exact shape found in the bricked session: two assistant messages back to back,
    results afterwards in reverse order. The results EXIST — they must be moved, not
    replaced with errors."""
    history = [
        {"role": "user", "content": "go"},
        _assistant("run_shell_12"),
        _assistant("run_shell_13"),
        _result("run_shell_13", "output 13"),
        _result("run_shell_12", "output 12"),
    ]
    out = _repair_tool_call_pairing(history)

    assert _pairs_ok(out)
    assert out[2]["content"] == "output 12"  # real output preserved, in place
    assert out[4]["content"] == "output 13"
    assert len([m for m in out if m.get("role") == "tool"]) == 2  # no duplicates


def test_orphaned_call_gets_a_synthetic_result():
    history = [
        {"role": "user", "content": "go"},
        _assistant("run_shell_1"),
        {"role": "user", "content": "still there?"},
    ]
    out = _repair_tool_call_pairing(history)

    assert _pairs_ok(out)
    filler = out[2]
    assert filler["role"] == "tool" and filler["tool_call_id"] == "run_shell_1"
    assert "no result" in json.loads(filler["content"])["error"]


def test_parallel_calls_in_one_message_all_get_results():
    history = [
        _assistant("a", "b", "c"),
        _result("b", "B"),
    ]
    out = _repair_tool_call_pairing(history)

    assert _pairs_ok(out)
    assert [m["tool_call_id"] for m in out[1:4]] == ["a", "b", "c"]
    assert out[2]["content"] == "B"  # the one real result kept its body


def test_reused_ids_across_turns_each_claim_their_own_result():
    """Kimi K3 numbers ids `name_N` and the counter restarts, so one thread really can
    carry `todo_write_2` twice (seen in the session that exposed this bug). Matching by id
    alone made the first call swallow the second call's result and orphan it."""
    history = [
        _assistant("todo_write_2", name="todo_write"),
        _result("todo_write_2", "first"),
        {"role": "assistant", "content": "thinking"},
        _assistant("todo_write_2", name="todo_write"),
        _result("todo_write_2", "second"),
    ]
    out = _repair_tool_call_pairing(history)

    assert _pairs_ok(out)
    bodies = [m["content"] for m in out if m.get("role") == "tool"]
    assert bodies == ["first", "second"]  # each call kept ITS own output


def test_stray_result_without_a_call_is_dropped():
    """A `tool` message not preceded by a matching tool_calls message is itself a protocol
    error — providers reject it."""
    history = [{"role": "user", "content": "hi"}, _result("ghost", "orphan output")]
    out = _repair_tool_call_pairing(history)
    assert all(m.get("role") != "tool" for m in out)


def test_healthy_history_is_returned_untouched():
    history = [
        {"role": "user", "content": "hi"},
        _assistant("x"),
        _result("x"),
        {"role": "assistant", "content": "done"},
    ]
    assert _repair_tool_call_pairing(history) is history  # same object: no copy, no churn


def test_history_without_tool_calls_is_returned_untouched():
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
    assert _repair_tool_call_pairing(history) is history


def test_repair_is_idempotent():
    history = [_assistant("a"), _assistant("b"), _result("b"), _result("a")]
    once = _repair_tool_call_pairing(history)
    twice = _repair_tool_call_pairing(once)
    assert [m.get("tool_call_id") for m in twice] == [m.get("tool_call_id") for m in once]
    assert _pairs_ok(twice)


@pytest.mark.asyncio
async def test_cancelled_turn_leaves_no_orphan_in_stored_history(tmp_path):
    """A cancelled task (app quit, uvicorn shutdown, a GC'd task) unwinds the turn wherever
    it was parked — typically inside the tool call, after the assistant message landed.
    The generator's finally must still answer every pending call, or run_turn's own
    `finally: save` persists a thread no provider accepts."""
    import asyncio

    from coworker.agents import code_agent
    from coworker.agent import build_engine
    from coworker.providers import AssistantTurn, ModelCapabilities, StreamChunk
    from coworker.providers.base import ToolCall

    started = asyncio.Event()

    def _slow_shell(command: str, timeout: int = 60) -> str:
        started.set()
        import time

        time.sleep(30)  # cancelled long before this returns
        return "never"

    _slow_shell.__name__ = "run_shell"

    class _Provider:
        def capabilities(self, model):
            return ModelCapabilities(tools=True, streaming=False)

        def complete(self, **kwargs):
            return AssistantTurn(
                text=None,
                tool_calls=[ToolCall(id="run_shell_13", name="run_shell", arguments={"command": "sleep 30"})],
            )

        def stream(self, **kwargs):
            yield StreamChunk(turn=self.complete(**kwargs))

    engine = build_engine(
        agent=code_agent(), workspace=tmp_path, provider=_Provider(), mode=Mode.AUTO
    )
    try:
        engine.registry.register(_slow_shell)

        async def drive():
            async for _ in engine.run("go"):
                pass

        task = asyncio.create_task(drive())
        await asyncio.wait_for(started.wait(), timeout=10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert _pairs_ok([m for m in engine.messages if m.get("role") != "notice"])
        answered = [m for m in engine.messages if m.get("role") == "tool"]
        assert [m["tool_call_id"] for m in answered] == ["run_shell_13"]
    finally:
        engine.executor.close()


def test_engine_feed_repairs_a_broken_thread(tmp_path):
    """End to end: a corrupted thread must produce a provider feed that satisfies the
    invariant — this is what unbricks an existing session."""
    from coworker.agents import chat_agent
    from coworker.agent import build_engine
    from coworker.providers import ModelCapabilities

    class _Stub:
        def complete(self, **kwargs):  # pragma: no cover
            raise NotImplementedError

        def capabilities(self, model):
            return ModelCapabilities()

    engine = build_engine(agent=chat_agent(), provider=_Stub())
    engine.messages.extend(
        [
            {"role": "user", "content": "go", "ts": 1.0},
            _assistant("run_shell_12"),
            _assistant("run_shell_13"),
            {"role": "notice", "kind": "error", "content": "400 …"},
            _result("run_shell_13", "out13"),
            _result("run_shell_12", "out12"),
        ]
    )
    feed = engine._outbound_messages()

    assert _pairs_ok(feed)
    assert all(m.get("role") != "notice" for m in feed)
    # The stored history is the record of what happened — repair is outbound-only.
    stored_calls = [
        c["id"] for m in engine.messages for c in (m.get("tool_calls") or [])
    ]
    assert stored_calls == ["run_shell_12", "run_shell_13"]
    assert [m.get("tool_call_id") for m in engine.messages if m.get("role") == "tool"] == [
        "run_shell_13",
        "run_shell_12",
    ]
