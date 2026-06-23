#!/usr/bin/env python3
"""
Test suite for the OnD20Seen reaction window on ATTACK ROLLS.

After an attack roll is seen, a nearby creature (within 60 ft + LoS, reaction free) may LOWER it:
  · Bend Luck     (L6+ Wild Magic Sorcerer)  — spend 1 Sorcery Point, -1d4
  · Cutting Words (L3+ College of Lore Bard) — spend 1 Bardic Inspiration use, -Bardic die
  · Silvery Barbs (1st-level reaction spell)  — spend a L1+ slot, force the attacker to reroll the d20
v1 is "lowering-only": the sole outcome change is hit → miss (never miss → hit), so the apply path
mirrors Shield (no post-hoc damage roll). The window runs BEFORE the OnHit Shield window.

Auto/RL tests drive execute_action with a scripted CombatDecider; GUI tests drive begin_attack →
pending_decision → submit_decision with NO decider installed (the path main.py uses). Because the d20
is random, tests use the repo's retry-loop idiom.
"""

import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import rpg_battle_map as rpg
from test_helpers import (setup_battle_map, setup_combat_engine,
                          create_test_agent, add_agent_to_battle)


class D20Decider(rpg.CombatDecider):
    """At an OnD20Seen window, pick the option whose feature == `feature` (None → always Skip).
    Records every window seen and counts OnD20Seen offers."""
    def __init__(self, feature):
        super().__init__()
        self.feature = feature
        self.windows = []
        self.d20_offers = 0
    def choose_reaction(self, ctx):
        self.windows.append(ctx.window)
        resp = rpg.ReactionResponse(); resp.option = -1
        if ctx.window == rpg.ReactionWindow.OnD20Seen:
            self.d20_offers += 1
            if self.feature:
                for i, o in enumerate(ctx.options):
                    if o.kind == rpg.ReactionOptionKind.Feature and o.feature == self.feature:
                        resp.option = i
                        break
        return resp


def _silvery_barbs_spell():
    sp = rpg.Spell(); sp.name = "Silvery Barbs"; sp.level = 1
    sp.geometry = rpg.SpellGeometry.Single
    return sp


def _greataxe():
    w = rpg.Weapon(); w.name = "Greataxe"; w.type = rpg.WeaponType.Melee; w.reach_ft = 5
    pr = rpg.PhysicalDamageRoll(); pr.type = rpg.PhysicalDamage.Slashing; pr.num_dice = 1; pr.die_size = 12
    w.physical_damage_types = [pr]
    return w


# ── Reactor builders (configure an already-placed agent) ──────────────────────
def _make_lore_bard(engine, bm, idx, level=5, cha=16):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Bard, level)
    s.cha = cha; s.prof_bonus = 3
    s.bard_subclass = rpg.BardCollege.Lore       # before init so the college gates apply
    s.initialize_class_resources(rpg.CharacterClass.Bard, level)
    s.hp_max = 30; s.hp_cur = 30
    engine.set_agent_stats(bm, idx, s)


def _make_wild_sorc(engine, bm, idx, level=6, cha=16):
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Sorcerer, level)
    s.cha = cha; s.prof_bonus = 3
    s.sorcerer_subclass = rpg.SorcererSubclass.WildMagic
    s.initialize_class_resources(rpg.CharacterClass.Sorcerer, level)
    s.hp_max = 30; s.hp_cur = 30
    engine.set_agent_stats(bm, idx, s)


def _make_silvery_caster(engine, bm, idx, slots=2):
    """Any creature that KNOWS Silvery Barbs and has a L1+ slot can use it (class-agnostic)."""
    engine.set_agent_spells(bm, idx, [_silvery_barbs_spell()])
    s = engine.get_agent_stats(bm, idx)
    s.spell_slots_remaining = [slots, 0, 0, 0, 0, 0, 0, 0, 0]
    s.hp_max = 30; s.hp_cur = 30
    engine.set_agent_stats(bm, idx, s)


