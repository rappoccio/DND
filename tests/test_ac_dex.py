"""
Phase 4 (LIVE_PLAY_BUGFIX_PLAN.md) — AC / persistence quick wins.

L42 — DEX modifier layering into AC.
    `base_ac` carries two conventions:
      · PCs (is_npc == False): base_ac is the PRE-DEX armor base entered in the GUI
        stat dialog; calculateAC layers DEX (+ armor/shield/feats) on top.
      · NPCs (is_npc == True): base_ac is the FINAL published AC (DEX already folded in);
        calculateAC must NOT re-add DEX or it double-counts.
    The weapon-attack path (resolveAttack) now reads calculateAC — previously it read
    raw base_ac, so a PC's DEX never reached the to-hit comparison.

L40 — current spell-slot state round-trips through save/reload
    (restore_class_resources overrides the freshly-initialised max with the saved
    spell_slots_cur).
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import rpg_battle_map as rpg
from test_helpers import setup_battle_map, setup_combat_engine
from test_feats import _place, _mk_weapon, _three


# ─────────────────────────────────────────────────────────────────────────────
#  L42 — DEX layering (PC) vs final-AC (NPC)
# ─────────────────────────────────────────────────────────────────────────────

def _set(engine, bm, idx, **kw):
    s = engine.get_agent_stats(bm, idx)
    for k, v in kw.items():
        setattr(s, k, v)
    engine.set_agent_stats(bm, idx, s)


def test_pc_dex_layered_into_ac():
    """PC (is_npc False): AC = pre-DEX base + DEX mod. 11 + (16-10)/2 = 14."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Rogue", 5, 5)
    _set(engine, bm, a, is_npc=False, base_ac=11, dex=16)
    assert engine.calculate_ac(bm, a) == 14, \
        f"PC DEX should layer onto base_ac (expected 14, got {engine.calculate_ac(bm, a)})"
    print("✅ test_pc_dex_layered_into_ac")


def test_pc_negative_dex_lowers_ac():
    """A DEX penalty also reaches AC: base 12 + (8-10)/2 = 11."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Clumsy", 5, 5)
    _set(engine, bm, a, is_npc=False, base_ac=12, dex=8)
    assert engine.calculate_ac(bm, a) == 11, \
        f"negative DEX should lower AC (expected 11, got {engine.calculate_ac(bm, a)})"
    print("✅ test_pc_negative_dex_lowers_ac")


def test_npc_ac_is_final_no_dex_readd():
    """NPC (is_npc True): base_ac is the published final AC; DEX is NOT re-added."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Aeromancer", 5, 5)
    _set(engine, bm, a, is_npc=True, base_ac=14, dex=15)   # published AC 14, +2 DEX baked in
    assert engine.calculate_ac(bm, a) == 14, \
        f"NPC AC must stay the published value (expected 14, got {engine.calculate_ac(bm, a)})"
    print("✅ test_npc_ac_is_final_no_dex_readd")


def test_temp_mods_apply_to_pc_and_npc():
    """ac_temporary_modifications (Shield spell, acid) apply regardless of is_npc."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    pc  = _place(engine, bm, "Wiz",   5, 5)
    npc = _place(engine, bm, "Ghoul", 7, 5)
    _set(engine, bm, pc,  is_npc=False, base_ac=10, dex=10, ac_temporary_modifications=5)  # Shield
    _set(engine, bm, npc, is_npc=True,  base_ac=12, dex=10, ac_temporary_modifications=5)
    assert engine.calculate_ac(bm, pc)  == 15, "PC temp mod (+5 Shield) should apply"
    assert engine.calculate_ac(bm, npc) == 17, "NPC temp mod should apply on top of final AC"
    print("✅ test_temp_mods_apply_to_pc_and_npc")


# ─────────────────────────────────────────────────────────────────────────────
#  L42 — the effective AC now reaches the weapon to-hit comparison (resolveAttack)
# ─────────────────────────────────────────────────────────────────────────────

def _attack_once(engine, bm, a, t):
    """Run one weapon attack and return the AttackResult (records target_ac hit or miss)."""
    return engine.execute_action(bm, rpg.Attack(a, t, 0))


def test_pc_dex_reaches_weapon_attack():
    """resolveAttack targets calculateAC: a PC's DEX raises the AC the attacker rolls against."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Orc",   5, 5)
    t = _place(engine, bm, "Rogue", 6, 5)   # adjacent
    engine.set_agent_weapons(bm, a, _three([_mk_weapon("Axe")]))
    _set(engine, bm, a, str=14)
    _set(engine, bm, t, is_npc=False, base_ac=11, dex=16, hp_max=200, hp_cur=200)
    r = _attack_once(engine, bm, a, t)
    assert r.target_ac == 14, \
        f"weapon attack should roll vs the DEX-layered AC (expected 14, got {r.target_ac})"
    print("✅ test_pc_dex_reaches_weapon_attack")


