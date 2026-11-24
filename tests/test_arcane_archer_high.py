#!/usr/bin/env python3
"""
Arcane Archer Indomitable Teleport (L15) and Masterful Shots (L18) (ARCANE_ARCHER_PLAN.md AA5).

Masterful Shots — a Reaction when a creature the archer can see misses it with an attack roll:
  · gates: L18, the Reaction, a Ranged weapon, a seen attacker            (test_masterful_gates)
  · legal cells: its own (no move), or on foot within half Speed,
    unoccupied, farther from the attacker                                  (test_masterful_destinations)
  · the engine's cell: in range, as far away as it can get                 (test_masterful_engine_cell)
  · GUI: a miss parks an AfterAttack window; the auto option moves and
    shoots back, spending the Reaction; a hit opens nothing               (test_masterful_window_*)
  · GUI: a picked cell, and Skip                                           (test_masterful_pick_and_skip)
  · auto: the decider takes it inline                                      (test_masterful_inline_decider)

Indomitable Teleport — after an Indomitable reroll succeeds, teleport up to 60 ft:
  · GUI: the success parks an AfterSave window; the picked cell is
    reached, an illegal one refused                                         (test_indomitable_teleport_window)
  · not offered below L15                                                  (test_indomitable_teleport_needs_l15)
  · the destination test (60 ft, unoccupied, not its own cell)            (test_indomitable_teleport_destinations)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle


def _bow():
    w = rpg.Weapon()
    w.name = "Longbow"
    w.type = rpg.WeaponType.Ranged
    w.proficient = True
    w.range_short_feet = 150
    w.range_long_feet = 600
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Piercing
    roll.num_dice = 1
    roll.die_size = 8
    w.physical_damage_types = [roll]
    return w


def _club():
    w = rpg.Weapon()
    w.name = "Club"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    roll = rpg.PhysicalDamageRoll()
    roll.type = rpg.PhysicalDamage.Bludgeoning
    roll.num_dice = 1
    roll.die_size = 4
    w.physical_damage_types = [roll]
    return w


def _make_archer(engine, bm, idx, level):
    s = engine.get_agent_stats(bm, idx)
    s.dex = 20
    s.intel = 16
    s.wis = 10
    s.save_prof_wis = False
    s.hp_max = s.hp_cur = 200
    s.base_ac = 100                      # only a natural 20 hits it
    s.speed_walk = 30
    s.set_class_level(rpg.CharacterClass.Fighter, level)
    s.fighter_subclass = rpg.FighterSubclass.ArcaneArcher
    s.initialize_multiclass_resources()
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [_bow(), rpg.Weapon(), rpg.Weapon()])


def _scene(level=18):
    """A 36×36 open grid: Archer (10,10), Orc adjacent at (11,10) with a club, AC 1, 500 HP."""
    bm = setup_battle_map()
    bm.set_uniform_grid(bm.cell_pixel_size // 3, 0, 0)
    bm.detect_walls()
    engine = setup_combat_engine()
    arc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 10, 10))
    orc = add_agent_to_battle(engine, bm, create_test_agent("Orc", 11, 10))
    bm.set_agent_faction(arc, 1)
    bm.set_agent_faction(orc, 2)
    _make_archer(engine, bm, arc, level)
    t = engine.get_agent_stats(bm, orc)
    t.hp_max = t.hp_cur = 500
    t.base_ac = 1
    engine.set_agent_stats(bm, orc, t)
    engine.set_agent_weapons(bm, orc, [_club(), rpg.Weapon(), rpg.Weapon()])
    return bm, engine, arc, orc


def _option(ctx, feature):
    return next(i for i, o in enumerate(ctx.options) if o.feature == feature)


def _skip(ctx):
    return next(i for i, o in enumerate(ctx.options) if o.kind == rpg.ReactionOptionKind.Skip)


def _refresh(engine, bm, arc, at=(10, 10)):
    bm.set_agent_position(arc, rpg.Cell(*at))
    c = engine.get_agent_conditions(bm, arc)
    c.reaction_used = False
    engine.set_agent_conditions(bm, arc, c)


def _miss_parks(engine, bm, arc, orc):
    """begin_attack by the orc until it misses (and the window parks); returns the parked ctx."""
    for _ in range(60):
        _refresh(engine, bm, arc)
        status = engine.begin_attack(bm, rpg.Attack(orc, arc, 0))
        if engine.last_attack_result().hit:
            assert status == rpg.FlowStatus.Completed, "a hit opens no Masterful Shots window"
            continue
        assert status == rpg.FlowStatus.AwaitingDecision, "a miss parks the window"
        pd = engine.pending_decision()
        assert pd.ctx.window == rpg.ReactionWindow.AfterAttack
        assert (pd.ctx.reactor_idx, pd.ctx.source_idx) == (arc, orc)
        return pd.ctx
    raise AssertionError("the orc never missed")


def _orc_hp(engine, bm, orc):
    return engine.get_agent_stats(bm, orc).hp_cur


def test_masterful_gates():
    bm, engine, arc, orc = _scene(level=17)
    assert not engine.can_masterful_shots(bm, arc, orc), "Masterful Shots is L18"
    bm, engine, arc, orc = _scene()
    assert engine.can_masterful_shots(bm, arc, orc)
    c = engine.get_agent_conditions(bm, arc); c.reaction_used = True; engine.set_agent_conditions(bm, arc, c)
    assert not engine.can_masterful_shots(bm, arc, orc), "needs the Reaction"
    bm, engine, arc, orc = _scene()
    engine.set_agent_weapons(bm, arc, [_club(), rpg.Weapon(), rpg.Weapon()])
    assert not engine.can_masterful_shots(bm, arc, orc), "needs a Ranged weapon"
    bm, engine, arc, orc = _scene()
    assert not engine.can_masterful_shots(bm, arc, arc), "not against itself"
    print("✅ test_masterful_gates")


def test_masterful_destinations():
    bm, engine, arc, orc = _scene()
    ok = lambda c, r: engine.is_masterful_shots_destination(bm, arc, orc, rpg.Cell(c, r))
    assert ok(10, 10), "its own cell: shoot without moving"
    assert ok(7, 10), "15 ft straight away (half of 30 ft)"
    assert not ok(6, 10), "20 ft is beyond half Speed"
    assert not ok(10, 11), "sideways is not away (still adjacent)"
    assert not ok(11, 10), "occupied (and toward it)"
    c = engine.get_agent_conditions(bm, arc); c.grappled = True; engine.set_agent_conditions(bm, arc, c)
    assert not ok(8, 10) and ok(10, 10), "Speed 0: only shooting in place"
    print("✅ test_masterful_destinations")


def test_masterful_engine_cell():
    bm, engine, arc, orc = _scene()
    d = engine.masterful_shots_destination(bm, arc, orc)
    assert engine.is_masterful_shots_destination(bm, arc, orc, d)
    assert (d.col, d.row) != (10, 10), "it moves"
    orc_o = bm.placed_agents[orc].origin
    dist = max(abs(d.col - orc_o.col), abs(d.row - orc_o.row))
    assert dist == 4, f"as far as half Speed allows (3 squares away from adjacent), got {dist}"
    assert engine.masterful_shots_weapon(bm, arc, orc, d) == 0, "the bow still reaches"
    print("✅ test_masterful_engine_cell")


def test_masterful_window_moves_and_shoots():
    bm, engine, arc, orc = _scene()
    ctx = _miss_parks(engine, bm, arc, orc)
    expect = engine.masterful_shots_destination(bm, arc, orc)
    hp0 = _orc_hp(engine, bm, orc)
    resp = rpg.ReactionResponse(); resp.option = _option(ctx, "MasterfulShots")
    assert engine.submit_decision(bm, resp) == rpg.FlowStatus.Completed
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (expect.col, expect.row), "moved to the engine's cell"
    assert engine.get_agent_conditions(bm, arc).reaction_used, "spends the Reaction"
    assert not engine.last_attack_result().hit, "the orc's attack result is unchanged"
    # The orc is AC 1, so the shot back hits unless it rolls a natural 1.
    for _ in range(30):
        if _orc_hp(engine, bm, orc) < hp0:
            break
        # a natural 1: shoot again through a fresh window
        ctx = _miss_parks(engine, bm, arc, orc)
        resp = rpg.ReactionResponse(); resp.option = _option(ctx, "MasterfulShots")
        engine.submit_decision(bm, resp)
    assert _orc_hp(engine, bm, orc) < hp0, "the shot back damaged the orc"
    print("✅ test_masterful_window_moves_and_shoots")


def test_masterful_pick_and_skip():
    bm, engine, arc, orc = _scene()
    ctx = _miss_parks(engine, bm, arc, orc)
    resp = rpg.ReactionResponse(); resp.option = _option(ctx, "MasterfulShotsPick")
    resp.cell_col, resp.cell_row = 8, 10
    engine.submit_decision(bm, resp)
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (8, 10), (at.col, at.row)
    assert engine.get_agent_conditions(bm, arc).reaction_used

    # An illegal picked cell is refused: no move, no Reaction spent.
    ctx = _miss_parks(engine, bm, arc, orc)
    resp = rpg.ReactionResponse(); resp.option = _option(ctx, "MasterfulShotsPick")
    resp.cell_col, resp.cell_row = 2, 10
    engine.submit_decision(bm, resp)
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (10, 10) and not engine.get_agent_conditions(bm, arc).reaction_used

    ctx = _miss_parks(engine, bm, arc, orc)
    hp0 = _orc_hp(engine, bm, orc)
    resp = rpg.ReactionResponse(); resp.option = _skip(ctx)
    assert engine.submit_decision(bm, resp) == rpg.FlowStatus.Completed
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (10, 10) and _orc_hp(engine, bm, orc) == hp0
    assert not engine.get_agent_conditions(bm, arc).reaction_used, "Skip spends nothing"
    print("✅ test_masterful_pick_and_skip")


def test_masterful_not_below_l18():
    bm, engine, arc, orc = _scene(level=17)
    for _ in range(40):
        status = engine.begin_attack(bm, rpg.Attack(orc, arc, 0))
        assert status == rpg.FlowStatus.Completed, "no window below L18"
    print("✅ test_masterful_not_below_l18")


class _TakeAll(rpg.CombatDecider):
    def __init__(self):
        super().__init__()
        self.windows = []

    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        resp = rpg.ReactionResponse(); resp.option = -1
        for i, o in enumerate(ctx.options):
            if o.kind == rpg.ReactionOptionKind.Feature:
                resp.option = i
                break
        return resp


def test_masterful_inline_decider():
    bm, engine, arc, orc = _scene()
    dec = _TakeAll(); engine.set_decider(dec)
    try:
        for _ in range(60):
            _refresh(engine, bm, arc)
            expect = engine.masterful_shots_destination(bm, arc, orc)
            r = engine.execute_action(bm, rpg.Attack(orc, arc, 0))
            if not r.hit:
                break
        else:
            raise AssertionError("the orc never missed")
    finally:
        engine.set_decider(None)
    assert rpg.ReactionWindow.AfterAttack in dec.windows
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (expect.col, expect.row)
    assert engine.get_agent_conditions(bm, arc).reaction_used
    print("✅ test_masterful_inline_decider")


# ── Indomitable Teleport ──────────────────────────────────────────────────────
def _cause_fear():
    sp = rpg.Spell(); sp.name = "Cause Fear"; sp.level = 1
    sp.attack_type = rpg.SpellAttack.Save
    sp.save_ability = rpg.SaveAbility.SaveWis
    sp.geometry = rpg.SpellGeometry.Single
    c = rpg.AttackCondition()
    c.condition_name = "Frightened"; c.requires_save = True
    c.save_ability = rpg.SaveAbility.SaveWis; c.condition_duration = 10
    sp.conditions = [c]
    return sp


def _cast_scene(level=15):
    """Caster (5,5) with DC 15 Cause Fear; the archer at (6,5) saves WIS at +0, so its first save
    often fails and an Indomitable reroll (+15) always succeeds."""
    bm = setup_battle_map()
    bm.set_uniform_grid(bm.cell_pixel_size // 3, 0, 0)
    bm.detect_walls()
    engine = setup_combat_engine()
    caster = add_agent_to_battle(engine, bm, create_test_agent("Caster", 5, 5))
    arc = add_agent_to_battle(engine, bm, create_test_agent("Archer", 6, 5))
    s = engine.get_agent_stats(bm, caster)
    s.cha = 18; s.prof_bonus = 3; s.spellcasting_ability = 5
    s.hp_max = s.hp_cur = 40
    engine.set_agent_stats(bm, caster, s)
    engine.set_agent_spells(bm, caster, [_cause_fear()])
    _make_archer(engine, bm, arc, level)
    return bm, engine, caster, arc


def _reset_cast(engine, bm, caster, arc):
    s = engine.get_agent_stats(bm, caster); s.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, caster, s)
    a = engine.get_agent_stats(bm, arc)
    a.resources["Indomitable"].current = a.resources["Indomitable"].max
    engine.set_agent_stats(bm, arc, a)
    c = engine.get_agent_conditions(bm, arc); c.frightened = False; c.reaction_used = False
    engine.set_agent_conditions(bm, arc, c)
    bm.set_agent_position(arc, rpg.Cell(6, 5))


def _indomitable_parks(engine, bm, caster, arc):
    """begin_cast until the archer's save fails and the OnSaveFail window parks; take Indomitable."""
    for _ in range(400):
        _reset_cast(engine, bm, caster, arc)
        a = rpg.SpellAction(); a.caster_idx = caster; a.spell_idx = 0; a.target_indices = [arc]
        if engine.begin_cast(bm, a) != rpg.FlowStatus.AwaitingDecision:
            continue
        ctx = engine.pending_decision().ctx
        assert ctx.window == rpg.ReactionWindow.OnSaveFail
        resp = rpg.ReactionResponse(); resp.option = _option(ctx, "Indomitable")
        return engine.submit_decision(bm, resp)
    raise AssertionError("the archer never failed the save")


