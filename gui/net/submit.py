"""The submit path's frame-tick half, and the submit log (MULTIPLAYER_PLAN.md M5a).

A `submit` frame arrives on `WS /live`, on the net thread. Deciding it means reading
liveness, and liveness is game state, so Step 0.7's F1 applies: the net thread queues it and
the frame tick decides. This module is the deciding. It runs on the pygame thread only, and
`net.link` hands `handle_submit` to the server the way it hands `build_view`.

**Submits get a queue of their own, `App._net_submits`, drained once per frame by `run()`
and never by `_pump_net()`.** A submit runs a prompt's callback, which is whatever the DM's
click would have run: an opportunity attack, a Shield, the next reactor's window. D-M4d-4
forbids a *command* from opening a modal, and a click is allowed to open one, so a submit is
not a command. It is input, and it is decided where input is decided: at the top of the frame
loop, never from inside a modal the DM is holding open. While the DM holds one open, a
submit waits. If it waits past `STATE_TIMEOUT_S`, the server answers `timeout`, which Step
0.5 already defines as "outcome unknown, re-read, never resubmit".

**The log (D-M5-6a) records every remote submit, including the refused ones, plus every
time the DM takes a player's prompt from them.** It keeps principal ids and never display
names (A2/A4). It is append-only JSON lines, one object per line, written beside
`replay_log.txt`, so a live bug report can carry the intents that led to it.
"""

from __future__ import annotations

import json
import os
import time

from net.roster import DM_PRINCIPAL_ID
from prompts import CLOCK_PRINCIPAL_ID, ERR_PROTOCOL, Response, SubmitResult

SUBMIT_LOG_PATH = "submit_log.jsonl"

# The answer fields a submit may carry. Envelope 4 as amended 2026-09-28: exactly one of these.
_ANSWER_FIELDS = ("option", "cell", "agent", "cancel")


def parse_submit(frame) -> tuple[str, Response | None, bool] | None:
    """`(prompt_id, response, is_cancel)`, or None for a frame of the wrong shape.

    This only checks shape. Whether the option exists, is enabled or is the right kind for
    the prompt is the bus's question (`bad_option` / `protocol`), and it is asked once,
    there. What is refused here is a frame that no prompt could accept: no id, two answers,
    a cell that is not two integers, a `cancel` that is anything but `true`. Nothing a client
    wrote is kept as a free string. The option id is compared with the prompt's own ids and
    goes no further.
    """
    if not isinstance(frame, dict):
        return None
    prompt_id = frame.get("id")
    if not isinstance(prompt_id, str) or not prompt_id:
        return None
    present = [f for f in _ANSWER_FIELDS if frame.get(f) is not None]
    if len(present) != 1:
        return None
    field = present[0]
    value = frame[field]
    if field == "cancel":
        return (prompt_id, None, True) if value is True else None
    if field == "option":
        return (prompt_id, Response(option=value), False) if isinstance(value, str) else None
    if field == "agent":
        ok = isinstance(value, int) and not isinstance(value, bool)
        return (prompt_id, Response(agent=value), False) if ok else None
    # cell
    if (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, int) and not isinstance(v, bool) for v in value)):
        return prompt_id, Response(cell=(value[0], value[1])), False
    return None


def handle_submit(app, principal, frame) -> dict:
    """Decide one submit on the frame tick, and return its `submit_ack`.

    Returns the wire dict rather than the `SubmitResult`, because `CommandQueue`'s rule 3
    applies: what crosses back to the net thread is freshly built plain data.
    """
    parsed = parse_submit(frame)
    raw_id = frame.get("id") if isinstance(frame, dict) else None
    if parsed is None:
        result = SubmitResult(False, raw_id if isinstance(raw_id, str) else "", ERR_PROTOCOL)
        app.submit_log.write(principal.id, result, None, None)
        return result.to_wire()

    prompt_id, response, is_cancel = parsed
    prompt = app.prompts.get(prompt_id)
    # The DM's own browser is remote too. Its answer is logged here as a submit, and the
    # observer below must not log it a second time as a takeover.
    app.submit_log.remote = True
    try:
        if is_cancel:
            result = app.prompts.cancel_as(prompt_id, principal.id)
        else:
            result = app.prompts.submit(prompt_id, response, principal.id)
    finally:
        app.submit_log.remote = False
    app.submit_log.write(principal.id, result, prompt,
                         {"cancel": True} if is_cancel else _answer(response))
    return result.to_wire()