def _make_light_cleric(engine, bm, idx, level=5, wis=16):
    """Light Domain Cleric (L3+): Warding Flare = WIS-mod (min 1) reaction uses / long rest."""
    s = engine.get_agent_stats(bm, idx)
    s.set_class_level(rpg.CharacterClass.Cleric, level)
    s.wis = wis; s.prof_bonus = 3
    s.cleric_subclass = rpg.ClericSubclass.LightDomain   # before init so the resource is seeded
    s.initialize_class_resources(rpg.CharacterClass.Cleric, level)
    s.hp_max = 30; s.hp_cur = 30
    engine.set_agent_stats(bm, idx, s)


def _setup(engine, bm, make_reactor, *, tgt_ac=13, give_shield=False):
    """Attacker (STR 18, +7 to hit) at (5,5); defender at (6,5); reactor at (5,7) (≈10 ft, clear LoS).
    add_agent_to_battle's apply_agent_configs wipes earlier stats, so configure all AFTER every add."""
    atk = add_agent_to_battle(engine, bm, create_test_agent("Atk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Def", 6, 5))
    rea = add_agent_to_battle(engine, bm, create_test_agent("Rea", 5, 7))

    a = engine.get_agent_stats(bm, atk)
    a.str = 18; a.prof_bonus = 3; a.hp_max = 30; a.hp_cur = 30
    engine.set_agent_stats(bm, atk, a)
    engine.set_agent_weapons(bm, atk, [_greataxe(), rpg.Weapon(), rpg.Weapon()])

    t = engine.get_agent_stats(bm, tgt)
    t.base_ac = tgt_ac; t.hp_max = 60; t.hp_cur = 60
    if give_shield:
        t.spell_slots_remaining = [2, 0, 0, 0, 0, 0, 0, 0, 0]
    engine.set_agent_stats(bm, tgt, t)
    if give_shield:
        sp = rpg.Spell(); sp.name = "Shield"; sp.level = 1; sp.geometry = rpg.SpellGeometry.Single
        engine.set_agent_spells(bm, tgt, [sp])

    make_reactor(engine, bm, rea)

    # Teams: defender + reactor are allies (team 1), attacker is the enemy (team 2). Warding Flare is
    # team-gated, so the reactor must share a team with the target it is shielding.
    bm.set_agent_faction(atk, 2)
    bm.set_agent_faction(tgt, 1)
    bm.set_agent_faction(rea, 1)
    return atk, tgt, rea


def _reset(engine, bm, tgt, rea, make_reactor):
    """Independent attempts: refill the defender's HP, re-init the reactor's resources, clear reactions."""
    t = engine.get_agent_stats(bm, tgt); t.hp_cur = t.hp_max
    engine.set_agent_stats(bm, tgt, t)
    tc = engine.get_agent_conditions(bm, tgt); tc.reaction_used = False
    engine.set_agent_conditions(bm, tgt, tc)
    make_reactor(engine, bm, rea)
    rc = engine.get_agent_conditions(bm, rea); rc.reaction_used = False; rc.incapacitated = False
    engine.set_agent_conditions(bm, rea, rc)


def _hp(engine, bm, idx):  return engine.get_agent_stats(bm, idx).hp_cur
def _atk(engine, bm, a, t): return engine.execute_action(bm, rpg.Attack(a, t, 0))


