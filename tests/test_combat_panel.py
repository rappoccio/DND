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
frightened / prone), at least one member of each Step 0.3 bucket 7a–7e, and — 14 to 18 —
the availability branches those thirteen never reach, each added BEFORE the M2 step that
converts it so the extraction has something to be proven identical against.

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
import json

import pygame

import rpg_battle_map as rpg
from dialogs import METAMAGIC_OPTIONS
from helpers import _dict_to_item, _dict_to_spell, _dict_to_weapon
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
    # §6 has no heading of the usual kind — its label IS its first line, and it is
    # drawn only when the section exists at all (checkpoint 18).
    ("Portent",     lambda s: s == "Portent Dice:"),
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



def _item(name):
    """An `rpg.Item` straight from the GUI's items.json, as `test_items.py` builds one."""
    with open(os.path.join(_ROOT, "gui", "items.json")) as f:
        for rec in json.load(f):
            if rec["name"] == name:
                return _dict_to_item(rec)
    raise KeyError(name)


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


_BASELINE_STATS = {}     # name -> {attr: value} as `_build_scene` left that combatant


def _stats_fields(s):
    """Every plain (non-callable) attribute of a `Stats`, as a dict.

    Used for both halves of the baseline. Sequences are copied into lists because the
    pybind bindings hand back views, not snapshots.
    """
    out = {}
    for n in dir(s):
        if n.startswith("_"):
            continue
        try:
            v = getattr(s, n)
        except Exception:
            continue
        if callable(v):
            continue
        try:
            out[n] = list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v
        except Exception:
            pass
    return out


def _snapshot_baseline(app):
    """Remember every combatant's stats as `_build_scene` left them.

    `_reclass` restores this before applying a new class, because a good many class
    features are recorded as *sticky fields* on `Stats` rather than derived from the
    class, and `initialize_class_resources` only ever sets them — it never clears the
    previous class's. `has_cunning_action` (Rogue), `weapon_mastery` (Fighter, Druid),
    `can_cast_spell`, `num_attacks`, `feats` and the save-proficiency flags all behave
    this way. `can_cast_spell` in particular decides the Bonus Action band's two-up
    layout, so without the restore a block's GEOMETRY would depend on which class the
    checkpoint before it happened to use, and the golden would be recording the order
    of the checkpoints rather than the panel's rules.

    There is no copy on the binding (`Stats` is neither deep-copyable nor
    copy-constructible), which is why the baseline is a field dict and not an object.
    """
    for name in ("Aria", "Skarn", "Brannor", "Cyra"):
        _BASELINE_STATS[name] = _stats_fields(
            app.combat.get_agent_stats(app.bm, _idx(app, name)))


def _reclass(app, name, cls, level, **fields):
    """Put `name` on turn re-classed from its baseline, and hand back its index.

    Checkpoints 19+ all work this way. Placing a fifth combatant would reorder
    initiative and churn every block above it, so the cheap path — the one 17 and 18
    already take — is to re-class one of the four that are already there. Restoring the
    baseline first (see `_snapshot_baseline`) is what makes each block independent of
    the ones before it.

    `fields` are set BEFORE `initialize_class_resources`, so a subclass reaches the
    resource table that depends on it (War Priest, Zealous Presence, …); a resource's
    *current* value is set by the caller afterwards, because initialization would
    overwrite it.

    The baseline does NOT cover conditions, weapons or inventory — a checkpoint that
    arms one of those clears it again itself.
    """
    idx = _goto(app, name)
    s = app.combat.get_agent_stats(app.bm, idx)
    for k, v in _BASELINE_STATS[name].items():
        try:
            setattr(s, k, v)        # derived/read-only fields simply refuse; that is
        except Exception:           # fine, set_class_level rebuilds them below
            pass
    s.set_class_level(cls, level)
    for k, v in fields.items():
        setattr(s, k, v)
    s.initialize_class_resources(cls, level)
    app.combat.set_agent_stats(app.bm, idx, s)
    return idx

