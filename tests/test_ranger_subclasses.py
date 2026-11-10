#!/usr/bin/env python3
"""
Ranger subclasses — the gap-closing phases of plans/RANGER_SUBCLASSES_PLAN.md.

R1 — Hunter (D10):
  · Horde Breaker arms on making a weapon attack, hit OR miss, only on the Hunter's own turn,
    remembering the original target and weapon.
  · horde_breaker_targets: within 5 ft of the original target, not it, not attacked this turn,
    in reach of the armed weapon; empty once used.
  · The NpcDriver takes the extra attack after its attack loop (automated Hunters).
  · Superior Hunter's Defense: Resistance to the triggering damage type until the end of the
    current turn (cleared as the next turn begins).
  · Hunter's Lore: marking a creature logs its immunities / resistances / vulnerabilities.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine, create_test_agent, add_agent_to_battle

SLASHING = 2   # PhysicalDamage_t::Slashing
FIRE     = 2   # MagicDamage_t::Fire


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _place(engine, bm, name, col, row, faction=0):
    idx = add_agent_to_battle(engine, bm, create_test_agent(name, col, row))
    if faction:
        bm.set_agent_faction(idx, faction)
    return idx


def _weapon(name="Sword", bonus_hit=50, bonus_damage=0):
    w = rpg.Weapon()
    w.name = name
    w.type = rpg.WeaponType.Melee
    w.reach_ft = 5
    w.range_short_feet = 5
    w.range_long_feet = 5
    w.proficient = True
    w.bonus_hit = bonus_hit
    w.bonus_damage = bonus_damage
    pr = rpg.PhysicalDamageRoll()
    pr.type = rpg.PhysicalDamage.Slashing
    pr.num_dice = 1
    pr.die_size = 6
    w.physical_damage_types = [pr]
    return w


def _hp(engine, bm, idx, hp=400, ac=10):
    s = engine.get_agent_stats(bm, idx)
    s.hp_max = hp
    s.hp_cur = hp
    s.base_ac = ac
    engine.set_agent_stats(bm, idx, s)


def _make_hunter(engine, bm, idx, level, prey=None, weapon=None):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Ranger, level)
    s.ranger_subclass = rpg.RangerSubclass.Hunter
    if prey is not None:
        s.hunter_prey = prey
    s.str = 14
    s.prof_bonus = 2 + (level - 1) // 4
    s.hp_max = 200
    s.hp_cur = 200
    engine.set_agent_stats(bm, idx, s)
    engine.set_agent_weapons(bm, idx, [weapon or _weapon(), rpg.Weapon(), rpg.Weapon()])


def _attack(engine, bm, a, t):
    return engine.execute_action(bm, rpg.Attack(a, t, 0))


def _horde(engine, bm, a, level=3):
    _make_hunter(engine, bm, a, level, prey=rpg.HunterPrey.HordeBreaker)


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — Horde Breaker
# ─────────────────────────────────────────────────────────────────────────────

def test_horde_breaker_arms_on_a_miss():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t, ac=999)                         # every swing misses
    r = _attack(engine, bm, a, t)
    assert r.valid and not r.hit, "the attack should miss"
    c = engine.get_agent_conditions(bm, a)
    assert c.horde_breaker_available, "Horde Breaker triggers on making an attack — a miss counts"
    assert c.horde_breaker_origin == t and c.horde_breaker_weapon == 0
    assert t in list(c.attacked_this_turn)
    print("✅ test_horde_breaker_arms_on_a_miss")


def test_horde_breaker_only_on_own_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    engine.begin_turn(bm, t)                           # the quarry's turn: an OA-style swing
    _attack(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).horde_breaker_available, \
        "Horde Breaker is once on each of YOUR turns — not on another creature's"
    engine.begin_turn(bm, a)
    _attack(engine, bm, a, t)
    assert engine.get_agent_conditions(bm, a).horde_breaker_available, "armed on the Hunter's own turn"
    print("✅ test_horde_breaker_only_on_own_turn")


def test_horde_breaker_not_on_an_opportunity_attack():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    act = rpg.Attack(a, t, 0)
    act.opportunity = True
    engine.execute_action(bm, act)
    assert not engine.get_agent_conditions(bm, a).horde_breaker_available
    print("✅ test_horde_breaker_not_on_an_opportunity_attack")


def test_horde_breaker_targets():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a     = _place(engine, bm, "Hunter", 5, 5)
    t     = _place(engine, bm, "Quarry", 5, 6)
    near  = _place(engine, bm, "Near", 6, 6)           # within 5 ft of t AND in the Hunter's reach
    far   = _place(engine, bm, "Far", 9, 9)            # nowhere near t
    nbr_t = _place(engine, bm, "Behind", 5, 7)         # within 5 ft of t, out of the Hunter's reach
    _horde(engine, bm, a)
    for i in (t, near, far, nbr_t):
        _hp(engine, bm, i)
    assert list(engine.horde_breaker_targets(bm, a)) == [], "nothing before an attack arms it"
    _attack(engine, bm, a, t)
    assert list(engine.horde_breaker_targets(bm, a)) == [near], list(engine.horde_breaker_targets(bm, a))

    # A creature already attacked this turn is not eligible.
    c = engine.get_agent_conditions(bm, a)
    c.attacked_this_turn = list(c.attacked_this_turn) + [near]
    engine.set_agent_conditions(bm, a, c)
    assert list(engine.horde_breaker_targets(bm, a)) == []

    # Used → empty, even with a valid creature.
    c.attacked_this_turn = [t]
    c.horde_breaker_used = True
    engine.set_agent_conditions(bm, a, c)
    assert list(engine.horde_breaker_targets(bm, a)) == []
    print("✅ test_horde_breaker_targets")


def test_horde_breaker_used_does_not_rearm():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    c = engine.get_agent_conditions(bm, a)
    c.horde_breaker_used = True
    engine.set_agent_conditions(bm, a, c)
    _attack(engine, bm, a, t)
    assert not engine.get_agent_conditions(bm, a).horde_breaker_available
    print("✅ test_horde_breaker_used_does_not_rearm")


def test_horde_breaker_turn_reset():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Hunter", 5, 5)
    t = _place(engine, bm, "Quarry", 5, 6)
    _horde(engine, bm, a)
    _hp(engine, bm, t)
    _attack(engine, bm, a, t)
    engine.begin_turn(bm, a)
    c = engine.get_agent_conditions(bm, a)
    assert not c.horde_breaker_available and not c.horde_breaker_used
    assert c.horde_breaker_origin == -1 and list(c.attacked_this_turn) == []
    print("✅ test_horde_breaker_turn_reset")


def test_npc_driver_takes_horde_breaker():
    """An automated Hunter (L3, one attack) swings at its target, then takes the Horde Breaker
    extra attack against the other enemy standing next to that target."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a  = _place(engine, bm, "Hunter", 5, 5, faction=1)
    t1 = _place(engine, bm, "Goblin A", 5, 6, faction=2)
    t2 = _place(engine, bm, "Goblin B", 6, 6, faction=2)
    _horde(engine, bm, a)
    for i in (t1, t2):
        _hp(engine, bm, i, hp=300)
    engine.begin_turn(bm, a)
    status = engine.run_npc_turn(bm, a)
    assert status == rpg.FlowStatus.Completed, status
    c = engine.get_agent_conditions(bm, a)
    assert sorted(c.attacked_this_turn) == sorted([t1, t2]), \
        f"both goblins should have been attacked, got {list(c.attacked_this_turn)}"
    assert c.horde_breaker_used and not c.horde_breaker_available
    print("✅ test_npc_driver_takes_horde_breaker")