def test_indomitable_teleport_window():
    bm, engine, caster, arc = _cast_scene()
    status = _indomitable_parks(engine, bm, caster, arc)
    assert status == rpg.FlowStatus.AwaitingDecision, "a successful Indomitable owes the teleport"
    pd = engine.pending_decision()
    assert pd.ctx.window == rpg.ReactionWindow.AfterSave and pd.ctx.reactor_idx == arc
    resp = rpg.ReactionResponse(); resp.option = _option(pd.ctx, "IndomitableTeleportPick")
    resp.cell_col, resp.cell_row = 16, 5                     # 50 ft away
    assert engine.submit_decision(bm, resp) == rpg.FlowStatus.Completed
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (16, 5), (at.col, at.row)
    assert engine.last_cast_result().target_results[0].saved, "the rescued save stands"
    assert not engine.get_agent_conditions(bm, arc).frightened
    assert not engine.get_agent_conditions(bm, arc).reaction_used, "no Reaction spent"

    # Skip (stay put), and an illegal cell (beyond 60 ft) also stays put.
    for col, use_skip in ((6, True), (30, False)):
        status = _indomitable_parks(engine, bm, caster, arc)
        ctx = engine.pending_decision().ctx
        resp = rpg.ReactionResponse()
        if use_skip:
            resp.option = _skip(ctx)
        else:
            resp.option = _option(ctx, "IndomitableTeleportPick")
            resp.cell_col, resp.cell_row = col, 5
        assert engine.submit_decision(bm, resp) == rpg.FlowStatus.Completed
        at = bm.placed_agents[arc].origin
        assert (at.col, at.row) == (6, 5), (col, at.col, at.row)
    print("✅ test_indomitable_teleport_window")


