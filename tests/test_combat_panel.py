#!/usr/bin/env python3
"""GUI regression oracle for the combat panel (MULTIPLAYER_PLAN.md Step 0.6).

This is the M2-analog of `test_determinism.py`. It stands `App` up headlessly on a
fixed map with a fixed seed, builds one scripted encounter, and dumps a **structural**
capture of `_draw_combat_panel` at a series of checkpoints to a byte-comparable golden
file.

Structural, not pixel: `SysFont("sans", …)` (`main.py:468`) resolves through the
platform font stack and the Dockerfile installs no font package, so a pixel golden
would be valid in exactly one environment. Panel geometry never consults text metrics —
every rect comes from `W`/`HW`/`TW3`/`TW5` arithmetic and a `y` cursor advanced by
constants — so button rects ARE identical across machines even when the glyphs inside
them are not. See "Step 0.6 — the oracle's shape" in the plan.

What is captured, per checkpoint, in draw order:

    text | <section> | <string>                       every string the panel renders
    btn  | <section> | <name> | <label> | <rect> | yes  every widget actually drawn
    btn  | -         | <name> | -       | -      | no   every widget NOT drawn

`Button.draw` is HOOKED — "drawn?" is never inferred from the rect. The stale-rect
guard parks undrawn buttons at x = -10000, but Step 0.3's F4 found the
`btn_cbt_metamagic` dict escapes that guard entirely, so inferring would bake the bug
into the baseline.

The panel's text is captured too, because the section labels ("Action ✓",
"[Bonus used]", "Frightened — must Dash") are how a reader tells WHICH BRANCH of the
five-way Action section ran — the cheapest possible check that an M2 step preserved the
branch structure.

Checkpoints cover the five-way Action branch (normal / action used / incapacitated /
frightened / prone) and at least one member of each Step 0.3 bucket 7a–7e.

Regenerate the golden after an INTENTIONAL panel change (inspect the diff first!):
    python test_combat_panel.py --update
"""

import os
import sys

# Headless SDL: set before pygame is imported anywhere (main.py imports it at module
# scope). `test_feats.py` uses the same pair for its headless `App` import.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import difflib
import pygame

import rpg_battle_map as rpg
from helpers import _dict_to_spell, _dict_to_weapon
from widgets import Button
from main import App

SEED = 20260921
MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
GOLDEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_combat_panel.golden.txt")

PC_TEAM = 2      # constants.PC_FACTION
FOE_TEAM = 1


# ─────────────────────────────────────────────────────────────────────────────
#  Capture
# ─────────────────────────────────────────────────────────────────────────────

# A section starts at the panel heading that introduces it. These are the only
# headings `_draw_combat_panel` draws; everything between two of them belongs to the
# first. Keyed off the rendered string because `txt()` is a closure inside the method
# and cannot be hooked from outside without editing main.py (Step 0.6 adds tests only).
_SECTION_HEADS = (
    ("Header",      lambda s: s.startswith("⚔  Combat")),
    ("Initiative",  lambda s: s == "Initiative Order"),
    ("TurnInfo",    lambda s: s.startswith("Turn: ")),
    ("Action",      lambda s: s in ("Action", "Action ✓")),
    ("BonusAction", lambda s: s in ("Bonus Action", "Bonus Action ✓")),
    ("Movement",    lambda s: s == "Movement"),
    ("CombatLog",   lambda s: s == "Combat Log:"),
)


def _section_for(s: str):
    for name, pred in _SECTION_HEADS:
        if pred(s):
            return name
    return None


class _RecordingFont:
    """Transparent `pygame.font.Font` proxy that reports every rendered string.

    `pygame.font.Font` is an immutable extension type, so `render` cannot be patched on
    the class; the App's three font attributes are wrapped instead. Everything the panel
    draws goes through one of them.
    """

    def __init__(self, font, sink):
        object.__setattr__(self, "_font", font)
        object.__setattr__(self, "_sink", sink)

    def render(self, text, antialias, color, *args, **kwargs):
        self._sink(text)
        return self._font.render(text, antialias, color, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._font, name)


