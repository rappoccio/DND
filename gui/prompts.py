"""The prompt bus: every choice the game asks for, as a first-class object.

Seam **S2** of ``plans/MULTIPLAYER_PLAN.md`` (phase M1). Today a choice is a
``(label, callback)`` list handed to one of eight widgets, resolved by a mouse click
inside the pygame event loop, and visible to nothing else. After M1 a choice is a
``Prompt``: it has an id, an owner, a liveness state and a wire projection, and the
widget that draws it is *a* renderer rather than *the* mechanism.

Three consequences, in the order they pay off:

  · the DM console becomes scriptable — ``tests/test_prompts.py`` drives a real combat
    by answering prompts with no pygame events at all, which is the first GUI flow this
    codebase can test;
  · ``authorize()`` finally has the prompt state it was written against — M0 left
    ``SessionRoster.prompt_lookup`` as a hook and denied every player until something
    filled it (D-M0-3). ``PromptBus`` is that something;
  · a second renderer — a browser, in M5 — answers the *same* prompt through the *same*
    callbacks, so remote play is a renderer and not a parallel implementation of the
    rules (Step 0.7's F4).

**What this module deliberately does not do.** It does not import pygame, it does not
know what a ``ContextMenu`` is beyond the four methods ``ContextMenuRenderer`` calls on
the object it is handed, and it never defers a callback to a later frame. M1's rule is
that the local renderer stays synchronous — the callback runs in the same frame as the
click, exactly as ``ContextMenu.handle`` runs it today — and *any* deferred answering
waits for M5. Everything here is therefore single-threaded and belongs to the pygame
thread (NN1).

Wire shapes are frozen in Step 0.5 (``prompt`` / ``submit`` / ``submit_ack``);
``Prompt.to_wire()`` and ``SubmitResult.to_wire()`` produce them, and nothing else here
may invent a field.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from net.roster import Action, DM_PRINCIPAL_ID, PromptTarget

# Step 0.5's `kind` and `expects` vocabularies, closed sets both. Kept as plain strings
# rather than enums because they cross the wire as strings and every consumer — the
# renderers here, the JS client in M4 — compares them as strings.
KINDS = ("reaction", "action", "target", "cell", "confirm")
EXPECTS = ("choice", "cell", "agent", "none")

# The closed `submit` error set, amended 2026-09-21 to add "timeout" (Step 0.7 F1).
# "timeout" is never raised here: it belongs to the net thread, which is the only party
# that can observe "the game thread never came back."
ERR_NOT_LIVE   = "not_live"      # answered already, superseded, or the DM took over
ERR_DENIED     = "denied"        # authorize() said no
ERR_BAD_OPTION = "bad_option"    # unknown option id, or one that is disabled
ERR_PROTOCOL   = "protocol"      # unknown prompt id, or a response of the wrong shape
ERR_TIMEOUT    = "timeout"       # reserved for the M5 transport; never produced here

# How many resolved prompts to keep addressable. A late submit for one of them gets
# "not_live" (true, and useful); a submit for one that has fallen out gets "protocol"
# (also true, and the client's recovery — re-read /state — is the same either way).
HISTORY_LIMIT = 64


class PromptState(enum.Enum):
    LIVE       = "live"
    ANSWERED   = "answered"
    CANCELLED  = "cancelled"     # dismissed without a choice; on_cancel ran
    SUPERSEDED = "superseded"    # a later prompt took the renderer; NO callback ran


@dataclass(frozen=True)
class Option:
    """One row of a prompt.

    ``on_choose`` is the callback the local click fires today, carried on the option
    because that is the shape all 87 call sites already have. It is **not** on the wire
    (F4: the ``Prompt`` the bus holds and the object on the wire are two types) — a
    remote answer re-enters through ``PromptBus.submit`` and the bus calls this same
    callable on the game thread.

    ``disabled_reason`` is a *rules* string ("Reaction already used"), never an
    authorization one: Step 0.5 is explicit that a prompt a viewer may not answer is not
    sent to them at all, greyed out or otherwise.
    """
    id:              str
    label:           str
    enabled:         bool = True
    disabled_reason: str | None = None
    on_choose:       Callable[[], None] | None = None

    def to_wire(self) -> dict:
        d: dict = {"id": self.id, "label": self.label, "enabled": self.enabled}
        if self.disabled_reason:
            d["disabled_reason"] = self.disabled_reason
        return d


@dataclass(frozen=True)
class Response:
    """A submission's payload — the `submit` envelope minus its routing fields."""
    option: str | None = None                  # expects "choice"
    cell:   tuple[int, int] | None = None      # expects "cell"
    agent:  int | None = None                  # expects "agent"

    @classmethod
    def from_wire(cls, msg: dict) -> "Response":
        cell = msg.get("cell")
        return cls(option=msg.get("option"),
                   cell=(int(cell[0]), int(cell[1])) if cell else None,
                   agent=None if msg.get("agent") is None else int(msg["agent"]))