def test_indomitable_teleport_needs_l15():
    bm, engine, caster, arc = _cast_scene(level=14)
    assert not engine.can_indomitable_teleport(bm, arc)
    status = _indomitable_parks(engine, bm, caster, arc)
    assert status == rpg.FlowStatus.Completed, "below L15 the cast just resolves"
    print("✅ test_indomitable_teleport_needs_l15")


def test_indomitable_teleport_destinations():
    bm, engine, caster, arc = _cast_scene()
    ok = lambda c, r: engine.is_indomitable_teleport_destination(bm, arc, rpg.Cell(c, r))
    assert ok(18, 5), "60 ft"
    assert not ok(19, 5), "65 ft"
    assert not ok(5, 5), "occupied"
    assert not ok(6, 5), "its own cell"
    assert not engine.apply_indomitable_teleport(bm, arc, 19, 5)
    assert engine.apply_indomitable_teleport(bm, arc, 18, 5)
    at = bm.placed_agents[arc].origin
    assert (at.col, at.row) == (18, 5)
    print("✅ test_indomitable_teleport_destinations")


if __name__ == "__main__":
    test_masterful_gates()
    test_masterful_destinations()
    test_masterful_engine_cell()
    test_masterful_window_moves_and_shoots()
    test_masterful_pick_and_skip()
    test_masterful_not_below_l18()
    test_masterful_inline_decider()
    test_indomitable_teleport_window()
    test_indomitable_teleport_needs_l15()
    test_indomitable_teleport_destinations()
    print("\nAll Arcane Archer L15/L18 tests passed ✅")