class PanelCapture:
    """Hooks `Button.draw` and the App's fonts for the duration of one panel draw."""

    def __init__(self, app):
        self.app = app
        self.lines = []
        self._section = "-"
        self._in_button = False
        self._drawn = set()
        self._bottom = 0
        self._names = {}          # id(Button) -> attribute name (every App button)
        self._roster = set()      # the combat panel's own widgets, drawn or not
        for attr, val in vars(app).items():
            if not attr.startswith("btn_"):
                continue
            named = []
            if isinstance(val, Button):
                named.append((attr, val))
            elif isinstance(val, dict):
                # btn_cbt_metamagic is a dict of 9 buttons, not a button — Step 0.3 F1.
                named += [(f"{attr}[{int(k)}]", b) for k, b in val.items()
                          if isinstance(b, Button)]
            for name, btn in named:
                self._names[id(btn)] = name
                if attr.startswith("btn_cbt_"):
                    self._roster.add(name)

    # — sinks —
    def _on_text(self, s):
        if self._in_button:
            return            # a button's own label; recorded by _on_button instead
        sec = _section_for(s)
        if sec:
            self._section = sec
        self.lines.append(f"text | {self._section:<11} | {s}")

    def _on_button(self, btn):
        name = self._names.get(id(btn), "<unregistered>")
        self._drawn.add(name)
        r = btn.rect
        self._bottom = max(self._bottom, r.bottom)
        self.lines.append(
            f"btn  | {self._section:<11} | {name} | {btn.text} | "
            f"{r.x},{r.y},{r.w},{r.h} | yes")

    # — run —
    def capture(self, title):
        app = self.app
        real_draw = Button.draw
        capture = self

        def draw(btn, surf):
            capture._on_button(btn)
            capture._in_button = True
            try:
                return real_draw(btn, surf)
            finally:
                capture._in_button = False

        saved_fonts = {a: getattr(app, a) for a in ("font_sm", "font_md", "font_lg")}
        for attr, font in saved_fonts.items():
            setattr(app, attr, _RecordingFont(font, self._on_text))
        Button.draw = draw
        try:
            app._draw_combat_panel()
        finally:
            Button.draw = real_draw
            for attr, font in saved_fonts.items():
                setattr(app, attr, font)

        out = [f"=== {title} ==="]
        out.extend(self.lines)
        for name in sorted(self._roster):
            if name not in self._drawn:
                out.append(f"btn  | {'-':<11} | {name} | - | - | no")
        # A one-line summary of the whole layout: the lowest drawn widget edge, and the
        # scroll the panel sized itself for. A diff here says "the panel got taller"
        # before the reader has scanned a single rect.
        out.append(f"meta | bottom={self._bottom} "
                   f"max_scroll={app._combat_panel_max_scroll}")
        out.append("")
        self.lines = []
        self._drawn = set()
        self._bottom = 0
        self._section = "-"
        return out


# ─────────────────────────────────────────────────────────────────────────────
#  Scene
# ─────────────────────────────────────────────────────────────────────────────

def _weapon(app, name, off_hand=False):
    w = _dict_to_weapon(app.weapon_name_to_dict[name])
    w.off_hand = off_hand
    return w


def _spell(app, name):
    return _dict_to_spell(app.all_spells[app.spell_name_to_idx[name]])


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    raise KeyError(name)