@dataclass
class Prompt:
    """One pending decision. Mutable only in ``state`` and ``response``."""
    id:        str
    actor_idx: int                      # whose turn or reaction this is
    owner:     str                      # principal id; who may answer (never a name)
    kind:      str
    title:     str
    options:   tuple[Option, ...]
    expects:   str = "choice"
    deadline:  float | None = None      # monotonic deadline; unused until M5's expiry
    parent_id: str | None = None        # the stack, per Step 0.5
    anchor:    tuple[int, int] | None = None   # local render hint; not on the wire
    on_answer: Callable[[Response], None] | None = None
    on_cancel: Callable[[], None] | None = None
    state:     PromptState = PromptState.LIVE
    response:  Response | None = None

    @property
    def is_live(self) -> bool:
        return self.state is PromptState.LIVE

    def option(self, option_id: str | None) -> Option | None:
        return next((o for o in self.options if o.id == option_id), None)

    def to_wire(self, seq: int = 0) -> dict:
        """The Step 0.5 `prompt` envelope. Callables are stripped here and nowhere else —
        this projection is the whole reason ``Prompt`` and its wire form are two types."""
        return {"v": 1, "t": "prompt",
                "id": self.id,
                "parent_id": self.parent_id,
                "seq": seq,
                "actor": self.actor_idx,
                "kind": self.kind,
                "title": self.title,
                "expects": self.expects,
                "options": [o.to_wire() for o in self.options],
                "deadline_ms": None if self.deadline is None else int(self.deadline * 1000)}


@dataclass(frozen=True)
class SubmitResult:
    ok:        bool
    prompt_id: str
    error:     str | None = None

    def __bool__(self) -> bool:
        return self.ok

    def to_wire(self) -> dict:
        d = {"v": 1, "t": "submit_ack", "id": self.prompt_id, "ok": self.ok}
        if not self.ok:
            d["error"] = self.error
        return d


class ContextMenuRenderer:
    """Draws a ``Prompt`` as the popup the DM already knows.

    Duck-typed on purpose: it calls ``show`` / ``dismiss`` / ``visible`` on whatever it
    is handed, so this module stays importable without pygame and the headless tests can
    pass a recorder in place of the widget. Appearance is unchanged — the items list it
    builds is the same list the call site used to build itself.
    """

    def __init__(self, menu, screen_size: Callable[[], tuple[int, int]] | None = None):
        self._menu = menu
        self._screen_size = screen_size

    def show(self, prompt: Prompt, submit: Callable[[str], None]) -> None:
        items = [(o.label, (lambda oid=o.id: submit(oid))) for o in prompt.options]
        if not items:                     # ContextMenu.show indexes max() over items
            return
        self._menu.show(prompt.anchor or (100, 100), items, self._size())

    def dismiss(self) -> None:
        self._menu.dismiss()

    def is_showing(self) -> bool:
        return bool(getattr(self._menu, "visible", False))

    def _size(self) -> tuple[int, int]:
        # The App's screen does not exist yet when the bus is constructed, so the size is
        # a callable resolved at show time. A failure here must not eat a prompt.
        if self._screen_size is None:
            return (9999, 9999)
        try:
            return self._screen_size()
        except Exception:
            return (9999, 9999)


