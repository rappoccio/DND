# ─────────────────────────────────────────────────────────────────────────────
#  helpers.py  –  Utility functions for D&D mechanics and serialization
# ─────────────────────────────────────────────────────────────────────────────

import math

import rpg_battle_map as rpg


# ─────────────────────────────────────────────────────────────────────────────
#  Placement rules (shared by the GUI and unit tests; no pygame dependency)
# ─────────────────────────────────────────────────────────────────────────────

def can_place_agent(bm, cell, size, exclude_idx=-1) -> bool:
    """Return True if a size×size agent fits at top-left `cell`: in bounds, not on a
    wall/blocked cell, and not overlapping another LIVE agent's footprint. A tombstoned
    agent (removed_from_play, e.g. a dismissed summon) no longer occupies its cell, and
    neither does a downed body (hp_cur <= 0) — mirroring the engine's agentOccupancy,
    so a killed agent's square frees up for others to move into or be placed on."""
    cols, rows = bm.grid_cols, bm.grid_rows
    if cell.col < 0 or cell.row < 0:
        return False
    if cell.col + size > cols or cell.row + size > rows:
        return False
    if bm.is_blocked(cell, size):
        return False
    for i, pt in enumerate(bm.placed_agents):
        if i == exclude_idx or pt.removed_from_play or pt.stats.hp_cur <= 0:
            continue
        if (cell.col < pt.origin.col + pt.size and
                cell.col + size > pt.origin.col and
                cell.row < pt.origin.row + pt.size and
                cell.row + size > pt.origin.row):
            return False
    return True


def summon_cell_placeable(bm, caster_origin, caster_size, cell, size, spell_range) -> bool:
    """Whether a summon of footprint `size` may manifest at `cell`: within the spell's
    range (feet, 5 ft/cell), with line of sight from the caster, on an unoccupied cell.
    Single source of truth for both the placement preview and _resolve_summon."""
    dist_cells = math.hypot(cell.col - caster_origin.col, cell.row - caster_origin.row)
    if dist_cells * 5.0 > spell_range + 1e-6:
        return False
    if not bm.has_line_of_sight(caster_origin, caster_size, cell, size):
        return False
    return can_place_agent(bm, cell, size)


# ─────────────────────────────────────────────────────────────────────────────
#  Beast Master: Primal Companion scaling (shared by the GUI and unit tests)
# ─────────────────────────────────────────────────────────────────────────────

def compute_companion_loadout(block: dict, pb: int, level: int, wis_mod: int):
    """Build a (stats_dict, weapon_dict) for a Primal Companion from its base stat
    `block` (one entry of primal_companions.json) and the owning Ranger's Proficiency
    Bonus / level / WIS modifier. Pure (no pygame / no engine state), so it is unit-tested
    directly.

    Scaling (2024 Beast Master):
      · HP  = hp_base + hp_per_level × Ranger level
      · AC  = 13 + PB
      · num_attacks = 2 at Ranger L11+ (Bestial Fury), else 1
      · natural-weapon to-hit = Ranger's spell-attack modifier (PB + WIS mod)
      · natural-weapon damage bonus = PB
    The to-hit/damage targets are RAW-fixed regardless of the beast's own ability mod,
    so weapon bonus_hit/bonus_damage cancel the mod the engine will re-add.
    """
    form = block.get("form", "Land")
    finesse = (form == "Sky")   # Sky has STR 6 and strikes with DEX; Land/Sea use STR.
    str_mod = _dnd_mod(block.get("str", 14))
    dex_mod = _dnd_mod(block.get("dex", 14))
    ability_mod = max(str_mod, dex_mod) if finesse else str_mod

    hp = block.get("hp_base", 5) + block.get("hp_per_level", 5) * level
    stats = {
        "str":   block.get("str", 14),
        "dex":   block.get("dex", 14),
        "con":   block.get("con", 15),
        "intel": block.get("intel", 8),
        "wis":   block.get("wis", 14),
        "cha":   block.get("cha", 11),
        "hp_max": hp,
        "hp_cur": hp,
        "base_ac": 13 + pb,
        "speed_walk": block.get("speed_walk", 30),
        "speed_swim": block.get("speed_swim", 0),
        "speed_fly":  block.get("speed_fly", 0),
        "prof_bonus": pb,
        "darkvision_range": block.get("darkvision", 60),
        "is_npc": True,
        "num_attacks": 2 if level >= 11 else 1,
        # Exceptional Training (Ranger L7+): the companion may Dash/Disengage/Hide as a Bonus
        # Action — reuse the Cunning Action machinery (surfaces those bonus-action buttons).
        "has_cunning_action": level >= 7,
    }
    atk = block.get("attack", {})
    roll = {
        "type":     atk.get("damage_type", "Slashing"),
        "num_dice": atk.get("num_dice", 1),
        "die_size": atk.get("die_size", 8),
    }
    weapon = {
        "name": atk.get("name", "Natural Weapon"),
        "type": "melee",
        "reach_ft": 5,
        "proficient": True,
        "finesse": finesse,
        "bonus_hit":    (pb + wis_mod) - pb - ability_mod,
        "bonus_damage": pb - ability_mod,
        "physical_damage_types": [roll],
        "magic_damage_types":    [],
    }
    # Exceptional Training (Ranger L7+): the companion's attacks may deal Force damage instead of
    # their normal type. Force is a *magic* damage type, so the roll moves to magic_damage_types
    # (the default at L7+ so it bypasses physical resistances — the only reason to keep the normal
    # type is a Force-immune foe, which is rare; see known_limitations).
    if level >= 7:
        weapon["physical_damage_types"] = []
        weapon["magic_damage_types"]    = [dict(roll, type="Force")]
    return stats, weapon


