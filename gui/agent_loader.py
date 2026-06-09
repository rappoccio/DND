"""
Shared agent loading utilities for main.py and replay.py

Provides functions to load agent configurations, stats, weapons, etc. from JSON
without code duplication between the main GUI and the combat replay system.
"""

import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    import rpg_battle_map as rpg
except ImportError:
    print("ERROR: rpg_battle_map module not found. Run cmake to build it first.")
    sys.exit(1)

from helpers import _dict_to_weapon, _dict_to_armor


def dict_to_stats(stats_dict):
    """Convert a dictionary to rpg.Stats object."""
    stats = rpg.Stats()
    stats.str = int(stats_dict.get("str", 10))
    stats.dex = int(stats_dict.get("dex", 10))
    stats.con = int(stats_dict.get("con", 10))
    stats.intel = int(stats_dict.get("intel", 10))
    stats.wis = int(stats_dict.get("wis", 10))
    stats.cha = int(stats_dict.get("cha", 10))
    stats.hp_max = int(stats_dict.get("hp_max", 10))
    stats.hp_cur = int(stats_dict.get("hp_cur", stats.hp_max))
    stats.base_ac = int(stats_dict.get("ac", 10))
    stats.speed_walk = int(stats_dict.get("speed_walk", 30))
    stats.speed_fly = int(stats_dict.get("speed_fly", 0))
    stats.speed_swim = int(stats_dict.get("speed_swim", 0))
    stats.speed_burrow = int(stats_dict.get("speed_burrow", 0))
    stats.prof_bonus = int(stats_dict.get("prof_bonus", 2))
    stats.num_attacks = int(stats_dict.get("num_attacks", 1))
    stats.weapon_mastery = int(stats_dict.get("weapon_mastery", 0))
    stats.is_npc = bool(stats_dict.get("is_npc", False))
    stats.has_sentinel = bool(stats_dict.get("has_sentinel", False))
    stats.has_branches_of_the_tree = bool(stats_dict.get("has_branches_of_the_tree", False))
    stats.save_prof_str = bool(stats_dict.get("save_prof_str", False))
    stats.save_prof_dex = bool(stats_dict.get("save_prof_dex", False))
    stats.save_prof_con = bool(stats_dict.get("save_prof_con", False))
    stats.save_prof_intel = bool(stats_dict.get("save_prof_intel", False))
    stats.save_prof_wis = bool(stats_dict.get("save_prof_wis", False))
    stats.save_prof_cha = bool(stats_dict.get("save_prof_cha", False))
    if "spellcasting_ability" in stats_dict:
        ability_val = stats_dict["spellcasting_ability"]
        if isinstance(ability_val, str):
            ability_map = {"str": 0, "dex": 1, "con": 2, "intel": 3, "wis": 4, "cha": 5}
            stats.spellcasting_ability = ability_map.get(ability_val, 5)
        else:
            stats.spellcasting_ability = int(ability_val) if ability_val else 5
    stats.temp_hp = int(stats_dict.get("temp_hp", 0))
    return stats


MAGIC_DAMAGE_NAMES = ["Acid", "Cold", "Fire", "Force", "Lightning",
                      "Necrotic", "Poison", "Psychic", "Radiant", "Thunder"]
PHYSICAL_DAMAGE_NAMES = ["Bludgeoning", "Piercing", "Slashing"]


def apply_damage_multipliers(stats, stats_dict):
    """Apply resist/immune/vuln damage multipliers from a stats dict onto a
    Stats object. Resistance=0.5, immunity=0.0, vulnerability=2.0; everything
    else stays 1.0. Shared by JSON agent loading and monster auto-population."""
    for idx in range(len(MAGIC_DAMAGE_NAMES)):
        stats.set_magic_damage_multiplier(idx, 1.0)
    for idx in range(len(PHYSICAL_DAMAGE_NAMES)):
        stats.set_physical_damage_multiplier(idx, 1.0)

    for names, mult, key in (
        (MAGIC_DAMAGE_NAMES, 0.5, "magic_resistances"),
        (MAGIC_DAMAGE_NAMES, 0.0, "magic_immunities"),
        (MAGIC_DAMAGE_NAMES, 2.0, "magic_vulnerabilities"),
    ):
        for entry in stats_dict.get(key, []):
            if entry in names:
                stats.set_magic_damage_multiplier(names.index(entry), mult)
    for names, mult, key in (
        (PHYSICAL_DAMAGE_NAMES, 0.5, "physical_resistances"),
        (PHYSICAL_DAMAGE_NAMES, 0.0, "physical_immunities"),
        (PHYSICAL_DAMAGE_NAMES, 2.0, "physical_vulnerabilities"),
    ):
        for entry in stats_dict.get(key, []):
            if entry in names:
                stats.set_physical_damage_multiplier(names.index(entry), mult)


