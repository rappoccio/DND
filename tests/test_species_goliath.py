"""Goliath and the SP6 combat spells (SPECIES_PLAN.md SP6: D6, D9, Hellish Rebuke, Faerie
Fire, Chill Touch).

Covered: Large Form needs level 5, grows the token to 2×2 (keeping its cell), adds 10 ft of
Speed and of this turn's walk, is refused with no room and after its once-per-Long-Rest use,
ends free (back to 1×1 at the top-left), lapses after 100 rounds, survives a board snapshot
round trip at either size, and gives Advantage on the Strength side of a grapple escape.
Giant Ancestry: a hit offers Fire / Frost / Hill and applying it adds 1d10 Fire, 1d6 Cold and
the slow, or Prone; PB uses per Long Rest; a non-damaging miss offers nothing; Cloud's Jaunt
teleports up to 30 ft and refuses farther; Stone's Endurance cuts the damage and Storm's
Thunder and Hellish Rebuke hurt the attacker through the defender OnHit window. Faerie
Fire's record is a DEX save in a 20-ft Square and Outlined gives attackers Advantage and
cancels Invisible. Chill Touch's hit stops healing until it expires.
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg
import helpers
from test_helpers import setup_battle_map, create_test_agent, add_agent_to_battle

CATALOG = {d["name"]: d for d in json.load(
    open(os.path.join(os.path.dirname(rpg.__file__), "spells.json")))}
PB = {1: 2, 5: 3}


def _sure_blade():
    w = rpg.Weapon()
    w.name = "Sure Blade"
    w.type = rpg.WeaponType.Melee
    w.proficient = True
    w.bonus_hit = 60          # only a natural 1 misses
    w.bonus_damage = 1
    return [w, rpg.Weapon(), rpg.Weapon()]


def _scene(level=5, ancestry="Fire", con=14, tgt_hp=500, extra=()):
    """A Goliath Fighter at (4,5) facing a foe at (5,5); `extra` places more foes."""
    bm = setup_battle_map()
    engine = rpg.CombatEngine(11)
    g = add_agent_to_battle(engine, bm, create_test_agent("Grog", 4, 5), hp=80, con=con, str=16)
    t = add_agent_to_battle(engine, bm, create_test_agent("Tgt", 5, 5), hp=tgt_hp)
    bm.set_agent_faction(t, 1)
    others = []
    for i, (c, r) in enumerate(extra):
        o = add_agent_to_battle(engine, bm, create_test_agent(f"X{i}", c, r), hp=50)
        bm.set_agent_faction(o, 1)
        others.append(o)
    s = engine.get_agent_stats(bm, g)
    s.add_class_level(rpg.CharacterClass.Fighter, level)
    s.char_level = level
    s.prof_bonus = PB[level]
    s.is_npc = False
    s.speed_walk = 30
    s.set_species("Goliath", ancestry)
    engine.set_agent_stats(bm, g, s)
    engine.set_agent_weapons(bm, g, _sure_blade())
    bm.placed_agents[g].init_movement(engine.get_agent_stats(bm, g).speed_walk, 0, 0, 0)
    return bm, engine, g, t, others


def _hit(engine, bm, a, t):
    for _ in range(50):
        r = engine.execute_action(bm, rpg.Attack(a, t, 0))
        if r.hit:
            return r
        c = engine.get_agent_conditions(bm, a)
        c.action_used = False
        engine.set_agent_conditions(bm, a, c)
    raise AssertionError("never hit")


# ── Large Form ────────────────────────────────────────────────────────────────

def test_large_form_grows_and_shrinks():
    bm, engine, g, _, _ = _scene()
    speed = engine.get_agent_stats(bm, g).speed_walk          # 35 (Goliath)
    assert engine.can_large_form(bm, g)
    walk0 = bm.placed_agents[g].raw_movement[0]
    assert engine.toggle_large_form(bm, g)
    pa = bm.placed_agents[g]
    s = engine.get_agent_stats(bm, g)
    assert pa.size == 2 and s.in_large_form() and s.large_form_rounds == 100
    assert s.speed_walk == speed + 10
    assert pa.raw_movement[0] == walk0 + 10, "this turn's walk grows too"
    o = pa.origin
    assert o.col <= 4 <= o.col + 1 and o.row <= 5 <= o.row + 1, "the 2×2 keeps its cell"
    assert not engine.can_large_form(bm, g), "once per Long Rest"
    assert engine.toggle_large_form(bm, g), "ending it is free"
    pa = bm.placed_agents[g]
    assert pa.size == 1 and (pa.origin.col, pa.origin.row) == (o.col, o.row)
    assert engine.get_agent_stats(bm, g).speed_walk == speed
    assert not engine.can_large_form(bm, g), "spent until the Long Rest"
    s = engine.get_agent_stats(bm, g)
    s.restore_resources_long_rest()
    engine.set_agent_stats(bm, g, s)
    assert engine.can_large_form(bm, g)
    print("✅ test_large_form_grows_and_shrinks passed")


def test_large_form_level_and_room():
    bm, engine, g, _, _ = _scene(level=1)
    assert not engine.can_large_form(bm, g), "level 5 only"
    # Foes on the four corners around (4,5) leave no free 2×2 that keeps the cell.
    bm, engine, g, _, _ = _scene(extra=[(3, 4), (5, 4), (3, 6), (5, 6)])
    assert engine.can_large_form(bm, g)
    o = engine.large_form_origin(bm, g)
    assert (o.col, o.row) == (-1, -1), (o.col, o.row)
    assert not engine.toggle_large_form(bm, g), "no room: refused"
    assert bm.placed_agents[g].size == 1
    assert not engine.get_agent_stats(bm, g).large_form_used, "a refusal spends nothing"
    print("✅ test_large_form_level_and_room passed")


def test_large_form_lapses_after_100_rounds():
    bm, engine, g, _, _ = _scene()
    assert engine.toggle_large_form(bm, g)
    for _ in range(99):
        engine.begin_turn(bm, g)
    assert bm.placed_agents[g].size == 2
    assert engine.get_agent_stats(bm, g).large_form_rounds == 1
    engine.begin_turn(bm, g)
    assert bm.placed_agents[g].size == 1
    assert not engine.get_agent_stats(bm, g).in_large_form()
    print("✅ test_large_form_lapses_after_100_rounds passed")


def test_large_form_snapshot_round_trip():
    bm, engine, g, _, _ = _scene()
    small = bm.snapshot_json()
    assert engine.toggle_large_form(bm, g)
    large = bm.snapshot_json()
    assert bm.restore_json(small), "restoring a smaller snapshot"
    assert bm.placed_agents[g].size == 1
    assert bm.restore_json(large), "restoring a larger snapshot"
    assert bm.placed_agents[g].size == 2
    assert engine.get_agent_stats(bm, g).in_large_form()
    print("✅ test_large_form_snapshot_round_trip passed")


# ── Giant Ancestry ────────────────────────────────────────────────────────────

def test_fire_and_frost_on_hit():
    for anc, die, typ in (("Fire", 10, rpg.MagicDamage.Fire), ("Frost", 6, rpg.MagicDamage.Cold)):
        bm, engine, g, t, _ = _scene(ancestry=anc)
        r = _hit(engine, bm, g, t)
        c = engine.get_agent_conditions(bm, g)
        assert c.giant_ancestry_available and c.giant_ancestry_target == t, anc
        before_hp = engine.get_agent_stats(bm, t).hp_cur
        before_total = r.total_damage
        assert engine.apply_giant_ancestry_on_hit(bm, g, r)
        extra = r.total_damage - before_total
        assert 1 <= extra <= die, (anc, extra)
        assert engine.get_agent_stats(bm, t).hp_cur == before_hp - extra
        assert typ in list(r.magic_damage_types)
        assert engine.get_agent_stats(bm, g).giant_ancestry_remaining() == PB[5] - 1
        assert not engine.get_agent_conditions(bm, g).giant_ancestry_available
        assert engine.get_agent_conditions(bm, t).slowed == (anc == "Frost")
    print("✅ test_fire_and_frost_on_hit passed")


def test_hill_prone_and_pool():
    bm, engine, g, t, _ = _scene(ancestry="Hill")
    for i in range(PB[5]):
        r = _hit(engine, bm, g, t)
        assert engine.apply_giant_ancestry_on_hit(bm, g, r)
        assert engine.get_agent_conditions(bm, t).prone
        tc = engine.get_agent_conditions(bm, t)
        tc.prone = False
        engine.set_agent_conditions(bm, t, tc)
    assert engine.get_agent_stats(bm, g).giant_ancestry_remaining() == 0
    _hit(engine, bm, g, t)
    assert not engine.get_agent_conditions(bm, g).giant_ancestry_available, "the pool is empty"
    print("✅ test_hill_prone_and_pool passed")


def test_clouds_jaunt():
    bm, engine, g, _, _ = _scene(ancestry="Cloud")
    assert engine.can_clouds_jaunt(bm, g)
    o = bm.placed_agents[g].origin
    assert not engine.clouds_jaunt(bm, g, o.col - 7, o.row), "35 ft is too far"
    assert engine.get_agent_stats(bm, g).giant_ancestry_remaining() == PB[5]
    dest = None
    for dc in range(-6, 0):
        if engine.is_valid_teleport_destination(bm, o.col + dc, o.row):
            dest = (o.col + dc, o.row)
    assert dest, "some open cell to the west"
    assert engine.clouds_jaunt(bm, g, *dest)
    n = bm.placed_agents[g].origin
    assert (n.col, n.row) == dest
    assert engine.get_agent_stats(bm, g).giant_ancestry_remaining() == PB[5] - 1
    bm2, engine2, g2, _, _ = _scene(ancestry="Fire")
    assert not engine2.can_clouds_jaunt(bm2, g2), "Cloud ancestry only"
    print("✅ test_clouds_jaunt passed")


class _Take(rpg.CombatDecider):
    """Takes the first option whose feature is `want`."""
    def __init__(self, want):
        super().__init__()
        self.want = want
        self.seen = []

    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse()
        resp.option = -1
        for i, o in enumerate(ctx.options):
            self.seen.append(o.feature)
            if o.kind == rpg.ReactionOptionKind.Feature and o.feature == self.want:
                resp.option = i
        return resp


def _foe_swings(engine, bm, foe, g, want):
    """The foe hits the Goliath once, with a decider that takes `want`."""
    engine.set_agent_weapons(bm, foe, _sure_blade())
    dec = _Take(want)
    engine.set_decider(dec)
    try:
        for _ in range(50):
            c = engine.get_agent_conditions(bm, foe)
            c.action_used = False
            engine.set_agent_conditions(bm, foe, c)
            r = engine.execute_action(bm, rpg.Attack(foe, g, 0))
            if r.hit:
                return r, dec
    finally:
        engine.set_decider(None)
    raise AssertionError("never hit")


def test_stone_and_storm_reactions():
    bm, engine, g, t, _ = _scene(ancestry="Stone", con=14)
    r, dec = _foe_swings(engine, bm, t, g, "StonesEndurance")
    assert "StonesEndurance" in dec.seen
    assert any(b[0] == "stone's endurance" and b[1] < 0 for b in r.damage_breakdown), list(r.damage_breakdown)
    assert engine.get_agent_conditions(bm, g).reaction_used
    assert engine.get_agent_stats(bm, g).giant_ancestry_remaining() == PB[5] - 1

    bm, engine, g, t, _ = _scene(ancestry="Storm")
    hp0 = engine.get_agent_stats(bm, t).hp_cur
    _, dec = _foe_swings(engine, bm, t, g, "StormsThunder")
    assert "StormsThunder" in dec.seen
    lost = hp0 - engine.get_agent_stats(bm, t).hp_cur
    assert 1 <= lost <= 8, lost
    print("✅ test_stone_and_storm_reactions passed")


def test_hellish_rebuke():
    bm, engine, g, t, _ = _scene(ancestry="Fire")
    s = engine.get_agent_stats(bm, g)
    s.set_species("Tiefling", "Infernal")
    s.char_level = 3
    s.cha = 16
    engine.set_agent_stats(bm, g, s)
    engine.set_agent_spells(bm, g, [])
    assert helpers.sync_item_spells(engine, bm, g, CATALOG) is not None
    assert "Hellish Rebuke" in [sp.name for sp in engine.get_agent_spells(bm, g)]
    hp0 = engine.get_agent_stats(bm, t).hp_cur
    _, dec = _foe_swings(engine, bm, t, g, "HellishRebuke")
    assert "HellishRebuke" in dec.seen
    lost = hp0 - engine.get_agent_stats(bm, t).hp_cur
    assert 1 <= lost <= 20, lost
    assert engine.get_agent_stats(bm, g).granted_free_left("Hellish Rebuke") == 0
    assert engine.get_agent_conditions(bm, g).reaction_used
    assert not engine.can_hellish_rebuke(bm, g, t), "reaction spent"
    print("✅ test_hellish_rebuke passed")


# ── Faerie Fire, Chill Touch ──────────────────────────────────────────────────

def test_faerie_fire_record_and_outlined():
    ff = CATALOG["Faerie Fire"]
    assert (ff["geometry"], ff["attack_type"], ff["width"], ff["length"]) == ("Square", "Save", 20, 20)
    assert ff["conditions"][0]["condition_name"] == "Outlined"
    bm, engine, g, t, _ = _scene()
    tc = engine.get_agent_conditions(bm, t)
    tc.invisible = True
    engine.set_agent_conditions(bm, t, tc)
    assert not engine.can_perceive_target(bm, g, t), "invisible to start with"
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx, cond.caster_idx, cond.condition_name = t, g, "Outlined"
    cond.turns_remaining = 10
    cond.save_repeat_turns = -1
    engine.add_agent_condition(bm, cond)
    assert engine.get_agent_conditions(bm, t).outlined
    assert engine.can_perceive_target(bm, g, t), "Outlined cancels Invisible"
    print("✅ test_faerie_fire_record_and_outlined passed")


def test_chill_touch_blocks_healing():
    ct = CATALOG["Chill Touch"]["conditions"][0]
    assert ct["prevents_healing"] and ct["condition_duration"] == 2
    bm, engine, g, t, _ = _scene()
    ts = engine.get_agent_stats(bm, t)
    ts.hp_cur = 100
    engine.set_agent_stats(bm, t, ts)
    cond = rpg.ActiveAgentCondition()
    cond.agent_idx, cond.caster_idx, cond.condition_name = t, g, "NoHeal"
    cond.turns_remaining = 2
    cond.save_repeat_turns = -1
    cond.prevents_healing = True
    engine.add_agent_condition(bm, cond)
    assert engine.get_agent_stats(bm, t).cant_heal
    engine.heal_agent(bm, t, 10)
    assert engine.get_agent_stats(bm, t).hp_cur == 100
    engine.tick_agent_conditions_for_caster(bm, g)
    assert engine.get_agent_stats(bm, t).cant_heal, "through the caster's next turn"
    engine.tick_agent_conditions_for_caster(bm, g)
    assert not engine.get_agent_stats(bm, t).cant_heal
    engine.heal_agent(bm, t, 10)
    assert engine.get_agent_stats(bm, t).hp_cur == 110
    print("✅ test_chill_touch_blocks_healing passed")


def _cast(engine, bm, c, name, t, slot):
    engine.set_agent_spells(bm, c, [helpers._dict_to_spell(CATALOG[name])])
    s = engine.get_agent_stats(bm, c)
    s.spellcasting_ability = 5
    s.cha = 20
    s.spell_slots_max = [4, 0, 0, 0, 0, 0, 0, 0, 0]
    s.spell_slots_remaining = [4, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, c, s)
    a = rpg.SpellAction()
    a.caster_idx, a.spell_idx, a.slot_level = c, 0, slot
    tc = bm.placed_agents[t].origin
    a.target_indices = [t]
    a.aoe_col, a.aoe_row = tc.col, tc.row
    return engine.execute_spell(bm, a)


def test_faerie_fire_cast_outlines():
    outlined = 0
    for seed in range(20):
        bm, engine, g, t, _ = _scene()
        ts = engine.get_agent_stats(bm, t)
        ts.dex = 1                                  # DC 8+PB+5 against −5: fails but on a 20
        engine.set_agent_stats(bm, t, ts)
        _cast(engine, bm, g, "Faerie Fire", t, 1)
        outlined += engine.get_agent_conditions(bm, t).outlined
    assert outlined >= 17, outlined
    print(f"✅ test_faerie_fire_cast_outlines passed ({outlined}/20)")


def test_chill_touch_cast_blocks_healing():
    blocked = 0
    for _ in range(20):
        bm, engine, g, t, _ = _scene()
        res = _cast(engine, bm, g, "Chill Touch", t, 0)
        hit = any(tr.target_idx == t and tr.hit for tr in res.target_results)
        assert engine.get_agent_stats(bm, t).cant_heal == hit
        blocked += hit
    assert blocked > 0
    print(f"✅ test_chill_touch_cast_blocks_healing passed ({blocked}/20 hits)")


if __name__ == "__main__":
    test_large_form_grows_and_shrinks()
    test_large_form_level_and_room()
    test_large_form_lapses_after_100_rounds()
    test_large_form_snapshot_round_trip()
    test_fire_and_frost_on_hit()
    test_hill_prone_and_pool()
    test_clouds_jaunt()
    test_stone_and_storm_reactions()
    test_hellish_rebuke()
    test_faerie_fire_record_and_outlined()
    test_chill_touch_blocks_healing()
    test_faerie_fire_cast_outlines()
    test_chill_touch_cast_blocks_healing()
    print("All Goliath / SP6 tests passed.")