def compute_summon_loadout(block: dict, slot_level: int, pb: int, spell_ability_mod: int):
    """Build a (stats_dict, weapon_dict) for a 2024 "Summon X" spirit from its base `block`
    (one entry of summon_spirits.json), scaled to the slot level the spell was cast with and
    the caster's Proficiency Bonus + spellcasting-ability modifier. Pure (no pygame / no engine
    state), so it is unit-tested directly. Mirrors compute_companion_loadout.

    Scaling (2024 summon-spirit pattern, verified vs the Draconic/Bestial Spirit cards):
      · AC  = ac_base + slot_level   (AC scales with the FULL spell level)
      · HP  = hp_base + hp_per_level × max(0, slot_level − base_level)   (hp_base = HP AT the
              spell's base level; the rider is "+N per spell level above base")
      · num_attacks = max(1, slot_level // 2) if `multiattack_half_level` (the "Multiattack: a
              number of Rend attacks equal to half the spell's level" rule); otherwise 2 once
              slot_level ≥ `multiattack_at` (default = never), else 1.
      · attack to-hit = the caster's spell-attack modifier (PB + spell_ability_mod); bonus_hit
              cancels the spirit's own ability mod the engine re-adds.
      · attack damage = num_dice d die_size + dmg_flat + (dmg_per_level × slot_level) of the
              form's type. dmg_flat is the card's printed flat bonus (= the spirit's ability mod
              on the verified cards); bonus_damage cancels the engine's re-added ability mod so
              the printed "die + flat + level" total is reproduced exactly, whatever the STR/DEX.
    """
    str_mod = _dnd_mod(block.get("str", 12))
    dex_mod = _dnd_mod(block.get("dex", 12))
    finesse = bool(block.get("finesse", False))
    ability_mod = dex_mod if finesse else str_mod

    base_level = block.get("base_level", 0)
    hp = block.get("hp_base", 5) + block.get("hp_per_level", 5) * max(0, slot_level - base_level)
    if block.get("multiattack_half_level", False):
        num_attacks = max(1, slot_level // 2)
    else:
        num_attacks = 2 if slot_level >= block.get("multiattack_at", 99) else 1
    stats = {
        "str":   block.get("str", 12),
        "dex":   block.get("dex", 12),
        "con":   block.get("con", 14),
        "intel": block.get("intel", 4),
        "wis":   block.get("wis", 10),
        "cha":   block.get("cha", 6),
        "hp_max": hp,
        "hp_cur": hp,
        "base_ac": block.get("ac_base", 11) + slot_level,
        "speed_walk": block.get("speed_walk", 30),
        "speed_swim": block.get("speed_swim", 0),
        "speed_fly":  block.get("speed_fly", 0),
        "prof_bonus": pb,
        "darkvision_range": block.get("darkvision", 60),
        "is_npc": True,
        "num_attacks": num_attacks,
    }
    atk = block.get("attack", {})
    dmg_bonus = block.get("dmg_flat", 0) + block.get("dmg_per_level", 1) * slot_level
    roll = {
        "type":     atk.get("damage_type", "Bludgeoning"),
        "num_dice": atk.get("num_dice", 1),
        "die_size": atk.get("die_size", 8),
    }
    weapon = {
        "name": atk.get("name", "Spirit Strike"),
        "type": "ranged" if atk.get("ranged", False) else "melee",
        "reach_ft": atk.get("reach_ft", 5),
        "proficient": True,
        "finesse": finesse,
        # to-hit total = ability_mod + pb + bonus_hit = pb + spell_ability_mod (= spell atk mod).
        "bonus_hit":    spell_ability_mod - ability_mod,
        # damage total bonus = ability_mod + bonus_damage = dmg_bonus (dmg_flat + level rider);
        # cancelling ability_mod reproduces the card's printed "die + flat + level" exactly.
        "bonus_damage": dmg_bonus - ability_mod,
    }
    # The spirit's signature damage type may be magical (Radiant/Necrotic/Force/Psychic/etc.),
    # in which case it bypasses non-magical resistances — route it through magic_damage_types.
    if atk.get("magic", False):
        weapon["physical_damage_types"] = []
        weapon["magic_damage_types"]    = [roll]
    else:
        weapon["physical_damage_types"] = [roll]
        weapon["magic_damage_types"]    = []
    return stats, weapon


# ─────────────────────────────────────────────────────────────────────────────
#  D&D mechanics helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dnd_mod(score: int) -> int:
    """Return the D&D ability modifier for a given score (floor((score-10)/2))."""
    return (score - 10) // 2

def _mod_str(score: int) -> str:
    m = _dnd_mod(score)
    return f"+{m}" if m >= 0 else str(m)

def _calculate_total_ac(base_ac: int, dex: int, armor_list: list) -> int:
    """Calculate total AC from base AC, DEX score, and armor pieces.

    armor_list: list of rpg.Armor objects (or dicts with 'ac_bonus' key).
    Returns the total AC including (capped) DEX modifier and armor bonuses.
    """
    total = base_ac

    # Calculate DEX modifier (will be capped based on armor)
    dex_mod = _dnd_mod(dex)

    # Find the most restrictive DEX modifier cap from equipped armor
    dex_mod_cap = None  # Default: no cap (light armor/unarmored)
    if armor_list:
        for piece in armor_list:
            # Only consider equipped pieces
            piece_name = None
            piece_cap = None

            if hasattr(piece, 'name'):
                piece_name = piece.name
                piece_cap = getattr(piece, 'dex_mod_cap', None)
            elif isinstance(piece, dict):
                piece_name = piece.get('name')
                piece_cap = piece.get('dex_mod_cap', None)

            # If this piece is equipped and has a cap, use it (most restrictive wins)
            if piece_name and piece_cap is not None:
                dex_mod_cap = piece_cap if dex_mod_cap is None else min(dex_mod_cap, piece_cap)

    # Apply capped DEX modifier (None = no cap)
    if dex_mod_cap is None:
        total += dex_mod  # No cap, apply full DEX modifier
    else:
        total += min(dex_mod, dex_mod_cap)  # Apply cap

    # Add armor bonuses
    if armor_list:
        for piece in armor_list:
            if hasattr(piece, 'ac_bonus'):
                bonus = piece.ac_bonus
            elif isinstance(piece, dict) and 'ac_bonus' in piece:
                bonus = piece.get('ac_bonus', 0)
            else:
                bonus = 0
            # Only add if armor piece is equipped (non-empty name)
            if hasattr(piece, 'name') and piece.name:
                total += bonus
            elif isinstance(piece, dict) and piece.get('name'):
                total += bonus

    return total


# ─────────────────────────────────────────────────────────────────────────────
#  Damage type parsing
# ─────────────────────────────────────────────────────────────────────────────

_PHYSICAL_DMG_NAMES = ("Bludgeoning", "Piercing", "Slashing")

def _parse_physical_damage(v):
    """Accept a string name or int ordinal, return rpg.PhysicalDamage."""
    if isinstance(v, str):
        return getattr(rpg.PhysicalDamage, v)
    return rpg.PhysicalDamage(int(v))

def _parse_magic_damage(v):
    """Accept a string name or int ordinal, return rpg.MagicDamage."""
    if isinstance(v, str):
        return getattr(rpg.MagicDamage, v)
    return rpg.MagicDamage(int(v))

def _parse_mastery(v):
    """Accept a 2024 Weapon Mastery name (or int ordinal), return rpg.WeaponMastery.

    Note: the enum value is named "None"; since that is a Python keyword it can only
    be reached via getattr, never as rpg.WeaponMastery.None (a syntax error)."""
    if v is None or v == "":
        return getattr(rpg.WeaponMastery, "None")
    if isinstance(v, str):
        return getattr(rpg.WeaponMastery, v)
    return rpg.WeaponMastery(int(v))


# ─────────────────────────────────────────────────────────────────────────────
#  Weapon serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_WEAPON: dict = {
    "name":            "New Weapon",
    "type":            "melee",    # "melee" | "ranged"
    "reach_ft":        5,          # melee reach in feet (5 / 10 / 15)
    "normal_range_ft": 80,         # ranged: normal range in feet
    "long_range_ft":   320,        # ranged: long range in feet
    "finesse":         False,
    "thrown":          False,      # Thrown property: may be hurled as a ranged attack
    "quantity":        1,          # copies carried; a THROW spends one (javelins come in bundles)
    "proficient":      True,
    "off_hand":        False,      # designated off-hand weapon (TWF)
    "two_handed":      False,      # prevents off-hand weapon when in main hand
    "bonus_hit":       0,          # flat bonus to attack rolls
    "bonus_damage":    0,          # flat bonus to damage
    "physical_damage_types": [{"type": "Slashing", "num_dice": 1, "die_size": 6}],
    "magic_damage_types":    [],
}