# ── Auto/RL path ──────────────────────────────────────────────────────────────
def test_cutting_words_can_miss():
    """A Lore Bard's Cutting Words is offered on a hit; with a big enough die it flips it to a miss,
    spending one Bardic Inspiration + the reaction. No damage on a flipped miss."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_lore_bard)
    dec = D20Decider("CuttingWords"); engine.set_decider(dec)
    bi_max = engine.get_agent_stats(bm, rea).resources["Bardic Inspiration"].max
    saw_window = saw_miss = False
    for _ in range(300):
        _reset(engine, bm, tgt, rea, _make_lore_bard)
        before = dec.d20_offers
        r = _atk(engine, bm, atk, tgt)
        if dec.d20_offers > before:                    # the window opened (a non-crit hit)
            saw_window = True
            assert engine.get_agent_conditions(bm, rea).reaction_used, "Cutting Words spends the reaction"
            assert engine.get_agent_stats(bm, rea).resources["Bardic Inspiration"].current == bi_max - 1, \
                "Cutting Words spends one Bardic Inspiration use"
            if not r.hit:
                saw_miss = True
                assert _hp(engine, bm, tgt) == 60, "a Cutting-Words miss deals no damage"
        if saw_window and saw_miss:
            print("✅ test_cutting_words_can_miss passed")
            return
    assert False, "did not observe both a window and a flipped-to-miss case in 300 attacks"


def test_bend_luck_spends_sp_and_can_miss():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_wild_sorc)
    dec = D20Decider("BendLuck"); engine.set_decider(dec)
    sp_max = engine.get_agent_stats(bm, rea).resources["Sorcery Points"].current
    saw_window = saw_miss = False
    for _ in range(400):
        _reset(engine, bm, tgt, rea, _make_wild_sorc)
        before = dec.d20_offers
        r = _atk(engine, bm, atk, tgt)
        if dec.d20_offers > before:
            saw_window = True
            assert engine.get_agent_conditions(bm, rea).reaction_used, "Bend Luck spends the reaction"
            assert engine.get_agent_stats(bm, rea).resources["Sorcery Points"].current == sp_max - 1, \
                "Bend Luck spends one Sorcery Point"
            if not r.hit:
                saw_miss = True
                assert _hp(engine, bm, tgt) == 60, "a Bend-Luck miss deals no damage"
        if saw_window and saw_miss:
            print("✅ test_bend_luck_spends_sp_and_can_miss passed")
            return
    assert False, "did not observe both a window and a flipped-to-miss case in 400 attacks"


def test_silvery_barbs_reroll_can_miss():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_silvery_caster)
    dec = D20Decider("SilveryBarbs"); engine.set_decider(dec)
    saw_window = saw_miss = False
    for _ in range(400):
        _reset(engine, bm, tgt, rea, _make_silvery_caster)
        before = dec.d20_offers
        l1_before = engine.get_agent_stats(bm, rea).spell_slots_remaining[0]
        r = _atk(engine, bm, atk, tgt)
        if dec.d20_offers > before:
            saw_window = True
            assert engine.get_agent_conditions(bm, rea).reaction_used, "Silvery Barbs spends the reaction"
            assert engine.get_agent_stats(bm, rea).spell_slots_remaining[0] == l1_before - 1, \
                "Silvery Barbs spends one L1 slot"
            if not r.hit:
                saw_miss = True
                assert _hp(engine, bm, tgt) == 60, "a reroll-to-miss deals no damage"
        if saw_window and saw_miss:
            print("✅ test_silvery_barbs_reroll_can_miss passed")
            return
    assert False, "did not observe both a window and a reroll-to-miss case in 400 attacks"


def test_warding_flare_disadvantage_can_miss():
    """A Light Domain Cleric's Warding Flare is offered on a hit; imposing Disadvantage (reroll, take
    the lower) can flip the hit to a miss, spending one Warding Flare use + the reaction. No damage on
    a flipped miss."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_light_cleric)
    dec = D20Decider("WardingFlare"); engine.set_decider(dec)
    wf_max = engine.get_agent_stats(bm, rea).resources["Warding Flare"].max
    saw_window = saw_miss = False
    for _ in range(400):
        _reset(engine, bm, tgt, rea, _make_light_cleric)
        before = dec.d20_offers
        r = _atk(engine, bm, atk, tgt)
        if dec.d20_offers > before:                    # the window opened (a hit)
            saw_window = True
            assert engine.get_agent_conditions(bm, rea).reaction_used, "Warding Flare spends the reaction"
            assert engine.get_agent_stats(bm, rea).resources["Warding Flare"].current == wf_max - 1, \
                "Warding Flare spends one use"
            if not r.hit:
                saw_miss = True
                assert _hp(engine, bm, tgt) == 60, "a Warding-Flare miss deals no damage"
        if saw_window and saw_miss:
            print("✅ test_warding_flare_disadvantage_can_miss passed")
            return
    assert False, "did not observe both a window and a flipped-to-miss case in 400 attacks"


