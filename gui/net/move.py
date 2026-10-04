"""Movement from the browser: the offer's Move row and its cell prompt (D-M5-4, slice M5c).

Choosing **Move** on the action offer posts a `kind:"cell"`, `expects:"cell"` prompt owned
by the token's controller, with the offer as its parent. It carries:

  · `cells`, the reachable set for the current mode. The bus refuses any other cell with
    `bad_option` and leaves the prompt live; `net/view.py` sends the same set to the
    owner (and the DM) as `you.reachable`, so the overlay and the check are one set. It is
    not fog-filtered: a player must never have to tap into fog to find out where they can
    go (D-M5-4.2, user's decision), and the leak of a wall's outline is accepted.
  · one option per OTHER mode with budget left. Choosing one re-posts the prompt for that
    mode. The mode lives in the prompt, never in `App.move_type`: the DM's own panel
    selection is not the player's to flip (D-M5-4.4).

A cell answer runs `App.commit_move`, the function the DM's drag release runs, so
opportunity attacks park and resume exactly as they do for the DM. One prompt is one leg:
once it resolves, the bus is empty, and `offer.ensure` posts a fresh offer on the next
frame, with Move still on it while budget remains. A cancel does the same and spends
nothing, since arming a Move only computes a set.
"""

from __future__ import annotations

import rpg_battle_map as rpg

from prompts import Option

MOVE_ID = "move"
MOVE_KIND = "cell"
MOVE_RENDER = "remote"

# (option id, engine mode, the word the title uses)
MODES = (("walk",   rpg.MovementType.Walk,   "walking"),
         ("fly",    rpg.MovementType.Fly,    "flying"),
         ("swim",   rpg.MovementType.Swim,   "swimming"),
         ("burrow", rpg.MovementType.Burrow, "burrowing"))

REASON_SPEED_ZERO = "Speed is 0"
REASON_NO_BUDGET = "No movement left this turn"


def _budgets(app, actor: int) -> list[tuple[str, object, str, int]]:
    return [(mid, mt, word, app.move_budget(actor, mt)) for mid, mt, word in MODES]


def option(app, actor: int, owner: str) -> Option:
    """The offer's Move row. Not an `ActionMenu` id, so it does not go through `perform`;
    its callback opens the Move prompt under the offer that is being answered."""
    if not app.combat.can_agent_move(app.bm, actor):
        return Option(MOVE_ID, "Move", enabled=False, disabled_reason=REASON_SPEED_ZERO)
    if all(ft <= 0 for *_, ft in _budgets(app, actor)):
        return Option(MOVE_ID, "Move", enabled=False, disabled_reason=REASON_NO_BUDGET)
    return Option(MOVE_ID, "Move",
                  on_choose=lambda: ask(app, actor, owner, app.prompts.answering))


def ask(app, actor: int, owner: str, parent, mode=None):
    """Post the Move prompt for `mode`; by default the DM's current `move_type`, or the
    first mode with budget left when that one has none. Nothing here writes `move_type`."""
    budgets = _budgets(app, actor)
    want = app.move_type if mode is None else mode
    current = (next((b for b in budgets if b[1] == want and b[3] > 0), None)
               or next((b for b in budgets if b[3] > 0), None))
    if current is None:
        return None
    _, mt, word, ft = current
    cells = [(c.col, c.row) for c in app.reachable_for(actor, mt)]
    options = [Option(mid, mid.capitalize(),
                      on_choose=lambda m=m: ask(app, actor, owner, parent, m))
               for mid, m, _, left in budgets if left > 0 and m != mt]

    def _answer(response):
        col, row = response.cell
        app.commit_move(actor, rpg.Cell(col, row), mt, owner)

    prompt = app.prompts.ask(actor, owner, MOVE_KIND,
                             f"Move: {word}, {ft} ft left", options,
                             expects="cell", parent=parent, render=MOVE_RENDER,
                             cells=cells, on_answer=_answer)
    app._move_prompt = prompt
    return prompt


def is_move_prompt(app, prompt) -> bool:
    return prompt is not None and prompt is getattr(app, "_move_prompt", None)