def _answer(response: Response) -> dict:
    if response.option is not None:
        return {"option": response.option}
    if response.cell is not None:
        return {"cell": list(response.cell)}
    return {"agent": response.agent}


class SubmitLog:
    """The append-only intent log (D-M5-6a).

    One JSON object per line. `seq` is the view cursor, which stays 0 until `EventStream`
    (S3) exists; it is logged anyway so the lines already have the field when a cursor
    arrives. `t` is `time.monotonic()`, which makes lines comparable with each other but not
    with wall clocks. That is enough to order a session, and it leaks nothing about when
    the table plays.

    The file is opened per write rather than held open. A write happens a few times a
    minute at most, and a held handle is one more thing to close on every exit path.
    Opening per write also means a DM who deletes the file between sessions gets a fresh
    one, not writes to an unlinked inode. A write that fails is printed once per failure
    and dropped, because the log must never cost the table a frame.

    It is also a bus observer: `observe` logs **the DM taking over**, meaning a prompt owned
    by someone else that was answered or dismissed by the DM principal (D-M5-7). The
    player's own answers never reach it: they come through `handle_submit`, which logs them
    first, so nothing is logged twice. It logs **an expiry** too, as an `expired` line with
    `CLOCK_PRINCIPAL_ID` as the principal: the deadline skipped the prompt, and neither the
    player nor the DM chose anything.
    """

    def __init__(self, path: str | None = None) -> None:
        # None until a transport exists: `start_player_server` points it at
        # `SUBMIT_LOG_PATH`. A constructed `App` (every headless suite) writes nothing, so
        # a DM-side dismissal in a test cannot leave a log file in the tree.
        self.path = path
        self.lines = 0          # written this session; the suite reads it
        self.remote = False     # True while handle_submit is inside the bus
        # D-M7-4: ``announce(event, prompt)`` repeats a `takeover` or `expired` line to the
        # session log, which the whole table reads. Installed by `App`; None writes nothing.
        self.announce = None

    def write(self, principal_id: str, result: SubmitResult, prompt, answer,
              event: str = "submit") -> None:
        entry = {"t": round(time.monotonic(), 3),
                 "event": event,
                 "seq": 0,
                 "principal": principal_id,
                 "prompt": result.prompt_id or None,
                 "kind": getattr(prompt, "kind", None),
                 "actor": getattr(prompt, "actor_idx", None),
                 "answer": answer,
                 "ok": result.ok}
        if not result.ok:
            entry["error"] = result.error
        self._append(entry)

    def observe(self, event: str, prompt) -> None:
        """`PromptBus` observer: the DM resolved a prompt that belongs to someone else, or
        its deadline did."""
        if event not in ("answered", "cancelled") or self.remote:
            return
        if event == "cancelled" and prompt.resolved_by == CLOCK_PRINCIPAL_ID:
            self.write(CLOCK_PRINCIPAL_ID, SubmitResult(True, prompt.id), prompt,
                       {"cancel": True}, event="expired")
            self._announce("expired", prompt)
            return
        if prompt.owner == DM_PRINCIPAL_ID or prompt.resolved_by != DM_PRINCIPAL_ID:
            return
        if event == "answered":
            answer = _answer(prompt.response) if prompt.response is not None else None
        else:
            answer = {"cancel": True}
        self.write(DM_PRINCIPAL_ID, SubmitResult(True, prompt.id), prompt, answer,
                   event="takeover")
        self._announce("takeover", prompt)

    def _announce(self, event: str, prompt) -> None:
        hook = self.announce
        if hook is None:
            return
        try:
            hook(event, prompt)
        except Exception as exc:          # the table's log must never cost the bus a frame
            print(f"[net] session log line dropped: {exc}")

    def _append(self, entry: dict) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
            self.lines += 1
        except OSError as exc:
            print(f"[net] submit log not written ({os.path.basename(self.path)}): {exc}")