def _set_res(app, idx, name, current):
    """Set a named resource's remaining uses on `idx`, in place.

    `_reclass` runs `initialize_class_resources`, which fills every resource to its
    maximum — so a checkpoint that needs a PARTLY SPENT one (Restore Beguiling Magic
    asks for a resource that is not full; the Glamour windows are the arm you reach
    once the use is gone) sets it afterwards, the way the panel's own handlers do.
    """
    s = app.combat.get_agent_stats(app.bm, idx)
    r = s.get_resource(name)
    if r is None:
        raise KeyError(f"{name} — not a resource this creature has")
    r.current = current
    s.resources[name] = r
    app.combat.set_agent_stats(app.bm, idx, s)


def build_output():
    app = App(MAP_PATH, seed=SEED)
    _build_scene(app)
    app._start_combat()
    app.combat.stop_recording()     # nothing below should reach the replay log
    _snapshot_baseline(app)

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

    # 17-18 are M2b's two blind spots, added the same way and for the same reason: the
    # 16 checkpoints above reach all five arms of the Action branch, but neither of the
    # two guards M2b actually MOVES is ever satisfied by this scene — `btn_cbt_nick` and
    # `btn_cbt_use_portent` are "no" in every block. Extracting a rule the golden has
    # only ever seen switched off proves nothing about it.

    # 17 — §4's [Action used] arm is not empty after all: Nick relocates the off-hand
    # attack into the Attack action, so its button is the one thing that arm can draw.
    # Aria is a Fighter, so `initialize_class_resources` already gave her the
    # "Weapon Mastery" feat (class_resources.cpp:866); all she lacks is a Nick weapon.
    aria2 = _goto(app, "Aria")
    _ws = app.combat.get_agent_weapons(app.bm, aria2)
    _ws[1] = _weapon(app, "Dagger", off_hand=True)      # Dagger's mastery IS Nick
    app.combat.set_agent_weapons(app.bm, aria2, _ws)
    _set_conditions(app, aria2, offhand_attack_used=False)
    app.action_used = True
    out += cap.capture("17 nick off-hand — Aria (§4: the [Action used] arm's one button)")

    # 18 — §6 in full: the Portent Dice block exists only for a Diviner Wizard holding
    # dice, and it is a section whose HEADING and dice readout appear exactly when its
    # button does. Cyra is re-classed rather than a fifth combatant being placed, which
    # would reorder initiative and churn all 17 blocks above.
    cyra2 = _goto(app, "Cyra")
    s = app.combat.get_agent_stats(app.bm, cyra2)
    s.set_class_level(rpg.CharacterClass.Wizard, 3)
    s.initialize_class_resources(rpg.CharacterClass.Wizard, 3)
    s.wizard_subclass = rpg.WizardSubclass.Diviner
    s.portent_dice = [17, 3]
    app.combat.set_agent_stats(app.bm, cyra2, s)
    out += cap.capture("18 diviner with portent — Cyra (§6: the whole section)")

    # 19 — a Draconic Sorcerer with an affinity element chosen. Until F8 was fixed
    # this state did not render a button: it raised NameError out of the draw pass
    # (`bonus_used` for `self.bonus_used`), so the whole panel went down for any
    # Draconic Sorcerer L6+ who had picked an element and was not already resisting.
    # `btn_cbt_draconic_resistance` had therefore never been drawn by anything.
    cyra3 = _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 14,
                     sorcerer_subclass=rpg.SorcererSubclass.Draconic,
                     draconic_affinity_type=0)
    out += cap.capture("19 draconic sorcerer with an affinity — Cyra (F8)")

    # ── 20-48: bucket 7a's coverage (M2c) ───────────────────────────────────
    # 78 of the panel's 110 named buttons were drawn by no checkpoint at all, and ~52
    # of those are bucket 7a — the flat class/subclass/level/resource guards M2c
    # converts. A golden that reads "no" for a button in every block cannot tell
    # whether an extraction preserved its rule or deleted it, so these are added FIRST,
    # against the still-fused code, exactly as 14-18 were for M2a and M2b. Batched by
    # class, because one creature shows a whole class's band at once.
    #
    # Every block re-classes a combatant rather than placing a fifth (see `_reclass`),
    # and every block sets its subclass explicitly — including to NONE — because
    # `set_class_level` replaces the class and leaves the old subclass field behind.

    # 20 — Abjurer with an active ward (temp HP is the ward's pool).
    cyra_w = _reclass(app, "Cyra", rpg.CharacterClass.Wizard, 3,
                      wizard_subclass=rpg.WizardSubclass.Abjurer)
    _s = app.combat.get_agent_stats(app.bm, cyra_w)
    _s.temp_hp = 5
    app.combat.set_agent_stats(app.bm, cyra_w, _s)
    out += cap.capture("20 abjurer, ward charged — Cyra (charge_arcane_ward)")
    _s = app.combat.get_agent_stats(app.bm, cyra_w)
    _s.temp_hp = 0                      # temp HP is in the HP readout, not class-gated
    app.combat.set_agent_stats(app.bm, cyra_w, _s)

    # 21/22 — Wild Shape is one button with two labels, and the active form also prints
    # a line of text above it. Both arms, because the label is the state.
    cyra_d = _reclass(app, "Cyra", rpg.CharacterClass.Druid, 2)
    out += cap.capture("21 druid, unshifted — Cyra (wild_shape)")
    _s = app.combat.get_agent_stats(app.bm, cyra_d)
    _s.wild_shape_active = True
    _s.wild_shape_form_name = "Wolf"
    app.combat.set_agent_stats(app.bm, cyra_d, _s)
    out += cap.capture("22 druid, shifted — Cyra (wild_shape: the Exit arm)")
    _s = app.combat.get_agent_stats(app.bm, cyra_d)
    _s.wild_shape_active = False
    app.combat.set_agent_stats(app.bm, cyra_d, _s)

    # 23 — the Monk band: five buttons under one class, all Focus-gated.
    _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
             monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    out += cap.capture("23 monk, open hand 17 — Cyra (patient_defense, step_of_wind, "
                       "wholeness_of_body, martial_arts, flurry_of_blows)")

    # 24 — the other Monk subclass that adds a bonus-action button.
    _reclass(app, "Cyra", rpg.CharacterClass.Monk, 3,
             monk_subclass=rpg.MonkSubclass.WarriorOfMercy)
    out += cap.capture("24 monk, mercy 3 — Cyra (hand_of_healing)")

    # 25/26 — Rage is shared; each Path adds its own L10+ presence. Berserker needs 14,
    # not the 10 the panel's guard tests: `class_resources.cpp:74` only grants the
    # Intimidating Presence resource at 14, so 10-13 is a level test the resource test
    # already dominates. Recorded as F9; the panel is left exactly as it is.
    _reclass(app, "Cyra", rpg.CharacterClass.Barbarian, 14,
             barbarian_subclass=rpg.BarbianSubclass.Berserker)
    out += cap.capture("25 barbarian, berserker 14 — Cyra (rage, intimidating_presence)")
    _reclass(app, "Cyra", rpg.CharacterClass.Barbarian, 10,
             barbarian_subclass=rpg.BarbianSubclass.Zealot)
    out += cap.capture("26 barbarian, zealot 10 — Cyra (rage, zealous_presence)")

    # 27-29 — the Warlock band. 29 carries NO subclass, so it is also the check that
    # re-classing clears the previous block's subclass-gated buttons.
    _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 6,
             warlock_subclass=rpg.WarlockSubclass.GreatOldOne)
    out += cap.capture("27 warlock, great old one 6 — Cyra "
                       "(clairvoyant_combatant, magical_cunning)")
    _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 3,
             warlock_subclass=rpg.WarlockSubclass.Celestial)
    out += cap.capture("28 warlock, celestial 3 — Cyra (healing_light)")
    _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 5,
             warlock_subclass=rpg.WarlockSubclass.NONE,
             eldritch_invocations=[8, 18])
    out += cap.capture("29 warlock, invocations 8+18 — Cyra "
                       "(one_with_shadows, familiar)")

    # 30/31 — the Cleric band beyond the Channel Divinity cluster 09 already covers.
    _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 10,
             cleric_subclass=rpg.ClericSubclass.WarDomain)
    out += cap.capture("30 cleric, war 10 — Cyra (war_priest, divine_intervention)")
    _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 17,
             cleric_subclass=rpg.ClericSubclass.LightDomain)
    out += cap.capture("31 cleric, light 17 — Cyra (corona)")

    # 32-35 — the Sorcerer subclasses. Draconic is checkpoint 19 (F8).
    _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 6,
             sorcerer_subclass=rpg.SorcererSubclass.WildMagic)
    out += cap.capture("32 sorcerer, wild magic 6 — Cyra (bend_luck, tides_of_chaos)")

    # 33 — the three Wild Magic surge affordances are bare stats flags with no class
    # guard at all, so they must be cleared again afterwards or they leak downward.
    cyra_wm = _idx(app, "Cyra")
    _s = app.combat.get_agent_stats(app.bm, cyra_wm)
    _s.wild_magic_extra_action = True
    _s.wild_magic_bonus_cast_turns = 2
    _s.wild_magic_teleport_bonus_turns = 2
    app.combat.set_agent_stats(app.bm, cyra_wm, _s)
    out += cap.capture("33 sorcerer, surge window open — Cyra (the 3 wild_magic_*)")
    _s = app.combat.get_agent_stats(app.bm, cyra_wm)
    _s.wild_magic_extra_action = False
    _s.wild_magic_bonus_cast_turns = 0
    _s.wild_magic_teleport_bonus_turns = 0
    app.combat.set_agent_stats(app.bm, cyra_wm, _s)

    _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 18,
             sorcerer_subclass=rpg.SorcererSubclass.Clockwork)
    out += cap.capture("34 sorcerer, clockwork 18 — Cyra "
                       "(trance_of_order, bastion_of_law, clockwork_cavalcade)")
    _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 18,
             sorcerer_subclass=rpg.SorcererSubclass.Aberrant)
    out += cap.capture("35 sorcerer, aberrant 18 — Cyra "
                       "(revelation_in_flesh, warping_implosion)")

    # 36-38 — Rogue, and the two Fighter subclass buttons Aria never shows.
    _reclass(app, "Cyra", rpg.CharacterClass.Rogue, 3,
             rogue_subclass=rpg.RogueSubclass.NONE)
    out += cap.capture("36 rogue 3 — Cyra (steady_aim)")
    _reclass(app, "Cyra", rpg.CharacterClass.Fighter, 3,
             fighter_subclass=rpg.FighterSubclass.BattleMaster)
    out += cap.capture("37 fighter, battle master 3 — Cyra (bm_maneuver)")
    # `btn_cbt_telekinetic` has TWO draw sites — the Telekinetic feat (17211) and Psi
    # Warrior's Telekinetic Movement (18077) — sharing one widget. This is the second;
    # 46 is the first. See F10: it is why the button is NOT in M2c's scope.
    _reclass(app, "Cyra", rpg.CharacterClass.Fighter, 3,
             fighter_subclass=rpg.FighterSubclass.PsiWarrior)
    out += cap.capture("38 fighter, psi warrior 3 — Cyra (telekinetic, Psi site)")

    # 39-42 — the Paladin band: one oath per block, and all three L20 capstones.
    _reclass(app, "Cyra", rpg.CharacterClass.Paladin, 3,
             paladin_oath=rpg.PaladinOath.OathOfDevotion)
    out += cap.capture("39 paladin, devotion 3 — Cyra (lay_on_hands, sacred_weapon)")
    _reclass(app, "Cyra", rpg.CharacterClass.Paladin, 20,
             paladin_oath=rpg.PaladinOath.OathOfVengeance)
    out += cap.capture("40 paladin, vengeance 20 — Cyra "
                       "(vow_of_enmity, avenging_angel)")
    _reclass(app, "Cyra", rpg.CharacterClass.Paladin, 20,
             paladin_oath=rpg.PaladinOath.OathOfAncients)
    out += cap.capture("41 paladin, ancients 20 — Cyra (elder_champion)")
    # Inspiring Smite only appears once a Divine Smite has landed this turn.
    cyra_g = _reclass(app, "Cyra", rpg.CharacterClass.Paladin, 20,
                      paladin_oath=rpg.PaladinOath.OathOfGlory)
    _set_conditions(app, cyra_g, divine_smite_used=True)
    out += cap.capture("42 paladin, glory 20 after a smite — Cyra "
                       "(inspiring_smite, living_legend)")
    _set_conditions(app, cyra_g, divine_smite_used=False)

    # 43/44 — Bard. The die a Bard hands out is held by the RECIPIENT, so
    # `use_inspiration` has no class guard of its own; it must be cleared again.
    cyra_b = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 3,
                      bard_subclass=rpg.BardCollege.Lore)
    out += cap.capture("43 bard, lore 3 — Cyra (grant_inspiration)")
    _s = app.combat.get_agent_stats(app.bm, cyra_b)
    _s.bardic_inspiration_die = 6
    app.combat.set_agent_stats(app.bm, cyra_b, _s)
    out += cap.capture("44 bard holding a die — Cyra (use_inspiration)")
    _s = app.combat.get_agent_stats(app.bm, cyra_b)
    _s.bardic_inspiration_die = 0
    app.combat.set_agent_stats(app.bm, cyra_b, _s)

    # 45/46 — Ranger.
    _reclass(app, "Cyra", rpg.CharacterClass.Ranger, 3,
             ranger_subclass=rpg.RangerSubclass.GloomStalker)
    out += cap.capture("45 ranger, gloom stalker 3 — Cyra (dread_ambusher)")
    _reclass(app, "Cyra", rpg.CharacterClass.Ranger, 14,
             ranger_subclass=rpg.RangerSubclass.BeastMaster)
    out += cap.capture("46 ranger, beast master 14 — Cyra "
                       "(tireless, natures_veil, companion)")

    # 47 — the guards that are not class-gated at all: four feats, two conditions and an
    # inventory. Skarn carries them because he is the one combatant with no class, so
    # nothing else in the block competes for the band. All of it is cleared again —
    # none of these guards would be stopped by a later re-class.
    skarn3 = _goto(app, "Skarn")
    _s = app.combat.get_agent_stats(app.bm, skarn3)
    for _f in ("Boon of Fate", "Boon of the Night Spirit",
               "Boon of Dimensional Travel", "Telekinetic"):
        _s.add_feat(_f)
    app.combat.set_agent_stats(app.bm, skarn3, _s)
    _set_conditions(app, skarn3, gwm_hew_available=True, blink_steps_available=True,
                    burning=True)
    app.combat.add_item_to_agent(app.bm, skarn3, _item("Potion of Healing"))
    out += cap.capture("47 feats, conditions and an item — Skarn (boon_of_fate, "
                       "merge_shadows, blink_steps, gwm_hew, telekinetic feat site, "
                       "use_item, extinguish)")
    _s = app.combat.get_agent_stats(app.bm, skarn3)
    _s.feats = []
    app.combat.set_agent_stats(app.bm, skarn3, _s)
    _set_conditions(app, skarn3, gwm_hew_available=False, blink_steps_available=False,
                    burning=False)
    app.combat.set_agent_items(app.bm, skarn3, [])

    # 48 — Quivering Palm, last of the batch because planting it leaves a delayed-trigger
    # condition on Skarn that nothing removes, and 47 is the only later block that looks
    # at him.
    cyra_q = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
                      monk_subclass=rpg.MonkSubclass.WarriorOfTheOpenHand)
    app.combat.plant_quivering_palm(app.bm, cyra_q, _idx(app, "Skarn"))
    out += cap.capture("48 monk with vibrations planted — Cyra (quivering_palm)")

    # ── 49-63: the clusters and the spatial predicates (M2d) ────────────────
    # 21 of the panel's buttons are still DARK — they read "no" in all 50 blocks above,
    # so a golden could not tell an extraction that preserved their rule from one that
    # deleted it. They are exactly M2d's: bucket 7e's clusters (several of them nested
    # inside another button's resource test) and bucket 7c's spatial predicates. Same
    # order 14-18 and 20-48 took: coverage FIRST, against the still-fused code.
    #
    # Batched by cluster rather than by class, because a cluster shares one guard and
    # one arming flag — which is also why M2d cannot convert them one button at a time.

    # 49/50 — Invoke Duplicity. The trio hangs off `_my_duplicates(cur_idx)`, a scan of
    # every placed agent, so 49 is the no-duplicate arm (only the activation shows) and
    # 50 the arm where one exists. L6 so Trickster's Transposition is reached too; the
    # duplicate is spawned exactly as `_resolve_invoke_duplicity` spawns one, far from
    # everybody so it cannot perturb the adjacency scan, and tombstoned again after.
    cyra_t = _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 6,
                      cleric_subclass=rpg.ClericSubclass.TrickeryDomain)
    out += cap.capture("49 cleric, trickery 6 — Cyra (turn_undead, invoke_duplicity)")

    _dup_cfg = rpg.AgentConfig()
    _dup_cfg.name      = "Cyra (Duplicate)"
    _dup_cfg.size      = 1
    _dup_cfg.start_col = 1
    _dup_cfg.start_row = 1
    _dup = app.bm.spawn_agent(_dup_cfg)
    app.bm.set_agent_summoner_idx(_dup, cyra_t)
    app.bm.set_agent_summon_spell(_dup, "Invoke Duplicity")
    out += cap.capture("50 cleric, trickery 6 with a duplicate — Cyra "
                       "(move_duplicity, swap_duplicity)")
    app.bm.set_agent_removed_from_play(_dup, True)

    # 51 — the third arm of the Channel Divinity cluster. 09 covers Turn Undead +
    # Radiance of the Dawn (Light); Preserve Life is Life Domain and nothing else
    # reaches it.
    _reclass(app, "Cyra", rpg.CharacterClass.Cleric, 3,
             cleric_subclass=rpg.ClericSubclass.LifeDomain)
    out += cap.capture("51 cleric, life 3 — Cyra (preserve_life)")

    # 52/53 — the College of Glamour four, which live INSIDE `grant_inspiration`'s own
    # Bardic Inspiration test — the nesting that makes them a cluster and not a run.
    # Two of them are `resource OR window-already-open`, so both arms are needed: 52
    # has the uses and no window, 53 has the windows and no uses. Beguiling Magic is
    # spent in 52 because Restore Beguiling Magic asks for a resource that is NOT full.
    cyra_gl = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
                       bard_subclass=rpg.BardCollege.Glamour)
    _set_res(app, cyra_gl, "Beguiling Magic", 0)
    out += cap.capture("52 bard, glamour 14 — Cyra (mantle, mantle_majesty, "
                       "unbreakable_majesty, beguiling_restore)")

    cyra_gl = _reclass(app, "Cyra", rpg.CharacterClass.Bard, 14,
                       bard_subclass=rpg.BardCollege.Glamour)
    _set_res(app, cyra_gl, "Mantle of Majesty", 0)
    _set_res(app, cyra_gl, "Unbreakable Majesty", 0)
    _s = app.combat.get_agent_stats(app.bm, cyra_gl)
    _s.mantle_majesty_turns  = 2
    _s.majestic_presence_turns = 2
    app.combat.set_agent_stats(app.bm, cyra_gl, _s)
    out += cap.capture("53 bard, glamour 14, uses spent but windows open — Cyra "
                       "(the OR arm of mantle_majesty and unbreakable_majesty)")

    # 54 — the Soulknife pair. Both labels carry the Psionic Energy count, so the label
    # is state here in the way Wild Shape's is; L13 reaches both.
    _reclass(app, "Cyra", rpg.CharacterClass.Rogue, 13,
             rogue_subclass=rpg.RogueSubclass.Soulknife)
    out += cap.capture("54 rogue, soulknife 13 — Cyra (psychic_teleport, psychic_veil)")

    # 55 — the Shadow Monk trio. Two are Bonus Actions and the third is a Magic action
    # gated on Focus, which is why spending the bonus action does not take all three.
    _reclass(app, "Cyra", rpg.CharacterClass.Monk, 17,
             monk_subclass=rpg.MonkSubclass.WarriorOfShadow)
    out += cap.capture("55 monk, shadow 17 — Cyra (shadow_step, cloak_of_shadows, "
                       "shadow_arts_darkness)")

    # 56/57 — the Elemental Monk pair. Attunement's label flips to a tick once the
    # effect is running, and that flag lives on the CONDITIONS, not the stats, so 57
    # sets and clears it rather than re-classing.
    cyra_el = _reclass(app, "Cyra", rpg.CharacterClass.Monk, 6,
                       monk_subclass=rpg.MonkSubclass.WarriorOfFourElements)
    out += cap.capture("56 monk, elements 6 — Cyra (elemental_attunement, "
                       "elemental_burst)")
    _set_conditions(app, cyra_el, elemental_attunement_active=True)
    out += cap.capture("57 monk, elements 6, attunement running — Cyra (the ✓ label)")
    _set_conditions(app, cyra_el, elemental_attunement_active=False)

    # 58/59 — the Archfey trio, and the one piece of §7 that WRITES to the app during
    # the draw pass: the rider cycle is capped at 3 effects below L6 and 5 from L6, and
    # the panel clamps a stale selection back to 0 on the spot. 58 is L6 with a rider
    # chosen (the label is the selection); 59 is L3 with the selection left at 4, which
    # only the clamp makes drawable — and it is also the arm where Misty Escape, an L6
    # Reaction, is absent.
    _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 6,
             warlock_subclass=rpg.WarlockSubclass.Archfey)
    app.steps_of_fey_effect = 2
    out += cap.capture("58 warlock, archfey 6, rider selected — Cyra (fey_effect, "
                       "steps_of_fey, misty_escape)")
    _reclass(app, "Cyra", rpg.CharacterClass.Warlock, 3,
             warlock_subclass=rpg.WarlockSubclass.Archfey)
    app.steps_of_fey_effect = 4
    out += cap.capture("59 warlock, archfey 3, stale rider — Cyra (the L3 cap clamps "
                       "the selection back to None)")
    app.steps_of_fey_effect = 0

    # 60-62 — bucket 7c, the three predicates that are neither class nor resource but a
    # scan of the other agents. Aria drives them because Skarn is the only combatant
    # standing next to anybody.

    # 60 — Drop Grapple scans every OTHER agent for one this creature is holding, and
    # is drawn OUTSIDE the bonus-action band (it is a free action).
    aria_g = _goto(app, "Aria")
    skarn_g = _idx(app, "Skarn")
    _set_conditions(app, skarn_g, grappled=True, grappler_idx=aria_g)
    out += cap.capture("60 grappling a neighbour — Aria (bucket 7c: grapple_drop)")

    # 61 — the same hold, plus a weapon flagged `auto_use_when_grappling`: the engine's
    # `pending_auto_grapple_strike` then points at it and the one-click Bite appears.
    # No monster in this scene carries such a weapon, so Aria's Longsword is flagged
    # for the block and her original pair restored after it.
    _bite = _weapon(app, "Longsword")
    _bite.auto_use_when_grappling = True
    app.combat.set_agent_weapons(app.bm, aria_g,
                                 [_bite, _weapon(app, "Shortsword", off_hand=True)])
    out += cap.capture("61 grappling with an auto-bite weapon — Aria "
                       "(bucket 7c: bite_grappled)")
    app.combat.set_agent_weapons(app.bm, aria_g,
                                 [_weapon(app, "Longsword"),
                                  _weapon(app, "Shortsword", off_hand=True)])
    _set_conditions(app, skarn_g, grappled=False, grappler_idx=-1)

    # 62 — Free from Net: netted yourself, or standing within 5 ft of someone who is.
    # An Action, so it is outside the bonus band too.
    _goto(app, "Aria")
    _set_conditions(app, aria_g, netted=True)
    out += cap.capture("62 netted — Aria (bucket 7c: escape_net)")
    _set_conditions(app, aria_g, netted=False)

    # 63 — F10, pinned. `btn_cbt_telekinetic` is ONE widget with TWO draw sites: the
    # Telekinetic feat (47) and Psi Warrior's Telekinetic Movement (38). A Psi Warrior
    # who has taken the feat satisfies both, so the widget is positioned and painted at
    # the upper site and then moved and painted again at the lower one — the upper is a
    # ghost with no rect behind it. No checkpoint had ever driven that state, which is
    # why the golden recorded the two sites as if they were alternatives. It records
    # the double draw now, so the F10 fix has a before to be a change from.
    cyra_f10 = _reclass(app, "Cyra", rpg.CharacterClass.Fighter, 3,
                        fighter_subclass=rpg.FighterSubclass.PsiWarrior)
    _s = app.combat.get_agent_stats(app.bm, cyra_f10)
    _s.add_feat("Telekinetic")
    app.combat.set_agent_stats(app.bm, cyra_f10, _s)
    out += cap.capture("63 psi warrior 3 WITH the Telekinetic feat — Cyra "
                       "(F10: one widget, both draw sites in one pass)")
    _s = app.combat.get_agent_stats(app.bm, cyra_f10)
    _s.feats = []
    app.combat.set_agent_stats(app.bm, cyra_f10, _s)

    # 64-65 — bucket 7b's dark arm. The economy-band header row is a fixed TWO-COLUMN
    # band, and no checkpoint above has ever drawn both of its columns: Aria has an
    # off-hand and no spells (the one-up), Cyra and Brannor have spells and no off-hand
    # (the two-up with its left column empty). A dual-wielder who also casts fills both,
    # and that is the arm M2e's conversion has to be proven identical on.
    aria_sb = _goto(app, "Aria")
    app.combat.set_agent_spells(app.bm, aria_sb, [_spell(app, "Fire Bolt")])
    out += cap.capture("64 dual-wield caster — Aria (bucket 7b: both band headers)")

    # 65 — the same two-up mid-sequence in the BONUS slot: the left column's LABEL takes
    # the attack count, and the band stays open although `bonus_used` is set. 08b pins
    # that pair in the one-up; this is the only block that pins it in the two-up.
    _goto(app, "Aria")
    app.bonus_used = True
    app.attacks_remaining = 2
    app._attack_sequence_slot = "bonus"
    out += cap.capture("65 dual-wield caster mid bonus sequence — Aria (bucket 7b)")
    app.combat.set_agent_spells(app.bm, aria_sb, [])

    # 66-69 — bucket 7d's dict, the last of the "add the checkpoint first" debt.
    # `_build_scene` teaches Cyra two of the nine options, so SEVEN of the nine toggles
    # have read `no` in every block above — and with them every other rule of that draw
    # site: the armed tick and its highlight, the second armed slot, and the Sorcery
    # Incarnate caption.

    # 66 — all nine learned, and a L7 Sorcerer's 7 Sorcery Points afford every one.
    cyra_mm = _reclass(app, "Cyra", rpg.CharacterClass.Sorcerer, 7)
    _s = app.combat.get_agent_stats(app.bm, cyra_mm)
    _s.metamagic_options = [v for v, _n, _sp, _note in METAMAGIC_OPTIONS]
    app.combat.set_agent_stats(app.bm, cyra_mm, _s)
    out += cap.capture("66 sorcerer 7, all nine metamagic options — Cyra "
                       "(bucket 7d: the seven dark toggles)")

    # 67 — armed. The tick is part of the LABEL and the highlight is a second rect
    # drawn over the button, so both belong in the capture. Seeking is the independent
    # toggle (it stacks rather than radio-selecting), so arming it alongside a
    # radio-selected option covers both branches of the armed test in one block.
    app.armed_metamagic = rpg.MetamagicOption.Heightened
    app.armed_seeking = True
    out += cap.capture("67 two metamagic options armed — Cyra (bucket 7d: the tick)")

    # 68 — Sorcery Incarnate (L7 + Innate Sorcery running): the caption above the
    # toggles, and the SECOND armed slot, which exists only while it is active.
    _s = app.combat.get_agent_stats(app.bm, cyra_mm)
    _s.innate_sorcery_turns = 10
    app.combat.set_agent_stats(app.bm, cyra_mm, _s)
    app.armed_metamagic2 = rpg.MetamagicOption.Twinned
    out += cap.capture("68 sorcery incarnate, two options armed — Cyra (bucket 7d)")

    # 69 — the same caption with NO toggles under it: Sorcery Incarnate is a property of
    # the creature, and affordability is a property of each option, so an empty purse
    # leaves the heading standing alone. It is the one state that proves the caption is
    # not drawn by the buttons' own gate.
    _set_res(app, cyra_mm, "Sorcery Points", 0)
    out += cap.capture("69 sorcery incarnate with no Sorcery Points — Cyra "
                       "(bucket 7d: the caption outlives its buttons)")
    app.armed_metamagic = rpg.MetamagicOption.NONE
    app.armed_metamagic2 = rpg.MetamagicOption.NONE
    app.armed_seeking = False

    # 99 — combat running with NOBODY on turn (`_current_agent_idx()` out of range:
    # combat started with no combatants, or the acting token was removed). This is the
    # one place M2b deliberately CHANGED what the panel draws, so it is recorded here
    # rather than only asserted about: the fused code drew Unarmed and the whole
    # five-up posture row for a creature that does not exist — it reached them through
    # a branch whose only per-creature guard was `_cur_has_weapons`, which is False out
    # of range while the row itself was unguarded. `ActionMenu._action` returns nothing
    # for an index it cannot read, so §4 is now empty here. See the plan's F7.
    # Last, because it leaves the app with no initiative order.
    _goto(app, "Aria")
    app.initiative_order = []
    out += cap.capture("99 nobody on turn — out-of-range agent (F7)")

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