def _weapon_to_dict(w) -> dict:
    """Convert an rpg.Weapon object to a plain dict for dialog editing."""
    return {
        "name":             w.name,
        "type":             "melee" if w.type == rpg.WeaponType.Melee else "ranged",
        "reach_ft":         w.reach_ft,
        "normal_range_ft":  w.normal_range_ft,
        "long_range_ft":    w.long_range_ft,
        "finesse":          w.finesse,
        "thrown":           w.thrown,
        # Thrown-weapon bundle + ground icon. quantity MUST round-trip or a character who saved
        # mid-fight with 2 javelins left reloads holding a fresh full bundle.
        "quantity":         w.quantity,
        "sprite_path":      w.sprite_path,
        "returns_after_throw": w.returns_after_throw,
        # Synthetic-weapon identity flags — MUST be serialized or they vanish on save/reload:
        # the weapon keeps its name ("PactBlade"/"PsychicBlade") so the re-conjure guard skips it,
        # leaving pact_weapon/psychic_blade False (no CHA attack/damage, no Soulknife riders).
        "pact_weapon":      w.pact_weapon,
        "psychic_blade":    w.psychic_blade,
        "proficient":       w.proficient,
        "off_hand":         w.off_hand,
        "two_handed":       w.two_handed,
        "heavy":            w.heavy,
        "light":            w.light,
        "is_shield":        w.is_shield,
        "auto_hit_if_grappled": w.auto_hit_if_grappled,
        # Save-delivered damage (a Vampire's Bite: CON save, not an attack roll). MUST round-trip or the
        # bite reverts to a plain auto-hit on save/reload.
        "save_for_damage":         w.save_for_damage,
        "save_for_damage_ability": w.save_for_damage_ability.name,
        # Auto-use-when-grappling (Vampire Bite auto-offer/auto-attempt). MUST round-trip or the
        # prompt/automation intent is lost on save/reload of encounters and the bestiary.
        "auto_use_when_grappling": w.auto_use_when_grappling,
        "permanently_armed": w.permanently_armed,
        "mastery":          w.mastery.name,
        "bonus_hit":        w.bonus_hit,
        "bonus_damage":     w.bonus_damage,
        "ac_bonus":         w.ac_bonus,
        # N/day attacks + Recharge — MUST round-trip or NPC usage caps reset on save/reload.
        "uses_max":         w.uses_max,
        "uses_remaining":   w.uses_remaining,
        "recharge_min":     w.recharge_min,
        "expended":         w.expended,
        "physical_damage_types": [{"type": r.type.name, "num_dice": r.num_dice, "die_size": r.die_size}
                                   for r in w.physical_damage_types],
        "magic_damage_types":    [{"type": r.type.name, "num_dice": r.num_dice, "die_size": r.die_size}
                                   for r in w.magic_damage_types],
        # On-hit riders (Grappled/escape_dc, reduceHPMax, save-based conditions, etc.).
        # MUST be serialized or they vanish on encounter save/reload (and weapon-dialog round-trips).
        "conditions": [{"condition_name":     c.condition_name,
                        "condition_duration":  c.condition_duration,
                        "push_ft":             c.push_ft,
                        "save_repeat_turns":   c.save_repeat_turns,
                        "contested":           c.contested,
                        "escape_dc":           c.escape_dc,
                        "requires_save":       c.requires_save,
                        "save_ability":        c.save_ability.name,
                        "save_dc_ability":     c.save_dc_ability.name,
                        "on_damage":           c.on_damage.name,
                        # Damage-over-time / no-heal rider (Pit Fiend poison). MUST round-trip or the
                        # bite's ongoing poison silently reverts to a plain Poisoned condition on reload.
                        "dot_dice":            c.dot_dice,
                        "dot_die_size":        c.dot_die_size,
                        "dot_flat_bonus":      c.dot_flat_bonus,
                        "dot_damage_type":     c.dot_damage_type.name,
                        "prevents_healing":    c.prevents_healing}
                       for c in w.conditions],
    }