def _build_scene(app):
    """Four combatants chosen so the checkpoints below can reach every Step 0.3 bucket.

    Aria   — Fighter 5, dual-wielding: the normal Action branch, Second Wind (7a),
             the ⚔ Bonus Atk economy-band header (7b), and (with Skarn next door)
             the adjacency-gated Jump/Shove row (7c).
    Skarn  — a foe standing adjacent to Aria. Not automated: nothing steps the frame
             loop here, but keeping it a PC-flagged token also keeps `_start_combat`
             from arming the NPC driver for it.
    Brannor— Cleric 3 (Light Domain): the Channel Divinity cluster (7e) and the
             spell-bearing layout of both economy bands.
    Cyra   — Sorcerer 3 with Metamagic + Sorcery Points: the metamagic toggle dict
             that is drawn outside the bonus-action band (7d).
    """
    _place(app, "Aria",    3, 3)
    _place(app, "Skarn",   4, 3)
    _place(app, "Brannor", 7, 7)
    _place(app, "Cyra",    9, 9)
    app.combat.apply_agent_configs(app.bm)
    for who, fac in (("Aria", PC_TEAM), ("Skarn", FOE_TEAM),
                     ("Brannor", PC_TEAM), ("Cyra", PC_TEAM)):
        app.bm.set_agent_faction(_idx(app, who), fac)

    bm, eng = app.bm, app.combat

    aria = _idx(app, "Aria")
    s = eng.get_agent_stats(bm, aria)
    s.str, s.dex, s.con, s.intel, s.wis, s.cha = 16, 14, 14, 10, 12, 10
    s.hp_max = s.hp_cur = 44
    s.base_ac = 18
    s.is_npc = False
    s.set_class_level(rpg.CharacterClass.Fighter, 5)
    s.initialize_class_resources(rpg.CharacterClass.Fighter, 5)
    eng.set_agent_stats(bm, aria, s)
    eng.set_agent_weapons(bm, aria, [_weapon(app, "Longsword"),
                                     _weapon(app, "Shortsword", off_hand=True)])

    skarn = _idx(app, "Skarn")
    s = eng.get_agent_stats(bm, skarn)
    s.str, s.dex, s.con, s.intel, s.wis, s.cha = 18, 12, 16, 8, 10, 8
    s.hp_max = s.hp_cur = 60
    s.base_ac = 15
    s.is_npc = False
    eng.set_agent_stats(bm, skarn, s)
    eng.set_agent_weapons(bm, skarn, [_weapon(app, "Greataxe")])

    brannor = _idx(app, "Brannor")
    s = eng.get_agent_stats(bm, brannor)
    s.str, s.dex, s.con, s.intel, s.wis, s.cha = 12, 12, 14, 10, 16, 10
    s.hp_max = s.hp_cur = 25
    s.base_ac = 16
    s.is_npc = False
    s.set_class_level(rpg.CharacterClass.Cleric, 3)
    s.cleric_subclass = rpg.ClericSubclass.LightDomain
    s.initialize_class_resources(rpg.CharacterClass.Cleric, 3)
    eng.set_agent_stats(bm, brannor, s)
    eng.set_agent_weapons(bm, brannor, [_weapon(app, "Mace")])
    eng.set_agent_spells(bm, brannor, [_spell(app, "Sacred Flame"),
                                       _spell(app, "Cure Wounds")])

    cyra = _idx(app, "Cyra")
    s = eng.get_agent_stats(bm, cyra)
    s.str, s.dex, s.con, s.intel, s.wis, s.cha = 8, 14, 12, 10, 12, 16
    s.hp_max = s.hp_cur = 20
    s.base_ac = 13
    s.is_npc = False
    s.set_class_level(rpg.CharacterClass.Sorcerer, 3)
    s.initialize_class_resources(rpg.CharacterClass.Sorcerer, 3)
    s.metamagic_options = [rpg.MetamagicOption.Quickened,
                           rpg.MetamagicOption.Seeking]
    eng.set_agent_stats(bm, cyra, s)
    eng.set_agent_spells(bm, cyra, [_spell(app, "Fire Bolt"),
                                    _spell(app, "Magic Missile")])


# ─────────────────────────────────────────────────────────────────────────────
#  Checkpoint driving
# ─────────────────────────────────────────────────────────────────────────────

def _slot(app, name):
    """Initiative slot holding `name`. Looked up by name, not assumed, so a change to
    the initiative dice reorders the list without invalidating every checkpoint."""
    want = _idx(app, name)
    for i, entry in enumerate(app.initiative_order):
        if entry.agent_idx == want:
            return i
    raise KeyError(name)


def _goto(app, name):
    """Put `name` on turn with a clean action economy, without spending engine RNG.

    The panel is a pure function of state, so the checkpoints set that state directly
    rather than stepping turns: an oracle that re-ran the turn pipeline would churn
    every time the dice changed, which is `test_determinism.py`'s job, not this one.
    """
    idx = _idx(app, name)
    app.turn_idx = _slot(app, name)
    app.action_used = False
    app.bonus_used = False          # property → reset_bonus_actions on the current agent
    app.attacks_remaining = 0
    app._attack_sequence_slot = ""
    app.combat_panel_scroll = 0
    app._reset_movement(idx)
    return idx


def _set_conditions(app, idx, **flags):
    cond = app.combat.get_agent_conditions(app.bm, idx)
    for k, v in flags.items():
        setattr(cond, k, v)
    app.combat.set_agent_conditions(app.bm, idx, cond)