def test_npc_driver_no_horde_breaker_without_a_second_target():
    bm = setup_battle_map(); engine = setup_combat_engine()
    a  = _place(engine, bm, "Hunter", 5, 5, faction=1)
    t1 = _place(engine, bm, "Goblin A", 5, 6, faction=2)
    _horde(engine, bm, a)
    _hp(engine, bm, t1, hp=300)
    engine.begin_turn(bm, a)
    engine.run_npc_turn(bm, a)
    c = engine.get_agent_conditions(bm, a)
    assert list(c.attacked_this_turn) == [t1] and not c.horde_breaker_used
    print("✅ test_npc_driver_no_horde_breaker_without_a_second_target")


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — Superior Hunter's Defense: Resistance until the end of the turn
# ─────────────────────────────────────────────────────────────────────────────

class _SHDOnce(rpg.CombatDecider):
    def __init__(self):
        super().__init__()
        self.taken = 0
    def choose_reaction(self, ctx):
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnHit:
            for i, o in enumerate(ctx.options):
                if o.kind == rpg.ReactionOptionKind.Feature and o.feature == "SuperiorHuntersDefense":
                    resp.option = i
                    self.taken += 1
                    break
        return resp


def _land(engine, bm, a, t, tries=40):
    for _ in range(tries):
        r = _attack(engine, bm, a, t)
        if r.hit:
            return r
    raise AssertionError("attack never landed")