def _dict_to_weapon(d: dict):
    """Convert a plain dict to an rpg.Weapon object."""
    w = rpg.Weapon()
    w.name            = d.get("name",            "Unnamed")
    w.type            = (rpg.WeaponType.Melee
                         if d.get("type", "melee") == "melee"
                         else rpg.WeaponType.Ranged)
    w.reach_ft        = int(d.get("reach_ft",        5))
    w.normal_range_ft = int(d.get("normal_range_ft", 80))
    w.long_range_ft   = int(d.get("long_range_ft",   320))
    w.finesse         = bool(d.get("finesse",         False))
    w.thrown          = bool(d.get("thrown",          False))
    # A weapon in hand is one weapon: default 1, never 0, or nothing loaded from weapons.json
    # (which does not author a quantity) could ever be thrown.
    w.quantity        = int(d.get("quantity",         1))
    w.sprite_path     = d.get("sprite_path", "") or ""
    w.returns_after_throw = bool(d.get("returns_after_throw", False))
    w.pact_weapon     = bool(d.get("pact_weapon",     False))
    w.psychic_blade   = bool(d.get("psychic_blade",   False))
    w.proficient      = bool(d.get("proficient",      True))
    w.off_hand        = bool(d.get("off_hand",        False))
    w.two_handed      = bool(d.get("two_handed",      False))
    w.heavy           = bool(d.get("heavy",           False))
    w.light           = bool(d.get("light",           False))
    w.is_shield       = bool(d.get("is_shield",       False))
    w.auto_hit_if_grappled = bool(d.get("auto_hit_if_grappled", False))
    # Save-delivered damage (a Vampire's Bite): the target rolls save_for_damage_ability; a failure lets
    # the bite land (full damage + riders), a success negates it. Paired with auto_hit_if_grappled.
    w.save_for_damage = bool(d.get("save_for_damage", False))
    _sfa = d.get("save_for_damage_ability", "SaveCon")
    try:
        w.save_for_damage_ability = getattr(rpg.SaveAbility, _sfa)
    except AttributeError:
        w.save_for_damage_ability = rpg.SaveAbility.SaveCon
    w.auto_use_when_grappling = bool(d.get("auto_use_when_grappling", False))
    w.permanently_armed = bool(d.get("permanently_armed", False))
    w.mastery         = _parse_mastery(d.get("mastery", ""))
    w.bonus_hit       = int(d.get("bonus_hit",       0))
    w.bonus_damage    = int(d.get("bonus_damage",    0))
    w.ac_bonus        = int(d.get("ac_bonus",        0))
    # N/day attacks + Recharge.  uses_max==0 ⇒ unlimited; recharge_min==0 ⇒ no recharge.
    w.uses_max        = int(d.get("uses_max",        0))
    # Default remaining to the cap so a freshly-loaded weapon starts full.
    w.uses_remaining  = int(d.get("uses_remaining",  d.get("uses_max", 0)))
    w.recharge_min    = int(d.get("recharge_min",    0))
    w.expended        = bool(d.get("expended",       False))

    # Physical damage rolls - build list then assign
    physical_rolls = []
    for entry in d.get("physical_damage_types", []):
        r = rpg.PhysicalDamageRoll()
        r.type     = _parse_physical_damage(entry.get("type", "Slashing"))
        r.num_dice = int(entry.get("num_dice", 1))
        r.die_size = int(entry.get("die_size", 6))
        r.bonus    = 0
        physical_rolls.append(r)
    w.physical_damage_types = physical_rolls

    # Magic damage rolls - build list then assign
    magic_rolls = []
    for entry in d.get("magic_damage_types", []):
        r = rpg.MagicDamageRoll()
        r.type     = _parse_magic_damage(entry.get("type", "Fire"))
        r.num_dice = int(entry.get("num_dice", 1))
        r.die_size = int(entry.get("die_size", 6))
        r.bonus    = 0
        magic_rolls.append(r)
    w.magic_damage_types = magic_rolls

    # Attack conditions - build list then assign
    conditions = []
    for cond_entry in d.get("conditions", []):
        if isinstance(cond_entry, dict):
            # Full condition spec: {"condition_name": "Stunned", "condition_duration": 2, "save_ability": "SaveStr", "save_dc_ability": "SaveWis"}
            c = rpg.AttackCondition()
            c.condition_name = cond_entry.get("condition_name", "")
            c.condition_duration = int(cond_entry.get("condition_duration", 0))
            c.push_ft = int(cond_entry.get("push_ft", 0))
            c.save_repeat_turns = int(cond_entry.get("save_repeat_turns", 1))
            # Grappled rider: contested Athletics vs automatic-on-hit, + optional fixed escape DC.
            c.contested = bool(cond_entry.get("contested", False))
            c.escape_dc = int(cond_entry.get("escape_dc", 0))
            if "requires_save" in cond_entry:
                c.requires_save = bool(cond_entry["requires_save"])
            on_damage_str = cond_entry.get("on_damage")
            if on_damage_str:
                try:
                    c.on_damage = getattr(rpg.OnDamage, on_damage_str)
                except AttributeError:
                    pass
            # Parse save_ability string (target's save - e.g., "SaveDex" -> rpg.SaveAbility.SaveDex)
            save_ability_str = cond_entry.get("save_ability", "SaveDex")
            try:
                c.save_ability = getattr(rpg.SaveAbility, save_ability_str)
            except AttributeError:
                c.save_ability = rpg.SaveAbility.SaveDex
            # Parse save_dc_ability string (attacker's ability - e.g., "SaveWis" -> rpg.SaveAbility.SaveWis)
            save_dc_ability_str = cond_entry.get("save_dc_ability", "SaveWis")
            try:
                c.save_dc_ability = getattr(rpg.SaveAbility, save_dc_ability_str)
            except AttributeError:
                c.save_dc_ability = rpg.SaveAbility.SaveWis
            # Damage-over-time / no-heal rider (Pit Fiend poison): dot_dice × d(dot_die_size) +
            # dot_flat_bonus of dot_damage_type at the start of each turn; prevents_healing blocks HP gain.
            c.dot_dice = int(cond_entry.get("dot_dice", 0))
            c.dot_die_size = int(cond_entry.get("dot_die_size", 0))
            c.dot_flat_bonus = int(cond_entry.get("dot_flat_bonus", 0))
            c.dot_damage_type = _parse_magic_damage(cond_entry.get("dot_damage_type", "Poison"))
            c.prevents_healing = bool(cond_entry.get("prevents_healing", False))
            conditions.append(c)
        else:
            # Simple string: just the condition name
            c = rpg.AttackCondition()
            c.condition_name = str(cond_entry)
            c.condition_duration = 0
            c.push_ft = 0
            c.save_repeat_turns = 1
            c.save_ability = rpg.SaveAbility.SaveDex
            c.save_dc_ability = rpg.SaveAbility.SaveWis
            conditions.append(c)
    w.conditions = conditions

    return w


def _condition_to_dict(c) -> dict:
    """Serialize an rpg.ActiveAgentCondition (a LIVE, in-flight tracking entry — duration,
    save timers, delayed/stored effect, and the Vistani-Curse kickback) to a plain dict.

    The whole struct is serialized, not just the kickback fields: a half-serialized entry is
    worse than none (a lingering curse would reload with the wrong timer/save). Round-trip
    discipline — every field written here MUST be read back in _dict_to_condition or it resets
    on reload. Enums round-trip by .name (see MagicDamage / SaveAbility bindings)."""
    return {
        "agent_idx":         c.agent_idx,
        "caster_idx":        c.caster_idx,
        "spell_idx":         c.spell_idx,
        "condition_name":    c.condition_name,
        "turns_remaining":   c.turns_remaining,
        "next_save_turn":    c.next_save_turn,
        "save_ability":      c.save_ability.name,
        "save_dc":           c.save_dc,
        "save_repeat_turns": c.save_repeat_turns,
        "condition_id":      c.condition_id,
        "cast_level":        c.cast_level,
        "on_damage":         c.on_damage.name,
        # Delayed / stored effect (Quivering Palm, Delayed Blast Fireball).
        "delayed_trigger":      c.delayed_trigger,
        "delay_dice":           c.delay_dice,
        "delay_die_size":       c.delay_die_size,
        "delay_flat_bonus":     c.delay_flat_bonus,
        "delay_damage_type":    c.delay_damage_type.name,
        "delay_requires_save":  c.delay_requires_save,
        "delay_half_on_save":   c.delay_half_on_save,
        "delay_drop_to_zero":   c.delay_drop_to_zero,
        "delay_auto_on_expire": c.delay_auto_on_expire,
        "delay_label":          c.delay_label,
        # Damage-over-time / no-heal rider (generic; Pit Fiend poison).
        "dot_dice":             c.dot_dice,
        "dot_die_size":         c.dot_die_size,
        "dot_flat_bonus":       c.dot_flat_bonus,
        "dot_damage_type":      c.dot_damage_type.name,
        "prevents_healing":     c.prevents_healing,
        # Caster "kickback" on condition end (Vistani Curse).
        "kickback_dice":        c.kickback_dice,
        "kickback_die_size":    c.kickback_die_size,
        "kickback_damage_type": c.kickback_damage_type.name,
        # Vistani Curse effect state.
        "curse_disadv_ability": c.curse_disadv_ability,
        "curse_vuln_type_code": c.curse_vuln_type_code,
        "curse_vuln_prev_mult": c.curse_vuln_prev_mult,
    }