def build_output():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()     # nothing below should reach the replay log

    cap = PanelCapture(app)
    out = [
        "# Structural capture of _draw_combat_panel (MULTIPLAYER_PLAN.md Step 0.6).",
        "# text | section | string",
        "# btn  | section | name | label | x,y,w,h | drawn?",
        f"# map={os.path.basename(MAP_PATH)} seed={SEED} "
        f"screen={app.screen.get_size()} panel_x={app._panel_x()}",
        "",
    ]

    # 01 — Action branch: normal. Also 7b (⚔ Bonus Atk, off-hand available) and
    # 7c (Skarn is adjacent, so the three-up Jump/Shove row is drawn).
    aria = _goto(app, "Aria")
    out += cap.capture("01 normal turn — Aria (Fighter 5, dual wield, foe adjacent)")

    # 02 — Action branch: action already spent (the [Action used] arm).
    _goto(app, "Aria")
    app.action_used = True
    out += cap.capture("02 action used — Aria")

    # 03 — Bonus band spent: the [Bonus used] arm. 7d's metamagic toggles and
    # haste_action are drawn OUTSIDE this band, which is what makes them bucket 7d.
    _goto(app, "Aria")
    app.bonus_used = True
    out += cap.capture("03 bonus used — Aria")

    # 04 — Action branch: incapacitated (collapses both bands).
    _goto(app, "Aria")
    _set_conditions(app, aria, incapacitated=True)
    out += cap.capture("04 incapacitated — Aria")
    _set_conditions(app, aria, incapacitated=False)

    # 05 — Action branch: frightened (Dash only).
    _goto(app, "Aria")
    _set_conditions(app, aria, frightened=True)
    out += cap.capture("05 frightened — Aria")
    _set_conditions(app, aria, frightened=False)

    # 06 — Action branch: prone (Stand Up replaces Prone in the five-up row).
    _goto(app, "Aria")
    _set_conditions(app, aria, prone=True)
    out += cap.capture("06 prone — Aria")
    _set_conditions(app, aria, prone=False)

    # 07 — 7c's other member: grappled while adjacent arms Escape Grapple.
    _goto(app, "Aria")
    _set_conditions(app, aria, grappled=True)
    out += cap.capture("07 grappled — Aria (bucket 7c: adjacency + condition)")
    _set_conditions(app, aria, grappled=False)

    # 08 — 7b, the hard half: mid-attack-sequence. Both economy-band headers take
    # their LABEL from `attacks_remaining` and their band from `_attack_sequence_slot`
    # (Step 0.3 F3), and `action_used` is deliberately still True while the sequence
    # runs, so this is also the branch where "[Action used]" must NOT appear.
    _goto(app, "Aria")
    app.action_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "action"
    out += cap.capture("08 mid attack sequence (action slot) — Aria (bucket 7b)")

    # 08b — the same sequence parked in the bonus band.
    _goto(app, "Aria")
    app.bonus_used = True
    app.attacks_remaining = 1
    app._attack_sequence_slot = "bonus"
    out += cap.capture("08b mid attack sequence (bonus slot) — Aria (bucket 7b)")

    # 09 — 7e: the Channel Divinity cluster (Turn Undead + Radiance of the Dawn).
    # Also the spell-bearing layout of both economy bands.
    _goto(app, "Brannor")
    out += cap.capture("09 cleric turn — Brannor (bucket 7e: Channel Divinity cluster)")

    # 10 — 7d: the metamagic toggle dict. Two options learned, both affordable.
    cyra = _goto(app, "Cyra")
    out += cap.capture("10 sorcerer turn — Cyra (bucket 7d: metamagic toggles)")

    # 11 — 7d, the point of the bucket: spending the bonus action must NOT hide the
    # metamagic qualifiers. Quickened is the lone exception and drops out.
    _goto(app, "Cyra")
    app.bonus_used = True
    out += cap.capture("11 sorcerer, bonus spent — Cyra (bucket 7d: band-independent)")

    # 12 — 7d's other member: Haste's extra Action, drawn outside the bonus band.
    _goto(app, "Cyra")
    s = app.combat.get_agent_stats(app.bm, cyra)
    s.haste_action_available = True
    app.combat.set_agent_stats(app.bm, cyra, s)
    app.bonus_used = True
    out += cap.capture("12 hasted, bonus spent — Cyra (bucket 7d: haste_action)")
    s = app.combat.get_agent_stats(app.bm, cyra)
    s.haste_action_available = False
    app.combat.set_agent_stats(app.bm, cyra, s)

    # 13 — a plain foe with no class features: the floor of the panel.
    _goto(app, "Skarn")
    out += cap.capture("13 featureless combatant — Skarn")

    # 14-16 cover the three availability branches of Step 0.3 sections 1 and 9 that
    # checkpoints 01-13 never reach. Added at the head of M2a (before the extraction,
    # against the old fused code) precisely so the extraction has something to be
    # proven identical against — an oracle written afterwards proves nothing.

    # 14 — §1: the Pause/Resume LABEL is state, the one piece of that row which is
    # not a constant. Every checkpoint above captures it unpaused.
    _goto(app, "Aria")
    app.combat_paused = True
    out += cap.capture("14 paused — Aria (§1: pause_resume label from state)")
    app.combat_paused = False

    # 15 — §9: Drop Concentration exists only while the creature is concentrating,
    # and it pushes the drop-weapon row down a slot.
    brannor2 = _goto(app, "Brannor")
    _set_conditions(app, brannor2, concentrating=True)
    out += cap.capture("15 concentrating — Brannor (§9: drop_concentration)")
    _set_conditions(app, brannor2, concentrating=False)

    # 16 — §9: the drop row is an n-up whose button WIDTH depends on how many slots
    # are droppable. Everyone above has three, so nothing has ever exercised n = 1.
    # Skarn's two Unarmed slots are made permanent (a monster's natural weapon),
    # which is the real-world shape of a slot you cannot drop.
    skarn2 = _goto(app, "Skarn")
    _ws = app.combat.get_agent_weapons(app.bm, skarn2)
    _ws[1].permanently_armed = True
    _ws[2].permanently_armed = True
    app.combat.set_agent_weapons(app.bm, skarn2, _ws)
    out += cap.capture("16 one droppable weapon — Skarn (§9: n=1 drop row)")

    return "\n".join(out).rstrip() + "\n"


