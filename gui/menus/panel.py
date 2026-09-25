"""The combat panel's rendering of the ActionMenu — S3 of M2.

`App._draw_combat_panel` builds `app._action_menu` once per frame and these helpers
turn it into pixels. Layout lives here and legality lives in `actions.py`; the split is
the whole point of the phase, so resist putting a rule back in here.

The click side stays on `App`: `App._action_clicked` is the gate every panel click
goes through, the way `_ask_actor` is for prompts, and it reaches the widget through
`cbt_btn` here. `App._BTN_H` stays on `App` too, because the pre-combat layout shares it.
"""


def cbt_btn(app, action_id: str):
    """The widget backing an action id. Ids match the `btn_cbt_` suffix by design.

    One id, one widget, with no exceptions since F10 was fixed — the alias table
    that pointed `telekinetic_feat` and `telekinetic_psi` at the same button is
    gone, and with it the pass that painted that button twice.
    """
    return getattr(app, "btn_cbt_" + action_id)


def menu_group(app, group: str, only=None, skip=()):
    """This frame's actions in `group`, in build order. `only`/`skip` split one
    group across several rows without teaching `actions.py` about rows."""
    return [a for a in app._action_menu.values()
            if a.group == group and a.id not in skip
            and (only is None or a.id in only)]


def draw_action_row(app, actions, lx, y, w, gap, trail=None, font=None):
    """Lay `actions` out as one equal-width row and draw them; return the new `y`.

    An empty row consumes no vertical space at all — that is how "the option is
    not on offer" reaches the layout now, in place of a positioning branch.

    `font` draws the row in something other than the panel default and restores
    `font_md` afterwards, which is what the narrow rows (§1's two, §4's five-up)
    have always done by hand.
    """
    if not actions:
        return y
    n = len(actions)
    tw = (w - (n - 1) * gap) // n
    row_font = font if font is not None else app.font_md
    widths = row_widths(app, [a.label for a in actions], tw, w, gap, row_font)
    x = lx
    for j, act in enumerate(actions):
        btn = cbt_btn(app, act.id)
        btn.text = act.label
        btn.rect.x = x
        btn.rect.y = y
        btn.rect.w = widths[j]
        x += widths[j] + gap
        if font is not None:
            btn.font = font
        btn.draw(app.screen)
        if font is not None:
            btn.font = app.font_md
    return y + app._BTN_H + (gap if trail is None else trail)


# A label needs this much more than its own glyphs before it stops looking clipped:
# two pixels of air on each side of the text `Button.draw` centres in the rect.
_ROW_LABEL_PAD = 4


def row_widths(app, labels, tw, w, gap, font):
    """Column widths for one `draw_action_row`: equal, unless equal would clip.

    F12: `Button.draw` centres its text and never clips, so a label wider than its
    column bleeds across the gap into its neighbour — which the structural golden
    cannot see, because every rect is exactly what the layout intended. The five-up
    posture row is where it bit: at `font_sm`, Disengage needs 76px, Go Prone 65 and
    Stand Up 64 in a 60px column.

    So the row sizes itself to its labels when it has to and can: each column takes
    the width its own text needs, and the slack left over is handed out evenly so the
    row still spans `w` exactly and its right edge still lines up with every other
    row. A row whose labels do NOT fit even at their natural widths keeps the equal
    split — a squashed-but-even row beats an arbitrary truncation, and the smoke
    test's overflow sweep is what reports it.

    Rows that already fit are untouched, which is why this moved only the posture
    row's rects in the golden.
    """
    need = [font.size(t)[0] + _ROW_LABEL_PAD for t in labels]
    span = w - (len(labels) - 1) * gap
    if max(need) <= tw or sum(need) > span:
        return [tw] * len(labels)
    widths = [x + (span - sum(need)) // len(need) for x in need]
    for j in range(span - sum(widths)):     # the division's remainder, leftmost first
        widths[j] += 1
    return widths


def draw_action_stack(app, actions, lx, y, w, gap):
    """Draw each action as its own full-width row; return the new `y`.

    §7 is a COLUMN of one-button rows, not a grid, so a run of converted buttons is
    n rows — not the n-up `draw_action_row` builds. The two shapes are one call
    apart and the mistake is silent: it turns a Monk's whole band into a three-up
    that still passes every availability test. An empty run consumes no space, same
    as an empty row.
    """
    for act in actions:
        y = draw_action_row(app, [act], lx, y, w, gap)
    return y