def _dict_to_condition(d: dict):
    """Rebuild an rpg.ActiveAgentCondition from a dict produced by _condition_to_dict.

    agent_idx / caster_idx are indices into placed_agents; the caller must re-add this via
    combat.add_agent_condition only AFTER the agents are placed in the SAME order they were
    saved, or the indices resolve to the wrong creatures."""
    c = rpg.ActiveAgentCondition()
    c.agent_idx         = int(d.get("agent_idx",  -1))
    c.caster_idx        = int(d.get("caster_idx", -1))
    c.spell_idx         = int(d.get("spell_idx",  -1))
    c.condition_name    = d.get("condition_name", "")
    c.turns_remaining   = int(d.get("turns_remaining",   0))
    c.next_save_turn    = int(d.get("next_save_turn",    0))
    try:
        c.save_ability  = getattr(rpg.SaveAbility, d.get("save_ability", "SaveDex"))
    except AttributeError:
        c.save_ability  = rpg.SaveAbility.SaveDex
    c.save_dc           = int(d.get("save_dc",           0))
    c.save_repeat_turns = int(d.get("save_repeat_turns", 1))
    c.condition_id      = int(d.get("condition_id",     -1))
    c.cast_level        = int(d.get("cast_level",        0))
    try:
        c.on_damage     = getattr(rpg.OnDamage, d.get("on_damage", "None"))
    except AttributeError:
        pass
    # Delayed / stored effect.
    c.delayed_trigger      = bool(d.get("delayed_trigger",      False))
    c.delay_dice           = int(d.get("delay_dice",           0))
    c.delay_die_size       = int(d.get("delay_die_size",       0))
    c.delay_flat_bonus     = int(d.get("delay_flat_bonus",     0))
    c.delay_damage_type    = _parse_magic_damage(d.get("delay_damage_type", "Force"))
    c.delay_requires_save  = bool(d.get("delay_requires_save",  True))
    c.delay_half_on_save   = bool(d.get("delay_half_on_save",   True))
    c.delay_drop_to_zero   = bool(d.get("delay_drop_to_zero",   False))
    c.delay_auto_on_expire = bool(d.get("delay_auto_on_expire", False))
    c.delay_label          = d.get("delay_label", "")
    # Damage-over-time / no-heal rider (generic; Pit Fiend poison).
    c.dot_dice         = int(d.get("dot_dice",         0))
    c.dot_die_size     = int(d.get("dot_die_size",     0))
    c.dot_flat_bonus   = int(d.get("dot_flat_bonus",   0))
    c.dot_damage_type  = _parse_magic_damage(d.get("dot_damage_type", "Poison"))
    c.prevents_healing = bool(d.get("prevents_healing", False))
    # Caster "kickback" on condition end (Vistani Curse).
    c.kickback_dice        = int(d.get("kickback_dice",     0))
    c.kickback_die_size    = int(d.get("kickback_die_size", 0))
    c.kickback_damage_type = _parse_magic_damage(d.get("kickback_damage_type", "Psychic"))
    # Vistani Curse effect state.
    c.curse_disadv_ability = int(d.get("curse_disadv_ability", -1))
    c.curse_vuln_type_code = int(d.get("curse_vuln_type_code", -1))
    c.curse_vuln_prev_mult = float(d.get("curse_vuln_prev_mult", 1.0))
    return c


def _weapon_slot_is_empty(w) -> bool:
    """True for a blank weapon slot: no name, or the default "Unarmed" sentinel
    (weapon.hpp defaults Weapon.name = "Unarmed"). "MonkUnarmed" is a REAL monk
    weapon and is NOT empty."""
    return (not w.name) or (w.name == "Unarmed")


def _weapons_to_list(weapons) -> list:
    """Serialize an agent's weapon list (from get_agent_weapons) to a flat list of dicts.

    Index convention is preserved (0=main_hand, 1=off_hand, 2=ranged, 3+=extra "Attack N").
    Trailing empty slots (nameless / the bare "Unarmed" sentinel) are dropped so a plain
    melee monster stays compact, but interior empties are kept as empty dicts to preserve
    later slots' indices (a recipe may reference slot 3 even if slot 1 is empty)."""
    dicts = [{} if _weapon_slot_is_empty(w) else _weapon_to_dict(w) for w in weapons]
    # Drop trailing empties only.
    while dicts and not dicts[-1]:
        dicts.pop()
    return dicts


def _weapons_from_list(data) -> list:
    """Deserialize the saved weapons field to a list of rpg.Weapon, padded to >=3.

    Accepts BOTH the new flat list form AND the legacy {main_hand,off_hand,ranged} dict so
    older encounter/PC saves still load. Empty dicts / empty names become blank rpg.Weapon()s."""
    weapons: list = []
    if isinstance(data, dict):
        # Legacy 3-slot dict form.
        for key in ("main_hand", "off_hand", "ranged"):
            entry = data.get(key)
            weapons.append(_dict_to_weapon(entry) if isinstance(entry, dict) and entry.get("name")
                           else rpg.Weapon())
    elif isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("name"):
                weapons.append(_dict_to_weapon(entry))
            elif isinstance(entry, str) and entry:
                # Oldest saves stored bare weapon-name strings; look up via catalog if available.
                weapons.append(_dict_to_weapon({"name": entry}))
            else:
                weapons.append(rpg.Weapon())
    # Invariant: pad to >=3 empty slots so the PC path (main/off/ranged) is always addressable.
    while len(weapons) < 3:
        weapons.append(rpg.Weapon())
    return weapons


# ─────────────────────────────────────────────────────────────────────────────
#  Armor serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_ARMOR: dict = {
    "name":            "New Armor",
    "description":     "",
    "ac_bonus":        0,
    "magic_damage_multipliers": [1.0] * 10,  # 10 magic damage types
    "physical_damage_multipliers": [1.0] * 3,  # 3 physical damage types
    "damage_reduction": 0,  # flat damage reduction in HP
    "requires_strength": False,
    "str_requirement": 0,
}


def _dict_to_armor(d: dict):
    """Convert a plain dict to an rpg.Armor object.

    Computes ac_bonus from the 'ac' field (handbook AC value),
    or uses explicit ac_bonus if provided (for shields/items that add to AC).
    """
    a = rpg.Armor()
    a.name = d.get("name", "Unnamed")
    a.description = d.get("description", "")

    # Compute ac_bonus: if "ac" is given, it's the base AC (subtract 10 for bonus)
    # Otherwise use explicit ac_bonus (for shields, magical items)
    if "ac" in d:
        a.ac_bonus = int(d["ac"]) - 10
    else:
        a.ac_bonus = int(d.get("ac_bonus", 0))

    a.damage_reduction = int(d.get("damage_reduction", 0))
    a.requires_strength = bool(d.get("requires_strength", False))
    a.str_requirement = int(d.get("str_requirement", 0))
    # DEX-to-AC cap: heavy armor = 0, medium = 2, light/unarmored omit it (C++ default 30). This
    # must be carried onto the C++ Armor or calculateAC can't cap DEX, and Heavy/Medium Armor
    # Master (which key off dex_mod_cap == 0 / == 2) can't detect the armor category.
    a.dex_mod_cap = int(d.get("dex_mod_cap", 30))

    # Magic damage multipliers (10 types)
    magic_mults = d.get("magic_damage_multipliers", [1.0] * 10)
    # Ensure it's the right length
    magic_mults = list(magic_mults) + [1.0] * 10
    a.magic_damage_multipliers = magic_mults[:10]

    # Physical damage multipliers (3 types)
    phys_mults = d.get("physical_damage_multipliers", [1.0] * 3)
    # Ensure it's the right length
    phys_mults = list(phys_mults) + [1.0] * 3
    a.physical_damage_multipliers = phys_mults[:3]

    return a