class PromptBus:
    """Holds the live prompt (and its ancestors), validates every answer, and owns the
    single resumption point each call site used to own itself.

    Ordering rule, and the one that keeps NN4 honest: a prompt is marked answered
    **before** its callback runs. The callback routinely opens the next prompt — a
    reaction chain does exactly that — and a second submission arriving mid-callback must
    see ``not_live``, not race the first one into the engine.
    """

    def __init__(self, roster=None, renderer=None):
        self._roster = None
        self._renderer = renderer
        self._prompts: dict[str, Prompt] = {}
        self._order: list[str] = []          # insertion order, for the history trim
        self._stack: list[Prompt] = []       # ancestors first, the displayed leaf last
        self._counter = 0
        self._observers: list[Callable[[str, Prompt], None]] = []
        if roster is not None:
            self.bind_roster(roster)

    # ── Wiring ──────────────────────────────────────────────────────────────

    def bind_roster(self, roster) -> None:
        """Adopt a roster and fill its prompt hook. ``_set_encounter_base`` builds a new
        roster per encounter, so this runs again on every load — M0's D-M0-3 left the
        hook empty precisely so the bus could be the thing that fills it."""
        self._roster = roster
        if roster is not None:
            roster.prompt_lookup = self.lookup

    def set_renderer(self, renderer) -> None:
        self._renderer = renderer

    def add_observer(self, fn: Callable[[str, Prompt], None]) -> None:
        """Called with ("asked" | "answered" | "cancelled" | "superseded", prompt) on the
        game thread. M4/M5 publish from here; nothing may block or touch the engine."""
        self._observers.append(fn)

    # ── State ───────────────────────────────────────────────────────────────

    @property
    def live(self) -> Prompt | None:
        """The prompt currently displayed — the leaf of the stack."""
        return self._stack[-1] if self._stack else None

    def get(self, prompt_id: str) -> Prompt | None:
        return self._prompts.get(prompt_id)

    def lookup(self, prompt_id: str) -> tuple[str | None, bool]:
        """``SessionRoster.prompt_lookup``: (owner principal id, is_live). The roster
        must not reach into this module's state, so it asks through this hook and keeps
        Step 0.4's frozen ``authorize()`` signature."""
        p = self._prompts.get(prompt_id)
        return (None, False) if p is None else (p.owner, p.is_live)

    # ── Asking ──────────────────────────────────────────────────────────────

    def ask(self, actor_idx: int, owner: str, kind: str, title: str,
            options: Sequence[Option] | Iterable[Option] = (),
            expects: str = "choice", deadline: float | None = None,
            parent: Prompt | None = None,
            anchor: tuple[int, int] | None = None,
            on_answer: Callable[[Response], None] | None = None,
            on_cancel: Callable[[], None] | None = None) -> Prompt:
        """Open a prompt and render it. Returns the ``Prompt`` so a caller that opens a
        submenu can pass it back as ``parent``.

        ``parent`` is explicit rather than inferred from "a prompt opened during another
        prompt's callback": a reaction chain opens the *next* reactor's window from
        inside the previous one's callback, and those are siblings, not a stack. Only a
        call site that means "this is a submenu of that" says so.
        """
        self._counter += 1
        prompt = Prompt(id=f"pr_{self._counter:05d}",
                        actor_idx=actor_idx, owner=owner, kind=kind, title=title,
                        options=tuple(options), expects=expects, deadline=deadline,
                        parent_id=parent.id if parent is not None else None,
                        anchor=anchor, on_answer=on_answer, on_cancel=on_cancel)

        if parent is None:
            # No parent means this prompt replaces whatever was on screen. That is what
            # a single-instance ContextMenu already does when a call site re-show()s over
            # a live menu (Step 0.2): the old one is destroyed without resolving. It is
            # marked superseded and its callbacks do NOT run — inventing a cancel here
            # would fire a Skip nobody asked for.
            for old in self._stack:
                if old.is_live:
                    old.state = PromptState.SUPERSEDED
                    self._publish("superseded", old)
            self._stack = []
        else:
            # Walk back to the parent: re-asking from an ancestor drops the branch below
            # it. The parent stays LIVE — Step 0.5 has cancelling a child re-send its
            # parent, and a dead parent could not be re-sent.
            while self._stack and self._stack[-1] is not parent:
                self._stack.pop()
            if not self._stack:
                self._stack = [parent]

        self._remember(prompt)
        self._stack.append(prompt)
        self._publish("asked", prompt)
        self._render(prompt)
        return prompt

    # ── Answering ───────────────────────────────────────────────────────────

    def submit(self, prompt_id: str, response: Response | None = None,
               principal_id: str = DM_PRINCIPAL_ID) -> SubmitResult:
        """Validate and resolve. The four checks are Step 0.5's, in its order: the id,
        the right to answer, the option, then liveness — liveness first among equals,
        because NN4's "first valid submission wins" is decided by nothing else."""
        prompt = self._prompts.get(prompt_id)
        if prompt is None:
            return SubmitResult(False, prompt_id, ERR_PROTOCOL)
        if not prompt.is_live:
            return SubmitResult(False, prompt_id, ERR_NOT_LIVE)
        if not self._authorized(principal_id, prompt):
            return SubmitResult(False, prompt_id, ERR_DENIED)

        response = response or Response()
        option: Option | None = None
        if prompt.expects == "choice":
            option = prompt.option(response.option)
            if option is None or not option.enabled:
                return SubmitResult(False, prompt_id, ERR_BAD_OPTION)
        elif prompt.expects == "cell":
            if not (isinstance(response.cell, tuple) and len(response.cell) == 2):
                return SubmitResult(False, prompt_id, ERR_PROTOCOL)
        elif prompt.expects == "agent":
            if not isinstance(response.agent, int):
                return SubmitResult(False, prompt_id, ERR_PROTOCOL)

        # Commit before dispatching (see the class docstring).
        prompt.state = PromptState.ANSWERED
        prompt.response = response
        # Answering resolves the whole stack: on the DM console the submenu destroyed its
        # parent when it opened, so picking an item there ends the interaction rather
        # than returning to a menu that is no longer on screen. Ancestors are superseded,
        # not cancelled — nobody declined them.
        ancestors = [p for p in self._clear_stack() if p is not prompt and p.is_live]
        self._publish("answered", prompt)
        for a in ancestors:
            a.state = PromptState.SUPERSEDED
            self._publish("superseded", a)

        # The option's own callback is what the 87 mechanical conversions carry; the
        # prompt-level on_answer is for the responses that are not a choice at all.
        if option is not None and option.on_choose is not None:
            option.on_choose()
        elif prompt.on_answer is not None:
            prompt.on_answer(response)
        return SubmitResult(True, prompt_id)

    def choose(self, option_id: str, principal_id: str = DM_PRINCIPAL_ID) -> SubmitResult:
        """Answer the displayed prompt by option id — what a local click means, and what
        a scripted test says."""
        prompt = self.live
        if prompt is None:
            return SubmitResult(False, "", ERR_NOT_LIVE)
        return self.submit(prompt.id, Response(option=option_id), principal_id)

    def choose_label(self, label: str, principal_id: str = DM_PRINCIPAL_ID) -> SubmitResult:
        """Answer by visible label. For tests and for the DM console's keyboard paths:
        an option id is positional and says nothing about what was picked."""
        prompt = self.live
        if prompt is None:
            return SubmitResult(False, "", ERR_NOT_LIVE)
        opt = next((o for o in prompt.options if o.label == label), None)
        if opt is None:
            return SubmitResult(False, prompt.id, ERR_BAD_OPTION)
        return self.submit(prompt.id, Response(option=opt.id), principal_id)

    def cancel(self, prompt_id: str | None = None) -> bool:
        """Dismiss without choosing, and run ``on_cancel``.

        Cancelling a child cancels its ancestors too, because that is what dismissing a
        submenu does on the DM console today: the popup is one widget and clicking away
        closes the lot. Step 0.5's "cancelling a child re-sends its parent" is the single
        deliberate local/remote difference in the protocol, and it arrives with the
        remote renderer in M5 — implementing it here would change DM behavior inside a
        phase whose acceptance criterion is that nothing changes.
        """
        prompt = self.live if prompt_id is None else self._prompts.get(prompt_id)
        if prompt is None or not prompt.is_live:
            return False
        doomed = [p for p in self._clear_stack() if p.is_live]
        if prompt not in doomed:
            doomed.append(prompt)
        for p in doomed:
            p.state = PromptState.CANCELLED
            self._publish("cancelled", p)
        # Leaf first: the leaf's on_cancel is the one that resumes the engine, and it may
        # legitimately open the next prompt (a declined reaction submits its Skip, which
        # can park the engine on the next reactor).
        for p in reversed(doomed):
            if p.on_cancel is not None:
                p.on_cancel()
        return True

    def renderer_dismissed(self) -> bool:
        """The event loop's report that the widget closed itself. Called after the local
        renderer has handled a click; if a prompt is still live and nothing is on screen,
        the click was a dismissal and the prompt is cancelled."""
        prompt = self.live
        if prompt is None or not prompt.is_live:
            return False
        if self._renderer is not None and self._renderer.is_showing():
            return False
        return self.cancel(prompt.id)

    # ── Internals ───────────────────────────────────────────────────────────

    def _authorized(self, principal_id: str, prompt: Prompt) -> bool:
        """NN6: the one chokepoint, consulted even when the only caller is the DM's own
        mouse. With no roster bound (a bus under unit test) the local console is trusted,
        which is the M0 state of the world and not a policy decision made here."""
        if self._roster is None:
            return True
        principal = self._roster.get(principal_id)
        return self._roster.authorize(principal, Action.ANSWER_PROMPT,
                                      PromptTarget(prompt.id))

    def _render(self, prompt: Prompt) -> None:
        if self._renderer is None:
            return
        self._renderer.show(prompt, lambda oid: self.choose(oid))

    def _clear_stack(self) -> list[Prompt]:
        """Empty the stack and clear the widget. Returns what was on it, so the caller
        can decide what each one's fate is — answered, cancelled or superseded.

        The widget has usually dismissed itself already (``ContextMenu.handle`` dismisses
        before it calls back), so this is idempotent by necessity, not by accident."""
        was, self._stack = self._stack, []
        if self._renderer is not None and self._renderer.is_showing():
            self._renderer.dismiss()
        return was

    def _remember(self, prompt: Prompt) -> None:
        self._prompts[prompt.id] = prompt
        self._order.append(prompt.id)
        while len(self._order) > HISTORY_LIMIT:
            self._prompts.pop(self._order.pop(0), None)

    def _publish(self, event: str, prompt: Prompt) -> None:
        for fn in self._observers:
            try:
                fn(event, prompt)
            except Exception as e:               # an observer must never wedge the table
                print(f"[prompts] observer failed on {event}: {e}")


def options_from_pairs(pairs: Iterable[tuple[str, Callable[[], None]]]) -> list[Option]:
    """``[(label, callback), …]`` → ``[Option, …]``, the mechanical half of the 87-site
    conversion. Ids are positional (``opt_0``, ``opt_1``, …) exactly as Step 0.5's
    examples show: nothing on the wire may depend on a label, which is display text and
    changes with the rules."""
    return [Option(id=f"opt_{i}", label=label, on_choose=cb)
            for i, (label, cb) in enumerate(pairs)]