def restore_class_resources(stats, agent_dict, rpg_module=None):
    """Restore character class, subclass, and resources from a saved agent dict."""
    if rpg_module is None:
        rpg_module = rpg
    class_name = agent_dict.get("agent_class", "None")
    char_level = int(agent_dict.get("agent_char_level", 1))
    stats.set_class_level(getattr(rpg_module.CharacterClass, class_name), char_level)
    barb = agent_dict.get("agent_barbarian_subclass", "NONE")
    if barb != "NONE":
        stats.barbarian_subclass = getattr(rpg_module.BarbianSubclass, barb)
    wiz = agent_dict.get("agent_wizard_subclass", "NONE")
    if wiz != "NONE":
        stats.wizard_subclass = getattr(rpg_module.WizardSubclass, wiz)
    ftr = agent_dict.get("agent_fighter_subclass", "NONE")
    if ftr != "NONE":
        stats.fighter_subclass = getattr(rpg_module.FighterSubclass, ftr)
    drd = agent_dict.get("agent_druid_circle", "NONE")
    if drd != "NONE":
        stats.druid_circle = getattr(rpg_module.DruidCircle, drd)
    mnk = agent_dict.get("agent_monk_subclass", "NONE")
    if mnk != "NONE":
        stats.monk_subclass = getattr(rpg_module.MonkSubclass, mnk)
    pal = agent_dict.get("agent_paladin_oath", "NONE")
    if pal != "NONE":
        stats.paladin_oath = getattr(rpg_module.PaladinOath, pal)
    wlk = agent_dict.get("agent_warlock_subclass", "NONE")
    if wlk != "NONE":
        stats.warlock_subclass = getattr(rpg_module.WarlockSubclass, wlk)
    rog = agent_dict.get("agent_rogue_subclass", "NONE")
    if rog != "NONE":
        stats.rogue_subclass = getattr(rpg_module.RogueSubclass, rog)
    clr = agent_dict.get("agent_cleric_subclass", "NONE")
    if clr != "NONE":
        stats.cleric_subclass = getattr(rpg_module.ClericSubclass, clr)
    bard = agent_dict.get("agent_bard_subclass", "NONE")
    if bard != "NONE":
        stats.bard_subclass = getattr(rpg_module.BardCollege, bard)
    sorc = agent_dict.get("agent_sorcerer_subclass", "NONE")
    if sorc != "NONE":
        stats.sorcerer_subclass = getattr(rpg_module.SorcererSubclass, sorc)
    stats.eldritch_invocations = list(agent_dict.get("agent_eldritch_invocations", []))
    stats.fiendish_resilience_type = int(agent_dict.get("agent_fiendish_resilience_type", -1))
    stats.initialize_class_resources(getattr(rpg_module.CharacterClass, class_name), char_level)
    slots_cur = agent_dict.get("spell_slots_cur")
    if slots_cur:
        stats.spell_slots_remaining = list(slots_cur)


def load_agents_from_json(json_path, bm, combat, sprites_dir="sprites"):
    """
    Load all agent configurations from a JSON file into the battle map.

    Args:
        json_path: Path to the agents JSON file
        bm: BattleMap instance to populate
        combat: CombatEngine instance for setting stats/weapons
        sprites_dir: Directory for sprite paths (used by main.py, ignored by replay.py)

    Returns:
        True if successful, False if file not found or corrupted
    """
    if not os.path.exists(json_path):
        print(f"ERROR: Agents file not found: {json_path}")
        return False

    try:
        with open(json_path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"\n{'='*60}")
        print(f"ERROR: Agents file corrupted: {json_path}")
        print(f"Details: {e}")
        print(f"{'='*60}\n")
        return False

    bm.clear_agents()
    agent_data = data.get("agents", [])

    # Create agent configs
    for t in agent_data:
        cfg = rpg.AgentConfig()
        cfg.name = t["name"]
        sprite_filename = t.get("sprite_path", "")
        cfg.sprite_path = os.path.join(sprites_dir, sprite_filename) if sprite_filename else ""
        cfg.size = t["size"]
        cfg.start_col = t["col"]
        cfg.start_row = t["row"]
        combat.add_agent_config(bm, cfg)

    combat.apply_agent_configs(bm)

    # Restore stats for each placed agent
    for i, t in enumerate(agent_data):
        if i >= len(bm.placed_agents):
            break
        sd = t.get("stats")
        if not sd:
            continue
        s = dict_to_stats(sd)
        apply_damage_multipliers(s, sd)
        combat.set_agent_stats(bm, i, s)

    # Restore weapons
    for i, t in enumerate(agent_data):
        if i >= len(bm.placed_agents):
            break
        cpp_weapons = [rpg.Weapon(), rpg.Weapon(), rpg.Weapon()]

        weapons_dict = t.get("weapons", {})
        if weapons_dict and isinstance(weapons_dict, dict):
            slot_names = ["main_hand", "off_hand", "ranged"]
            for slot_idx, slot_name in enumerate(slot_names):
                weapon_data = weapons_dict.get(slot_name, "")
                if weapon_data:
                    # Weapons can be stored as dicts (from replay.py)
                    if isinstance(weapon_data, dict):
                        cpp_weapons[slot_idx] = _dict_to_weapon(weapon_data)

        combat.set_agent_weapons(bm, i, cpp_weapons)

    # Restore character class, level, and all subclasses
    for i, t in enumerate(agent_data):
        if i >= len(bm.placed_agents):
            break
        stats = combat.get_agent_stats(bm, i)
        restore_class_resources(stats, t)
        combat.set_agent_stats(bm, i, stats)

    return True