# ─────────────────────────────────────────────────────────────────────────────
#  Runner
# ─────────────────────────────────────────────────────────────────────────────

# `_start_combat` truncates these two in the cwd (gui/, per run_all_tests.py). They are
# the live session's logs, not test artifacts — leave whatever was there untouched.
_CWD_LOGS = ("replay_log.txt", "combat_log.txt")


def _preserve_cwd_logs():
    saved = {}
    for name in _CWD_LOGS:
        try:
            with open(name, "rb") as f:
                saved[name] = f.read()
        except FileNotFoundError:
            saved[name] = None
    return saved


def _restore_cwd_logs(saved):
    for name, data in saved.items():
        if data is None:
            if os.path.exists(name):
                os.remove(name)
        else:
            with open(name, "wb") as f:
                f.write(data)


def main():
    update = "--update" in sys.argv
    saved = _preserve_cwd_logs()
    try:
        actual = build_output()
    finally:
        _restore_cwd_logs(saved)
        pygame.quit()

    if update:
        with open(GOLDEN_PATH, "w") as f:
            f.write(actual)
        print(f"✅ wrote golden: {GOLDEN_PATH} ({actual.count(chr(10))} lines)")
        return 0

    if not os.path.exists(GOLDEN_PATH):
        print(f"❌ no golden file yet: {GOLDEN_PATH}\n"
              f"   Bootstrap it once with:\n"
              f"       python {os.path.basename(__file__)} --update\n"
              f"   Inspect the output, then commit the golden.")
        return 1

    with open(GOLDEN_PATH) as f:
        expected = f.read()

    if actual == expected:
        n = sum(1 for ln in expected.splitlines() if ln.startswith("==="))
        print(f"✅ test_combat_panel: {n} combat-panel checkpoints match the golden file")
        return 0

    actual_path = GOLDEN_PATH + ".actual"
    with open(actual_path, "w") as f:
        f.write(actual)
    diff = difflib.unified_diff(expected.splitlines(keepends=True),
                                actual.splitlines(keepends=True),
                                fromfile="golden", tofile="actual")
    sys.stdout.writelines(diff)
    print(f"\n❌ test_combat_panel: panel structure differs from golden.\n"
          f"   Wrote actual output to {actual_path}\n"
          f"   If this change is intentional, re-bootstrap with --update.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