def test_superior_hunters_defense_lasts_the_turn():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk    = _place(engine, bm, "Brute", 5, 5)
    hunter = _place(engine, bm, "Hunter", 6, 5)
    engine.set_agent_weapons(bm, atk, [_weapon(bonus_damage=100), rpg.Weapon(), rpg.Weapon()])
    _make_hunter(engine, bm, hunter, 15)
    _hp(engine, bm, hunter, hp=2000)

    dec = _SHDOnce(); engine.set_decider(dec)
    engine.begin_turn(bm, atk)
    _land(engine, bm, atk, hunter)
    assert dec.taken == 1, "the Hunter takes Superior Hunter's Defense on the first hit"
    c = engine.get_agent_conditions(bm, hunter)
    assert c.shd_resist_physical_mask & (1 << SLASHING), "Slashing is resisted for the rest of the turn"

    # Same turn, reaction spent: the next Slashing hit is still halved by the Resistance.
    r2 = _land(engine, bm, atk, hunter)
    assert dec.taken == 1, "no second reaction"
    assert r2.total_damage <= (106 + 2) // 2 + 1, f"second hit should be resisted, dealt {r2.total_damage}"

    # The next turn begins → the Resistance is gone.
    engine.begin_turn(bm, hunter)
    c = engine.get_agent_conditions(bm, hunter)
    assert c.shd_resist_physical_mask == 0 and c.shd_resist_magic_mask == 0
    c.reaction_used = True                              # keep the reaction out of the next hit
    engine.set_agent_conditions(bm, hunter, c)
    r3 = _land(engine, bm, atk, hunter)
    assert r3.total_damage >= 100, f"no Resistance once the turn has ended, dealt {r3.total_damage}"
    engine.set_decider(None)
    print("✅ test_superior_hunters_defense_lasts_the_turn")


# ─────────────────────────────────────────────────────────────────────────────
#  R1 — Hunter's Lore
# ─────────────────────────────────────────────────────────────────────────────

def _hunters_mark_spell():
    sp = rpg.Spell()
    sp.name = "Hunter's Mark"
    sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    sp.attack_type = rpg.SpellAttack.Automatic
    sp.range = 90
    sp.duration = 1
    sp.requires_concentration = True
    return sp


def _mark(engine, bm, ranger, quarry):
    engine.set_agent_spells(bm, ranger, [_hunters_mark_spell()])
    rs = engine.get_agent_stats(bm, ranger)
    rs.spell_slots_remaining = [9, 0, 0, 0, 0, 0, 0, 0, 0]
    rs.spellcasting_ability = 4
    engine.set_agent_stats(bm, ranger, rs)
    action = rpg.SpellAction()
    action.caster_idx = ranger
    action.spell_idx = 0
    action.target_indices = [quarry]
    engine.resolve_cast(bm, action)


def test_hunters_lore_logs_the_quarry():
    bm = setup_battle_map(); engine = setup_combat_engine()
    logger = rpg.MessageLogger(); engine.set_logger(logger)
    ranger = _place(engine, bm, "Ranger", 5, 5)
    quarry = _place(engine, bm, "Quarry", 6, 5)
    _make_hunter(engine, bm, ranger, 3)
    qs = engine.get_agent_stats(bm, quarry)
    pm = list(qs.physical_damage_multipliers); pm[SLASHING] = 0.5
    mm = list(qs.magic_damage_multipliers); mm[FIRE] = 0.0; mm[7] = 2.0   # Fire immune, Psychic vuln
    qs.physical_damage_multipliers = pm
    qs.magic_damage_multipliers = mm
    engine.set_agent_stats(bm, quarry, qs)
    logger.flush()
    _mark(engine, bm, ranger, quarry)
    lore = [ln for ln in logger.flush() if "Hunter's Lore" in ln]
    assert len(lore) == 1, lore
    assert "Immunities: Fire" in lore[0] and "Resistances: Slashing" in lore[0] \
        and "Vulnerabilities: Psychic" in lore[0], lore[0]
    print("✅ test_hunters_lore_logs_the_quarry")


def test_hunters_lore_not_for_other_rangers():
    bm = setup_battle_map(); engine = setup_combat_engine()
    logger = rpg.MessageLogger(); engine.set_logger(logger)
    ranger = _place(engine, bm, "Ranger", 5, 5)
    quarry = _place(engine, bm, "Quarry", 6, 5)
    s = engine.get_agent_stats(bm, ranger)
    s.set_class_level(rpg.CharacterClass.Ranger, 5)
    s.ranger_subclass = rpg.RangerSubclass.GloomStalker
    engine.set_agent_stats(bm, ranger, s)
    logger.flush()
    _mark(engine, bm, ranger, quarry)
    assert not [ln for ln in logger.flush() if "Hunter's Lore" in ln]
    print("✅ test_hunters_lore_not_for_other_rangers")


# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\n🎉 All {len(fns)} Ranger subclass tests passed")


if __name__ == "__main__":
    run_all()