def _armor_to_dict(a) -> dict:
    """Convert an rpg.Armor object to a plain dict."""
    return {
        "name": a.name,
        "description": a.description,
        "ac_bonus": a.ac_bonus,
        "dex_mod_cap": a.dex_mod_cap,
        "magic_damage_multipliers": list(a.magic_damage_multipliers),
        "physical_damage_multipliers": list(a.physical_damage_multipliers),
        "damage_reduction": a.damage_reduction,
        "requires_strength": a.requires_strength,
        "str_requirement": a.str_requirement,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Spell serialization helpers
# ─────────────────────────────────────────────────────────────────────────────

_ABILITY_TO_INT: dict[str, int] = {
    name.removeprefix("Save").lower(): member.value
    for name, member in rpg.SaveAbility.__members__.items()
    if name.startswith("Save")
}
_INT_TO_ABILITY: dict[int, str] = {v: k for k, v in _ABILITY_TO_INT.items()}


_DEFAULT_SPELL: dict = {
    "name":                  "New Spell",
    "type":                  "Harm",
    "geometry":              "Single",
    "attack_type":           "AttackRoll",
    "save_ability":          None,   # used by Save attack type only
    "range":                 30,
    "radius":                None,   # used by Sphere/Cone only
    "width":                 None,   # used by Line only
    "length":                None,   # used by Line only
    "duration":               1,
    "magic_damage_types":    ["Fire"],
    "physical_damage_types": [],
    "num_dice":               1,
    "die_size":               6,
    "terrain_effect":        None,   # {type, multiplier, duration} or None
    "hatch_pattern":         None,   # matplotlib hatch pattern: '//', '\\', '||', etc.
    "terrain_color":         None,   # RGB tuple (R, G, B) for terrain, None = brown default
    "level":                 0,      # 0=cantrip/unlimited, 1-9=requires spell slot
    "upcast_dice_bonus":     0,      # extra dice per slot level above spell.level
}


def _spell_to_dict(s) -> dict:
    geo = s.geometry.name
    uses_radius = geo in ("Sphere", "Cone")
    # Line, Square and Rectangle all carry their extent in width/length. Dropping
    # them for Square/Rectangle (as an over-narrow `geo == "Line"` test once did)
    # made a saved Square reload with the width=5/length=30 defaults — i.e. a
    # 1-cell-wide line (this is how Hypnotic Pattern silently became a line).
    uses_line   = geo in ("Line", "Square", "Rectangle")

    # Convert magic_damage_types to new format with per-type dice
    magic_dmg = []
    for roll in s.magic_damage_rolls:
        magic_dmg.append({
            "type": roll.type.name,
            "num_dice": roll.num_dice,
            "die_size": roll.die_size
        })

    # Convert physical_damage_types to new format with per-type dice
    phys_dmg = []
    for roll in s.physical_damage_rolls:
        phys_dmg.append({
            "type": roll.type.name,
            "num_dice": roll.num_dice,
            "die_size": roll.die_size
        })

    return {
        "name":                  s.name,
        "type":                  s.type.name,
        "geometry":              geo,
        "attack_type":           s.attack_type.name,
        "save_ability":          s.save_ability.name if s.attack_type == rpg.SpellAttack.Save else None,
        "range":                 s.range,
        "radius":                s.radius if uses_radius else None,
        "width":                 s.width  if uses_line   else None,
        "length":                s.length if uses_line   else None,
        "duration":              s.duration,
        "magic_damage_types":    magic_dmg,
        "physical_damage_types": phys_dmg,
        "terrain_effect":        s.terrain_effect if hasattr(s, 'terrain_effect') else None,
        "hatch_pattern":         s.hatch_pattern if hasattr(s, 'hatch_pattern') else None,
        "terrain_color":         s.terrain_color if hasattr(s, 'terrain_color') else None,
        "requires_concentration": s.requires_concentration,
        "moves_with_caster":     s.moves_with_caster,
        "grants_advantage_aura": s.grants_advantage_aura,
        "opens_doors":           s.opens_doors,
        "dispels_magic":         s.dispels_magic if hasattr(s, 'dispels_magic') else False,
        "light_level":           s.light_level,
        # N/day + Recharge (breath weapons / limited innate actions). uses_max==0
        # ⇒ unlimited; recharge_min==0 ⇒ no recharge. Mirrors the Weapon fields.
        "uses_max":              s.uses_max,
        "uses_remaining":        s.uses_remaining,
        "recharge_min":          s.recharge_min,
        "expended":              s.expended,
        # Power Word Kill / Stun HP gates + Mass Heal / Power Word Fortify pool.
        "instant_kill_threshold": getattr(s, "instant_kill_threshold", 0),
        "condition_hp_threshold": getattr(s, "condition_hp_threshold", 0),
        "hp_pool":                getattr(s, "hp_pool", 0),
        "pool_is_temp_hp":        getattr(s, "pool_is_temp_hp", False),
        "heal_to_full":           getattr(s, "heal_to_full", False),
        "ends_conditions":        list(getattr(s, "ends_conditions", [])),
    }


def _dict_to_spell(d: dict):
    """Convert a spell dict (from spells.json or a save) into a C++ rpg.Spell.

    SINGLE SOURCE OF TRUTH for dict -> Spell. The GUI spell-loading paths and the unit
    tests all funnel through here, so every spells.json field is parsed in exactly one
    place. (This logic used to be duplicated in a near-identical method inside main.py;
    new fields were only added to that copy, which is how `school` and later
    `light_level` silently went missing here and broke school/lighting in tests.)
    """
    s = rpg.Spell()
    s.name         = d.get("name",         "Unnamed Spell")
    s.type         = getattr(rpg.SpellType,     d.get("type",         "Harm"),     rpg.SpellType.Harm)
    s.geometry     = getattr(rpg.SpellGeometry, d.get("geometry",     "Single"),   rpg.SpellGeometry.Single)
    s.attack_type  = getattr(rpg.SpellAttack,   d.get("attack_type",  "AttackRoll"), rpg.SpellAttack.AttackRoll)
    s.save_ability = getattr(rpg.SaveAbility,   d.get("save_ability") or "SaveDex", rpg.SaveAbility.SaveDex)
    # spells.json stores the school lowercase ("enchantment"); the enum members are capitalized
    # ("Enchantment"). Normalize so getattr resolves (and save-file round-trips of the capitalized
    # enum name still work). Was silently NONE for every spells.json spell before this.
    s.school       = getattr(rpg.SpellSchool,   d.get("school",       "NONE").capitalize(), rpg.SpellSchool.NONE)
    s.range        = int(d.get("range")  or 30)
    s.radius       = int(d.get("radius") or 10)
    s.width        = int(d.get("width")  or  5)
    s.length       = int(d.get("length") or 30)
    s.duration     = int(d.get("duration",   1))
    # Light-emitting spells (Darkness, Daylight, Fog Cloud, Light): the engine only
    # places a light effect when light_level >= 0 (spell.hpp default is -1 = none).
    s.light_level  = int(d.get("light_level", -1))

    # Parse damage types — handle both new (object) and old (string) formats.
    # Route each entry by its TYPE NAME, not by which list it came from: some data
    # (e.g. a Bludgeoning breath weapon) files a physical type under magic_damage_types.
    # A physical name parsed as MagicDamage raises AttributeError and crashes the whole
    # load, so classify by name and drop it in the correct bucket regardless of source.
    magic_rolls, phys_rolls = [], []
    for dmg in list(d.get("magic_damage_types", [])) + list(d.get("physical_damage_types", [])):
        if isinstance(dmg, dict):
            # New format: {"type": "Fire", "num_dice": 2, "die_size": 6, "bonus": 1}
            name     = dmg.get("type", "Fire")
            num_dice = int(dmg.get("num_dice", 1))
            die_size = int(dmg.get("die_size", 6))
            bonus    = int(dmg.get("bonus", 0))
        else:
            # Old format: just the string "Fire" — use spell-level num_dice/die_size
            name     = dmg
            num_dice = int(d.get("num_dice", 1))
            die_size = int(d.get("die_size", 6))
            bonus    = int(d.get("bonus", 0))
        if name in _PHYSICAL_DMG_NAMES:
            roll = rpg.PhysicalDamageRoll()
            roll.type = _parse_physical_damage(name)
            phys_rolls.append(roll)
        else:
            roll = rpg.MagicDamageRoll()
            roll.type = _parse_magic_damage(name)
            magic_rolls.append(roll)
        roll.num_dice, roll.die_size, roll.bonus = num_dice, die_size, bonus
    s.magic_damage_rolls = magic_rolls
    s.physical_damage_rolls = phys_rolls

    # Parse healing type (for Heal spells)
    healing_raw = d.get("healing_type")
    if healing_raw and isinstance(healing_raw, dict):
        healing = rpg.HealingRoll()
        healing.num_dice = int(healing_raw.get("num_dice", 1))
        healing.die_size = int(healing_raw.get("die_size", 6))
        healing.bonus = int(healing_raw.get("bonus", 0))
        s.healing_type = healing

    s.requires_concentration = d.get("requires_concentration", False)
    s.moves_with_caster = d.get("moves_with_caster", False)
    s.grants_advantage_aura = d.get("grants_advantage_aura", False)
    s.selective_targeting = d.get("selective_targeting", False)
    s.resource_name = d.get("resource_name", "") or ""
    s.resource_cost = int(d.get("resource_cost", 1))
    s.requires_los = d.get("requires_los", False)
    s.check_los_on_center = d.get("check_los_on_center", True)
    s.opens_doors = d.get("opens_doors", False)
    if hasattr(s, "dispels_magic"):
        s.dispels_magic = d.get("dispels_magic", False)
    # Power Word Kill / Stun HP gates and Mass Heal / Power Word Fortify HP pool.
    # Guarded with hasattr so an older compiled module still loads spells.json.
    if hasattr(s, "instant_kill_threshold"):
        s.instant_kill_threshold = int(d.get("instant_kill_threshold", 0))
    if hasattr(s, "condition_hp_threshold"):
        s.condition_hp_threshold = int(d.get("condition_hp_threshold", 0))
    if hasattr(s, "hp_pool"):
        s.hp_pool = int(d.get("hp_pool", 0))
    if hasattr(s, "pool_is_temp_hp"):
        s.pool_is_temp_hp = bool(d.get("pool_is_temp_hp", False))
    if hasattr(s, "heal_to_full"):
        s.heal_to_full = bool(d.get("heal_to_full", False))
    if hasattr(s, "ends_conditions"):
        s.ends_conditions = list(d.get("ends_conditions", []))
    s.level = int(d.get("level", 0))
    s.upcast_dice_bonus = int(d.get("upcast_dice_bonus", 0))
    s.num_targets = int(d.get("num_targets", 1))
    s.targets_per_upcast_level = int(d.get("targets_per_upcast_level", 0))
    s.effects_on_begin_turn = d.get("effects_on_begin_turn", True)
    s.effects_on_end_turn = d.get("effects_on_end_turn", False)

    # N/day + Recharge (breath weapons / limited innate actions). uses_max==0
    # ⇒ unlimited; recharge_min==0 ⇒ no recharge. uses_remaining defaults to
    # uses_max so a freshly-loaded spell starts full. Mirrors _dict_to_weapon.
    s.uses_max       = int(d.get("uses_max",       0))
    s.uses_remaining = int(d.get("uses_remaining", d.get("uses_max", 0)))
    s.recharge_min   = int(d.get("recharge_min",   0))
    s.expended       = bool(d.get("expended",      False))

    # Parse terrain effect (Grease, Spike Growth, etc.) onto the C++ Spell.
    # Cosmetic color/hatch stay in _spell_metadata for rendering.
    te = d.get("terrain_effect")
    if te:
        if te.get("type") == "Slipping":
            s.terrain_difficulty = rpg.TerrainDifficulty.Slipping
            s.slip_save_dc       = int(te.get("slip_save_dc", 10))
            s.slip_distance_feet = int(te.get("slip_distance_feet", 5))
        else:
            m = float(te.get("multiplier", 0.5))
            s.terrain_difficulty = (rpg.TerrainDifficulty.Quartered if m <= 0.25
                                    else rpg.TerrainDifficulty.Halved)

    # Parse spell conditions - same format as weapon conditions
    conditions = []
    for cond_entry in d.get("conditions", []):
        if isinstance(cond_entry, dict):
            # Full condition spec: {"condition_name": "Paralyzed", "condition_duration": 10, ...}
            c = rpg.AttackCondition()
            c.condition_name = cond_entry.get("condition_name", "")
            c.condition_duration = int(cond_entry.get("condition_duration", 0))
            c.push_ft = int(cond_entry.get("push_ft", 0))
            c.save_repeat_turns = int(cond_entry.get("save_repeat_turns", 1))
            # Condition requires a save if it has a save_ability specified
            c.requires_save = ("save_ability" in cond_entry)
            # Parse save_ability string (target's save) - defaults to spell's save_ability
            save_ability_str = cond_entry.get("save_ability")
            if save_ability_str:
                try:
                    c.save_ability = getattr(rpg.SaveAbility, save_ability_str)
                except AttributeError:
                    c.save_ability = s.save_ability  # fallback to spell's ability
            else:
                c.save_ability = s.save_ability  # use spell's ability as default
            # Parse save_dc_ability string (caster's ability for DC)
            save_dc_ability_str = cond_entry.get("save_dc_ability", "SaveSpellcasterMod")
            try:
                c.save_dc_ability = getattr(rpg.SaveAbility, save_dc_ability_str)
            except AttributeError:
                c.save_dc_ability = rpg.SaveAbility.SaveSpellcasterMod
            # on_damage: "end" ends the condition on any damage; "repeat_save" re-rolls at advantage
            od = str(cond_entry.get("on_damage", "") or "").lower()
            if od == "end":
                c.on_damage = rpg.OnDamage.End
            elif od in ("repeat_save", "repeatsave", "repeat-save"):
                c.on_damage = rpg.OnDamage.RepeatSave
            # Vistani Curse authoring: curse_kind (1=vuln, 2=weakness, 3=affliction) plus the
            # caster kickback (psychic damage to the Vistana when the curse ends).
            c.curse_kind = int(cond_entry.get("curse_kind", 0))
            c.kickback_dice = int(cond_entry.get("kickback_dice", 0))
            c.kickback_die_size = int(cond_entry.get("kickback_die_size", 0))
            kb_type_str = cond_entry.get("kickback_damage_type", "Psychic")
            try:
                c.kickback_damage_type = getattr(rpg.MagicDamage, kb_type_str)
            except AttributeError:
                c.kickback_damage_type = rpg.MagicDamage.Psychic
            # Damage-over-time / no-heal rider (generic; a spell-delivered poison, etc.).
            c.dot_dice = int(cond_entry.get("dot_dice", 0))
            c.dot_die_size = int(cond_entry.get("dot_die_size", 0))
            c.dot_flat_bonus = int(cond_entry.get("dot_flat_bonus", 0))
            c.dot_damage_type = _parse_magic_damage(cond_entry.get("dot_damage_type", "Poison"))
            c.prevents_healing = bool(cond_entry.get("prevents_healing", False))
            conditions.append(c)
        else:
            # Simple string: just the condition name (legacy support)
            c = rpg.AttackCondition()
            c.condition_name = str(cond_entry)
            c.condition_duration = 0  # will use spell duration
            c.push_ft = 0
            c.save_repeat_turns = 1
            c.requires_save = False
            c.save_ability = s.save_ability  # use spell's ability for legacy conditions
            c.save_dc_ability = rpg.SaveAbility.SaveSpellcasterMod
            conditions.append(c)
    s.conditions = conditions

    # Parse teleportation spell fields
    s.teleportation_spell = d.get("teleportation_spell", False)
    s.max_teleport_targets = int(d.get("max_teleport_targets", 0))
    s.teleport_range_ft = int(d.get("teleport_range_ft", 0))

    # Parse casting time
    casting_time_str = d.get("casting_time", "Action")
    s.casting_time = getattr(rpg.CastingTime, casting_time_str, rpg.CastingTime.Action)

    return s


# ─────────────────────────────────────────────────────────────────────────────
#  Item serialization helpers (carried consumables — items.json)
# ─────────────────────────────────────────────────────────────────────────────
#  Mirrors the spell path: items.json is the authored catalog, _dict_to_item is
#  the single place a record becomes an rpg.Item, and _item_to_dict is the single
#  place one goes back to JSON (saves). New Item fields must be added to BOTH or
#  they silently reset on save/reload.


def _dict_to_item(d: dict):
    """Convert an item dict (from items.json or a save) into a C++ rpg.Item."""
    it = rpg.Item()
    it.name = d.get("name", "Unnamed Item")
    it.description = d.get("description", "")

    it.type = getattr(rpg.ItemType, d.get("type", "Heal"), rpg.ItemType.Heal)
    it.action_type = getattr(rpg.ItemAction, d.get("action_type", "BonusAction"),
                             rpg.ItemAction.BonusAction)

    # Reach for administering a potion to someone else (0 = self only); the throwing
    # range for a Thrown item (20 ft for the flasks, 15 ft for a Net).
    it.range = int(d.get("range", 5))

    healing_raw = d.get("healing_type")
    if isinstance(healing_raw, dict):
        h = rpg.HealingRoll()
        h.num_dice = int(healing_raw.get("num_dice", 0))
        h.die_size = int(healing_raw.get("die_size", 4))
        h.bonus    = int(healing_raw.get("bonus", 0))
        it.healing = h

    # ── Thrown items (Acid, Alchemist's Fire, Holy Water, Net) ───────────────
    # The save DC is derived from the thrower (8 + DEX mod + PB), so it is never authored.
    # A Net has no damage_type block at all: it deals no damage, it just tangles.
    damage_raw = d.get("damage_type")
    if isinstance(damage_raw, dict):
        dmg = rpg.MagicDamageRoll()
        dmg.type     = getattr(rpg.MagicDamage, damage_raw.get("type", "Acid"), rpg.MagicDamage.Acid)
        dmg.num_dice = int(damage_raw.get("num_dice", 0))
        dmg.die_size = int(damage_raw.get("die_size", 6))
        dmg.bonus    = int(damage_raw.get("bonus", 0))
        it.damage = dmg

    it.save_ability = getattr(rpg.SaveAbility, d.get("save_ability", "SaveDex"),
                              rpg.SaveAbility.SaveDex)
    it.condition_applied    = d.get("condition_applied", "") or ""
    it.only_vs_fiend_undead = bool(d.get("only_vs_fiend_undead", False))
    it.max_target_size      = int(d.get("max_target_size", 0))
    it.escape_dc            = int(d.get("escape_dc", 0))

    it.quantity = int(d.get("quantity", 1))
    it.consumable = bool(d.get("consumable", True))
    it.sprite_path = d.get("sprite_path", "") or ""
    return it


def _item_to_dict(it) -> dict:
    """Convert an rpg.Item to a plain dict (save / dialog display)."""
    return {
        "name": it.name,
        "description": it.description,
        "type": it.type.name,
        "action_type": it.action_type.name,
        "range": it.range,
        "healing_type": {
            "num_dice": it.healing.num_dice,
            "die_size": it.healing.die_size,
            "bonus":    it.healing.bonus,
        },
        "damage_type": {
            "type":     it.damage.type.name,
            "num_dice": it.damage.num_dice,
            "die_size": it.damage.die_size,
            "bonus":    it.damage.bonus,
        },
        "save_ability":         it.save_ability.name,
        "condition_applied":    it.condition_applied,
        "only_vs_fiend_undead": it.only_vs_fiend_undead,
        "max_target_size":      it.max_target_size,
        "escape_dc":            it.escape_dc,
        "quantity": it.quantity,
        "consumable": it.consumable,
        "sprite_path": it.sprite_path,
    }