def test_warding_flare_gate():
    """Deterministic eligibility checks for can_warding_flare (30 ft, subclass, resource, reaction)."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Atk", 1, 1))
    near = add_agent_to_battle(engine, bm, create_test_agent("Near", 1, 3))   # 10 ft
    far  = add_agent_to_battle(engine, bm, create_test_agent("Far", 1, 9))    # 40 ft (>30, ≤60)
    _make_light_cleric(engine, bm, near)
    _make_light_cleric(engine, bm, far)

    assert engine.can_warding_flare(bm, near, atk, near), "in-range Light cleric with a use is eligible"
    assert not engine.can_warding_flare(bm, far, atk, far), "a cleric beyond 30 ft is NOT eligible"

    # Drain the resource → not eligible.
    s = engine.get_agent_stats(bm, near); s.resources["Warding Flare"].current = 0
    engine.set_agent_stats(bm, near, s)
    assert not engine.can_warding_flare(bm, near, atk, near), "no Warding Flare use → not eligible"

    # Refill but spend the reaction → not eligible.
    _make_light_cleric(engine, bm, near)
    c = engine.get_agent_conditions(bm, near); c.reaction_used = True
    engine.set_agent_conditions(bm, near, c)
    assert not engine.can_warding_flare(bm, near, atk, near), "reaction already spent → not eligible"

    # A non-Light cleric (Life Domain) is not eligible even in range with a free reaction.
    _make_light_cleric(engine, bm, near)
    c = engine.get_agent_conditions(bm, near); c.reaction_used = False
    engine.set_agent_conditions(bm, near, c)
    s = engine.get_agent_stats(bm, near); s.cleric_subclass = rpg.ClericSubclass.LifeDomain
    engine.set_agent_stats(bm, near, s)
    assert not engine.can_warding_flare(bm, near, atk, near), "non-Light Domain cleric → not eligible"
    print("✅ test_warding_flare_gate passed")


def test_warding_flare_team_gate():
    """Warding Flare only fires to protect the cleric's own team: an in-range, otherwise-eligible
    Light cleric may NOT shield an enemy or a neutral, only itself and its allies."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk  = add_agent_to_battle(engine, bm, create_test_agent("Atk", 1, 1))
    cler = add_agent_to_battle(engine, bm, create_test_agent("Cler", 1, 3))   # 10 ft
    ally = add_agent_to_battle(engine, bm, create_test_agent("Ally", 1, 5))   # 10 ft from cleric
    foe  = add_agent_to_battle(engine, bm, create_test_agent("Foe", 2, 3))    # 5 ft from cleric
    _make_light_cleric(engine, bm, cler)

    # Teams: cleric + ally on team 1; attacker + foe on team 2.
    bm.set_agent_faction(cler, 1); bm.set_agent_faction(ally, 1)
    bm.set_agent_faction(atk, 2);  bm.set_agent_faction(foe, 2)

    assert engine.can_warding_flare(bm, cler, atk, cler), "may protect itself"
    assert engine.can_warding_flare(bm, cler, atk, ally), "may protect a teammate"
    assert not engine.can_warding_flare(bm, cler, atk, foe), "must NOT shield an enemy"

    # A neutral (faction 0) is nobody's ally → not protected.
    bm.set_agent_faction(ally, 0)
    assert not engine.can_warding_flare(bm, cler, atk, ally), "must NOT shield a neutral non-ally"
    print("✅ test_warding_flare_team_gate passed")


