#!/usr/bin/env python3
"""The restore oracle (MULTIPLAYER_PLAN.md M6.0).

M6's other slices are each held to this one check: a fight saved at the turn boundary
and restored into a fresh ``App`` must be indistinguishable from the fight it came from.
"Indistinguishable" is a fingerprint of everything a turn can read: every agent at its
raw index, the board's doors, effects, lights and terrain, the engine snapshot and the
Python turn loop, including the NPC driver that runs an automated turn on the next frame.

The scene is the hard one Step 0 named:
  · a summon on the map, and a dismissed summon left as a tombstone;
  · Wall of Fire (spell + terrain effects) and Darkness (a light effect), both cast
    through the engine, the way a real turn places them;
  · an opened door;
  · an automated NPC on turn, saved before its turn runs (D-M6-1).

**The oracle is a ratchet, both ways.** ``KNOWN_GAPS`` lists every fingerprint key that
the current save path does not restore. The test fails when a key outside that list
breaks, and also when a listed key starts restoring, so each slice that closes a gap must
delete it from the list. The list is empty when M6 is done.

``_save`` and ``_restore`` are the autosave ring since M6.4: ``autosave.save`` at the
turn boundary, then ``autosave.restore`` into a fresh ``App`` pointed at the same encounter,
which is what a DM does after a crash. Both lists are empty: M6 restores everything the
fingerprint reads.

A plain fight (no summon, no effect, a PC on turn) is the control. Until M6.2 the actor on
turn came back without its condition flags (F-M6-7); it now restores cleanly, and stays a
ratchet so it keeps doing so. The control is also run through the DM's own encounter save
and Load (``_dm_save`` / ``_dm_restore``), so that path stays under test as well.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import enum
import json
import shutil
import tempfile

import rpg_battle_map as rpg

import autosave
from main import App
from net.roster import PC_FACTION

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261020
FOE_FACTION = 1

# Every fingerprint key the current save path loses, measured on 2026-10-20 (M6.0). See
# "M6.0 — what landed" in the plan for what each one is. A slice that closes a gap deletes
# it here. A slice that un-masks a gap (M6.2 lets the combat resume run, which exposes
# what the resume itself loses) may add it, and says so in its plan entry.

# The control. Clean since M6.2: the board snapshot in `_combat.json` carries the
# condition flags (F-M6-7) and the movement budgets through the DM's own save and load.
KNOWN_PLAIN_GAPS = frozenset()

# The hard scene. Since M6.2 the raw-basis save keeps the summon and the tombstone at
# their index, so the resume runs, and the board snapshot brings back the effects, the
# light and terrain they set, and every agent's fight state. Since M6.4 the restore
# re-arms the NPC drive (F-M6-4), the last gap.
KNOWN_GAPS = frozenset()


# ─────────────────────────────────────────────────────────────────────────────
#  The fingerprint
# ─────────────────────────────────────────────────────────────────────────────

def _dump(obj, depth=0):
    """A plain, comparable form of an engine value: scalars as themselves, enums by name,
    sequences element-wise, and a bound object as its public data attributes."""
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, enum.Enum) or hasattr(type(obj), "__members__"):   # pybind11 enums too
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): _dump(v, depth + 1) for k, v in sorted(obj.items(), key=str)}
    if isinstance(obj, (list, tuple, set, frozenset)):
        items = [_dump(v, depth + 1) for v in obj]
        return sorted(items, key=repr) if isinstance(obj, (set, frozenset)) else items
    if depth > 4:
        return repr(obj)
    out = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception as e:                       # a property that refuses: record it
            out[name] = f"<{type(e).__name__}>"
            continue
        if callable(val):
            continue
        out[name] = _dump(val, depth + 1)
    return out if out else repr(obj)


def _canonical(node):
    """The engine snapshot with its hash-map arrays sorted. An int-keyed
    `std::unordered_map` serializes as an array of two-field entries (`{agent, feet}`,
    `{caster, targets}`, …) in hash-iteration order, and a map rebuilt by a restore can
    iterate in a different order while holding the same entries (M6.2 measured it on the
    movement budgets). Order there is not state, so it is not compared. Every other array
    keeps its order."""
    if isinstance(node, dict):
        return {k: _canonical(v) for k, v in node.items()}
    if isinstance(node, list):
        items = [_canonical(v) for v in node]
        if items and all(isinstance(v, dict) and len(v) == 2 for v in items):
            items.sort(key=lambda v: json.dumps(v, sort_keys=True))
        return items
    return node


def _cells(bm):
    return [rpg.Cell(c, r) for r in range(bm.grid_rows) for c in range(bm.grid_cols)]


def fingerprint(app) -> dict:
    """Everything a turn can read, one comparable value per key."""
    bm, combat = app.bm, app.combat
    fp = {"agents.basis": [pt.name for pt in bm.placed_agents]}
    for i, pt in enumerate(bm.placed_agents):
        key = f"agents.{pt.name}"
        fp[f"{key}.placement"] = {
            "idx": i, "origin": (pt.origin.col, pt.origin.row), "size": pt.size,
            "faction": pt.faction, "controller": pt.controller,
            "summoner_idx": pt.summoner_idx, "removed": pt.removed_from_play,
            "on_deck": bm.is_agent_on_deck(i),
            "automated": bm.is_agent_npc_automated(i),
        }
        fp[f"{key}.movement"] = (pt.walk_remaining, pt.fly_remaining,
                                 pt.swim_remaining, pt.burrow_remaining)
        fp[f"{key}.stats"] = _dump(combat.get_agent_stats(bm, i))
        fp[f"{key}.conditions"] = _dump(combat.get_agent_conditions(bm, i))

    fp["board.doors"] = _dump(list(bm.doors))
    fp["board.terrain_effects"] = _dump(list(bm.active_terrain_effects))
    fp["board.spell_effects"] = _dump(list(bm.active_spell_effects))
    fp["board.light_effects"] = _dump(list(bm.active_light_effects))
    cells = _cells(bm)
    fp["board.light_levels"] = [str(bm.get_light_level(c)) for c in cells]
    fp["board.terrain_types"] = [str(bm.get_terrain_type(c)) for c in cells]
    fp["board.terrain_mult"] = [bm.get_terrain_multiplier(c) for c in cells]
    fp["board.disallowed"] = sorted((c.col, c.row) for c in bm.disallowed_cells)
    fp["board.explored"] = sorted((c.col, c.row) for c in bm.explored_cells())

    fp["engine"] = _canonical(json.loads(combat.snapshot_json()))

    fp["turn.loop"] = {
        "combat_active": bool(app.combat_active),
        "combat_paused": bool(app.combat_paused),
        "turn_idx": int(app.turn_idx), "round_num": int(app.round_num),
        "initiative": [(e.agent_idx, e.d20, e.modifier, e.total)
                       for e in app.initiative_order],
    }
    # The automated NPC's turn runs on the frame AFTER its turn starts (F-M6-4).
    fp["turn.npc_drive"] = int(app._npc_drive_idx)
    fp["turn.economy"] = (bool(app.action_used), bool(app.bonus_used),
                          int(app.attacks_remaining))
    return fp


def diff(before: dict, after: dict) -> dict:
    """{key: (before, after)} for every key whose value did not survive."""
    return {k: (before.get(k, "<absent>"), after.get(k, "<absent>"))
            for k in sorted(set(before) | set(after))
            if before.get(k, "<absent>") != after.get(k, "<absent>")}


# ─────────────────────────────────────────────────────────────────────────────
#  The save and the restore under test
# ─────────────────────────────────────────────────────────────────────────────

def _save(app) -> tuple[str, int]:
    """The autosave ring (M6.4): one slot written at the turn boundary the scene stops on.
    The runner turns the per-turn hook off, so the slot is written here, explicitly."""
    k = autosave.save(app)
    assert k is not None, "the autosave wrote nothing"
    return app._save_path, k


def _restore(saved: tuple[str, int]):
    """A fresh App, pointed at the same encounter the way a relaunched DM's is, then the
    slot restored into it."""
    path, k = saved
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(path)
    assert autosave.restore(app, k), "the autosave restore refused"
    return app


def _dm_save(app, raw=False) -> str:
    """The DM's encounter save (which writes the combat sidecar, with its
    board snapshot, and the session) plus the terrain file. `raw` keeps summons and
    tombstones at their index (D-M6-2), as the autosave will; the plain scene keeps the
    DM's own compacted save, so the DM's save and load stay under test too."""
    app._save_agents(raw=raw)
    app._save_terrain()
    return app._save_path


def _dm_restore(path: str):
    app = App(MAP_PATH, seed=SEED)
    app._on_load_path_chosen(path)
    return app


# ─────────────────────────────────────────────────────────────────────────────
#  Scenes
# ─────────────────────────────────────────────────────────────────────────────

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


def _spell(app, name):
    from helpers import _dict_to_spell
    return _dict_to_spell(app.all_spells[app.spell_name_to_idx[name]])


def _caster(app, name, cls, level, spell):
    i = _idx(app, name)
    s = app.combat.get_agent_stats(app.bm, i)
    s.set_class_level(cls, level)
    s.initialize_class_resources(cls, level)
    s.restore_spell_slots()
    app.combat.set_agent_stats(app.bm, i, s)
    app.combat.set_agent_spells(app.bm, i, [_spell(app, spell)])
    return i


def _cast(app, caster, at, to=None):
    act = rpg.SpellAction()
    act.caster_idx = caster
    act.spell_idx = 0
    act.target_indices = []
    act.aoe_col, act.aoe_row = at
    act.aoe_col2, act.aoe_row2 = to or at
    res = app.combat.execute_spell(app.bm, act)
    app._flush_combat_log()
    assert res.valid, f"the cast at {at} was refused"
    return res


def _spawn(app, name, cell, summoner):
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size = name, cell[0], cell[1], 1
    cfg.sprite_path = ""
    idx = app.bm.spawn_agent(cfg)
    assert idx >= 0, f"spawn_agent refused {name} at {cell}"
    app.bm.set_agent_summoner_idx(idx, summoner)
    return idx


def _fight(tmpdir, *, hard):
    """Four creatures and a running fight. `hard` adds the summons, the spells, the
    door and the automated NPC, and leaves that NPC on turn."""
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "oracle_agents.json"))
    for name, col, row in (("Aria", 2, 3), ("Brannor", 2, 5),
                           ("Gnasher", 8, 3), ("Skarn", 8, 8)):
        _place(app, name, col, row)
    app.combat.apply_agent_configs(app.bm)
    for name in ("Aria", "Brannor"):
        app.bm.set_agent_faction(_idx(app, name), PC_FACTION)
    for name in ("Gnasher", "Skarn"):
        app.bm.set_agent_faction(_idx(app, name), FOE_FACTION)
    if hard:
        app.bm.set_agent_npc_automated(_idx(app, "Gnasher"), True)
        app.bm.add_door(cells=[rpg.Cell(5, 1)])

    app._start_combat()
    if not hard:
        _advance_to(app, lambda i: app.bm.placed_agents[i].faction == PC_FACTION)
        return app

    aria = _caster(app, "Aria", rpg.CharacterClass.Wizard, 9, "Wall of Fire")
    brannor = _caster(app, "Brannor", rpg.CharacterClass.Wizard, 9, "Darkness")
    _cast(app, aria, (6, 6), (9, 6))
    _cast(app, brannor, (2, 9))
    _spawn(app, "Wolf", (3, 3), aria)
    imp = _spawn(app, "Imp", (3, 5), brannor)
    app.bm.set_agent_removed_from_play(imp, True)       # a dismissed summon: a tombstone
    # A DM-placed terrain effect: difficult ground with a duration, no caster.
    app.bm.place_terrain_effect("Rubble", [rpg.Cell(4, 8), rpg.Cell(5, 8)],
                                rpg.TerrainDifficulty.Halved, 5, -1)
    door = app.bm.doors[0]
    app.bm.open_door(door.id)

    gnasher = _idx(app, "Gnasher")
    _advance_to(app, lambda i: i == gnasher)
    assert app._npc_drive_idx == gnasher, "the automated NPC's turn is armed, not yet run"
    return app


def _advance_to(app, want):
    """End turns until `want(current agent)`; the frame loop never runs, so nothing an
    automated NPC would do happens in between."""
    for _ in range(2 * len(app.initiative_order) + 2):
        if want(app._current_agent_idx()):
            return
        app._advance_turn()
    raise AssertionError("never reached the wanted turn")


def _round_trip(hard, dm=False):
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=hard)
        before = fingerprint(app)
        assert fingerprint(app) == before, "the fingerprint itself is not stable"
        after = fingerprint(_dm_restore(_dm_save(app)) if dm else _restore(_save(app)))
        return before, after
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _paths(b, a, at=""):
    """The innermost places two dumps disagree, as dotted paths with both values."""
    if isinstance(b, dict) and isinstance(a, dict):
        out = []
        for k in sorted(set(b) | set(a)):
            if b.get(k, "<absent>") != a.get(k, "<absent>"):
                out += _paths(b.get(k, "<absent>"), a.get(k, "<absent>"), f"{at}.{k}")
        return out
    if isinstance(b, list) and isinstance(a, list) and len(b) == len(a):
        out = []
        for i, (x, y) in enumerate(zip(b, a)):
            if x != y:
                out += _paths(x, y, f"{at}[{i}]")
        return out
    return [(at or ".", b, a)]


def _report(gaps):
    for k, (b, a) in gaps.items():
        print(f"   {k}:")
        for path, x, y in _paths(b, a)[:12]:
            print(f"      {path}: {str(x)[:120]}  ->  {str(y)[:120]}")


# ─────────────────────────────────────────────────────────────────────────────
#  Tests
# ─────────────────────────────────────────────────────────────────────────────

def _ratchet(gaps, known, name):
    _report(gaps)
    new = sorted(set(gaps) - known)
    closed = sorted(known - set(gaps))
    assert not new, f"restore lost state not in {name}: {new}"
    assert not closed, f"these restore now; delete them from {name}: {closed}"


def test_plain_fight_gaps_are_exactly_the_known_ones():
    """The control: no summon, no effect, a PC on turn, so the resume itself runs."""
    before, after = _round_trip(hard=False)
    _ratchet(diff(before, after), KNOWN_PLAIN_GAPS, "KNOWN_PLAIN_GAPS")
    print(f"✅ test_plain_fight_gaps_are_exactly_the_known_ones "
          f"({len(KNOWN_PLAIN_GAPS)} known gaps)")


def test_plain_fight_survives_the_dm_save_and_load():
    """The control again, through the DM's own encounter save and Load: the board snapshot
    in `_combat.json` (M6.2) keeps that path whole too."""
    before, after = _round_trip(hard=False, dm=True)
    _ratchet(diff(before, after), KNOWN_PLAIN_GAPS, "KNOWN_PLAIN_GAPS")
    print("✅ test_plain_fight_survives_the_dm_save_and_load")


def test_hard_fight_gaps_are_exactly_the_known_ones():
    """The ratchet: every gap is listed, and every listed gap is still a gap."""
    before, after = _round_trip(hard=True)
    _ratchet(diff(before, after), KNOWN_GAPS, "KNOWN_GAPS")
    print(f"✅ test_hard_fight_gaps_are_exactly_the_known_ones ({len(KNOWN_GAPS)} known gaps)")


def test_resumed_actor_can_move():
    """F-M6-7's live half, in the DM's own save and load: the actor on turn must come back
    with the walk it had, and spend it. The sidecar carried the engine's copy of the budget
    but not the agent's own, which is the one a move spends, so the resumed actor read 0 ft
    and every move was refused."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=False)
        actor = app._current_agent_idx()
        had = app.bm.placed_agents[actor].walk_remaining
        assert had > 0, "the scene's actor has no walk to lose"
        app2 = _dm_restore(_dm_save(app))
        assert app2._current_agent_idx() == actor and app2.combat_active
        assert app2.bm.placed_agents[actor].walk_remaining == had, \
            f"resumed with {app2.bm.placed_agents[actor].walk_remaining} ft, not {had}"
        assert app2.move_remaining_walk == had, "the panel's copy must agree"

        start = app2.bm.placed_agents[actor].origin
        dest = rpg.Cell(start.col + 1, start.row)
        app2.combat.begin_move(app2.bm, actor, dest, rpg.MovementType.Walk)
        moved = app2.bm.placed_agents[actor].origin
        assert (moved.col, moved.row) == (dest.col, dest.row), \
            f"the resumed actor could not take one step: still at {(moved.col, moved.row)}"

        # Exhaustion lives in the condition flags and the budget is stored raw (the board
        # snapshot, M6.2): an exhausted actor must come back with what it had, not its
        # exhaustion's worth more or less.
        cond = app.combat.get_agent_conditions(app.bm, actor)
        cond.exhaustion_level = 2
        app.combat.set_agent_conditions(app.bm, actor, cond)
        tired = app.bm.placed_agents[actor].walk_remaining
        assert tired == had - 10, (tired, had)
        app3 = _dm_restore(_dm_save(app))
        assert app3.bm.placed_agents[actor].walk_remaining == tired, \
            f"an exhausted actor resumed with {app3.bm.placed_agents[actor].walk_remaining} ft, not {tired}"
        print("✅ test_resumed_actor_can_move")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_hard_scene_has_what_it_claims():
    """The scene is only hard if it holds every hard part; guard it against a changed
    spell or map quietly emptying it."""
    tmp = tempfile.mkdtemp()
    try:
        app = _fight(tmp, hard=True)
        bm = app.bm
        assert any(pt.summoner_idx >= 0 and not pt.removed_from_play for pt in bm.placed_agents)
        assert any(pt.removed_from_play for pt in bm.placed_agents)
        assert len(bm.active_spell_effects) > 0, "Wall of Fire placed no spell effect"
        assert len(bm.active_light_effects) > 0, "Darkness placed no light effect"
        assert len(bm.active_terrain_effects) > 0, "no terrain effect on the board"
        assert any(d.open for d in bm.doors)
        assert bm.is_agent_npc_automated(app._current_agent_idx())
        print("✅ test_hard_scene_has_what_it_claims")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [test_hard_scene_has_what_it_claims, test_resumed_actor_can_move, test_plain_fight_gaps_are_exactly_the_known_ones,
             test_plain_fight_survives_the_dm_save_and_load,
             test_hard_fight_gaps_are_exactly_the_known_ones]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