def test_npc_final_ac_used_in_weapon_attack():
    """An NPC target's published AC is used as-is (no DEX double-count) on the to-hit roll."""
    bm = setup_battle_map(); engine = setup_combat_engine()
    a = _place(engine, bm, "Fighter", 5, 5)
    t = _place(engine, bm, "Golem",   6, 5)
    engine.set_agent_weapons(bm, a, _three([_mk_weapon("Sword")]))
    _set(engine, bm, a, str=14)
    _set(engine, bm, t, is_npc=True, base_ac=17, dex=20, hp_max=200, hp_cur=200)  # +5 DEX baked in
    r = _attack_once(engine, bm, a, t)
    assert r.target_ac == 17, \
        f"NPC target AC must be the published 17 (got {r.target_ac})"
    print("✅ test_npc_final_ac_used_in_weapon_attack")


# ─────────────────────────────────────────────────────────────────────────────
#  L40 — current spell-slot state survives save → reload
# ─────────────────────────────────────────────────────────────────────────────

def test_spell_slots_current_roundtrip():
    """restore_class_resources overrides the freshly-initialised max with saved spell_slots_cur."""
    from agent_loader import dict_to_stats, restore_class_resources

    # A level-5 Wizard has 4/3/2 first/second/third slots at full. Simulate a mid-combat state
    # where some have been spent, exactly as main.py's save block writes it (agent-level key).
    spent = [1, 3, 0, 0, 0, 0, 0, 0, 0]   # 1 of 4 L1 left, 3 of 3 L2 left, 0 of 2 L3 left
    agent = {
        "stats": {"is_npc": False, "spellcasting_ability": "intel"},
        "agent_class_levels": {"Wizard": 5},
        "spell_slots_cur": spent,
    }
    s = dict_to_stats(agent["stats"])
    restore_class_resources(s, agent)
    got = list(s.spell_slots_remaining)
    assert got == spent, f"saved spell slots should be restored verbatim (expected {spent}, got {got})"
    # And the max is still the class-derived full complement (not clobbered to the spent values).
    assert list(s.spell_slots_max)[0] >= 4, \
        f"spell_slots_max should remain the class maximum (got {list(s.spell_slots_max)})"
    print("✅ test_spell_slots_current_roundtrip")


def test_spell_slots_absent_defaults_to_max():
    """With no saved spell_slots_cur (fresh spawn), slots initialise to the class maximum."""
    from agent_loader import dict_to_stats, restore_class_resources
    agent = {
        "stats": {"is_npc": False, "spellcasting_ability": "intel"},
        "agent_class_levels": {"Wizard": 5},
    }
    s = dict_to_stats(agent["stats"])
    restore_class_resources(s, agent)
    assert list(s.spell_slots_remaining) == list(s.spell_slots_max), \
        "absent spell_slots_cur should leave slots at full"
    print("✅ test_spell_slots_absent_defaults_to_max")


if __name__ == "__main__":
    test_pc_dex_layered_into_ac()
    test_pc_negative_dex_lowers_ac()
    test_npc_ac_is_final_no_dex_readd()
    test_temp_mods_apply_to_pc_and_npc()
    test_pc_dex_reaches_weapon_attack()
    test_npc_final_ac_used_in_weapon_attack()
    test_spell_slots_current_roundtrip()
    test_spell_slots_absent_defaults_to_max()
    print("\n✅ All AC/DEX + spell-slot round-trip tests passed")