def test_lowering_to_miss_suppresses_shield():
    """If Cutting Words turns the hit into a miss, the OnHit Shield window must not open afterwards."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_lore_bard, give_shield=True)
    dec = D20Decider("CuttingWords"); engine.set_decider(dec)
    for _ in range(400):
        _reset(engine, bm, tgt, rea, _make_lore_bard)
        before_d20 = dec.d20_offers
        n_before = len(dec.windows)
        r = _atk(engine, bm, atk, tgt)
        if dec.d20_offers > before_d20 and not r.hit:           # a window opened and flipped to a miss
            this_attack = dec.windows[n_before:]
            assert rpg.ReactionWindow.OnHit not in this_attack, \
                "a lowered-to-miss attack opens no Shield (OnHit) window"
            print("✅ test_lowering_to_miss_suppresses_shield passed")
            return
    assert False, "no Cutting-Words miss occurred to test Shield suppression in 400 attacks"


def test_reaction_used_not_offered():
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_lore_bard)
    dec = D20Decider("CuttingWords"); engine.set_decider(dec)
    saw_hit = False
    for _ in range(200):
        _reset(engine, bm, tgt, rea, _make_lore_bard)
        rc = engine.get_agent_conditions(bm, rea); rc.reaction_used = True   # reaction already spent
        engine.set_agent_conditions(bm, rea, rc)
        r = _atk(engine, bm, atk, tgt)
        if r.hit and not r.critical:
            saw_hit = True
    assert saw_hit, "expected at least one non-crit hit"
    assert dec.d20_offers == 0, "a reactor whose reaction is spent is never offered the window"
    print("✅ test_reaction_used_not_offered passed")


def test_no_resource_not_offered():
    """A Lore Bard with zero Bardic Inspiration uses is not offered Cutting Words."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_lore_bard)
    dec = D20Decider("CuttingWords"); engine.set_decider(dec)
    saw_hit = False
    for _ in range(200):
        _reset(engine, bm, tgt, rea, _make_lore_bard)
        s = engine.get_agent_stats(bm, rea)
        s.resources["Bardic Inspiration"].current = 0          # drain the resource
        engine.set_agent_stats(bm, rea, s)
        r = _atk(engine, bm, atk, tgt)
        if r.hit and not r.critical:
            saw_hit = True
    assert saw_hit, "expected at least one non-crit hit"
    assert dec.d20_offers == 0, "no Bardic Inspiration → no Cutting Words window"
    print("✅ test_no_resource_not_offered passed")


# ── GUI suspend/resume path (begin_attack → pending_decision → submit_decision; NO decider) ──
def _feat_opt(ctx, feature):
    return next(i for i, o in enumerate(ctx.options)
               if o.kind == rpg.ReactionOptionKind.Feature and o.feature == feature)

def _skip_opt(ctx):
    return next(i for i, o in enumerate(ctx.options) if o.kind == rpg.ReactionOptionKind.Skip)

def _submit(engine, bm, option):
    resp = rpg.ReactionResponse(); resp.option = option
    return engine.submit_decision(bm, resp)


def test_gui_suspend_cutting_words_negate():
    """begin_attack parks at the OnD20Seen window on a hit; submitting Cutting Words can flip to a miss."""
    bm = setup_battle_map(); engine = setup_combat_engine()    # no set_decider — GUI path
    atk, tgt, rea = _setup(engine, bm, _make_lore_bard)
    for _ in range(300):
        _reset(engine, bm, tgt, rea, _make_lore_bard)
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.AwaitingDecision:
            pd = engine.pending_decision()
            assert pd.active and pd.ctx.window == rpg.ReactionWindow.OnD20Seen
            assert pd.ctx.reactor_idx == rea and pd.ctx.source_idx == atk
            status = _submit(engine, bm, _feat_opt(pd.ctx, "CuttingWords"))
            # After the only reactor resolves there may still be a Shield window, but tgt has none here:
            assert status == rpg.FlowStatus.Completed and not engine.pending_decision().active
            assert engine.get_agent_conditions(bm, rea).reaction_used, "Cutting Words spent the reaction"
            r = engine.last_attack_result()
            if not r.hit:
                assert _hp(engine, bm, tgt) == 60, "a flipped-to-miss deals no damage"
            print("✅ test_gui_suspend_cutting_words_negate passed")
            return
    assert False, "no OnD20Seen window parked in 300 begin_attack calls"


def test_gui_suspend_skip_then_resolve():
    """Submitting Skip at the parked window spends nothing and the attack resolves normally."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk, tgt, rea = _setup(engine, bm, _make_lore_bard)
    for _ in range(300):
        _reset(engine, bm, tgt, rea, _make_lore_bard)
        bi_before = engine.get_agent_stats(bm, rea).resources["Bardic Inspiration"].current
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.AwaitingDecision:
            status = _submit(engine, bm, _skip_opt(engine.pending_decision().ctx))
            assert status == rpg.FlowStatus.Completed
            assert not engine.get_agent_conditions(bm, rea).reaction_used, "Skip spends no reaction"
            assert engine.get_agent_stats(bm, rea).resources["Bardic Inspiration"].current == bi_before, \
                "Skip spends no Bardic Inspiration"
            assert engine.last_attack_result().hit, "skipping the lowering window → the hit lands"
            print("✅ test_gui_suspend_skip_then_resolve passed")
            return
    assert False, "no OnD20Seen window parked in 300 begin_attack calls"


def test_gui_multi_reactor_cursor():
    """Two eligible reactors are offered in order; skipping the first advances to the second."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    atk = add_agent_to_battle(engine, bm, create_test_agent("Atk", 5, 5))
    tgt = add_agent_to_battle(engine, bm, create_test_agent("Def", 6, 5))
    rea1 = add_agent_to_battle(engine, bm, create_test_agent("Bard", 5, 7))
    rea2 = add_agent_to_battle(engine, bm, create_test_agent("Sorc", 5, 8))
    a = engine.get_agent_stats(bm, atk); a.str = 18; a.prof_bonus = 3; engine.set_agent_stats(bm, atk, a)
    engine.set_agent_weapons(bm, atk, [_greataxe(), rpg.Weapon(), rpg.Weapon()])
    t = engine.get_agent_stats(bm, tgt); t.base_ac = 13; t.hp_max = 60; t.hp_cur = 60
    engine.set_agent_stats(bm, tgt, t)
    _make_lore_bard(engine, bm, rea1)
    _make_wild_sorc(engine, bm, rea2)

    def reset_both():
        tc = engine.get_agent_conditions(bm, tgt); tc.reaction_used = False
        engine.set_agent_conditions(bm, tgt, tc)
        _make_lore_bard(engine, bm, rea1); _make_wild_sorc(engine, bm, rea2)
        for r in (rea1, rea2):
            c = engine.get_agent_conditions(bm, r); c.reaction_used = False; c.incapacitated = False
            engine.set_agent_conditions(bm, r, c)

    for _ in range(300):
        reset_both()
        status = engine.begin_attack(bm, rpg.Attack(atk, tgt, 0))
        if status == rpg.FlowStatus.AwaitingDecision:
            seen = []
            while status == rpg.FlowStatus.AwaitingDecision:
                ctx = engine.pending_decision().ctx
                if ctx.window != rpg.ReactionWindow.OnD20Seen:
                    break                                  # (no Shield here; defensive)
                seen.append(ctx.reactor_idx)
                status = _submit(engine, bm, _skip_opt(ctx))
            assert seen == [rea1, rea2], f"both reactors offered in index order, got {seen}"
            print("✅ test_gui_multi_reactor_cursor passed")
            return
    assert False, "no OnD20Seen window parked in 300 begin_attack calls"


def run_all():
    test_cutting_words_can_miss()
    test_bend_luck_spends_sp_and_can_miss()
    test_silvery_barbs_reroll_can_miss()
    test_warding_flare_disadvantage_can_miss()
    test_warding_flare_gate()
    test_warding_flare_team_gate()
    test_lowering_to_miss_suppresses_shield()
    test_reaction_used_not_offered()
    test_no_resource_not_offered()
    test_gui_suspend_cutting_words_negate()
    test_gui_suspend_skip_then_resolve()
    test_gui_multi_reactor_cursor()
    print("\nAll OnD20Seen (Bend Luck / Cutting Words / Silvery Barbs) tests passed ✅")


if __name__ == "__main__":
    run_all()
