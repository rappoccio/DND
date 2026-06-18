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
    agent (removed_from_play, e.g. a dismissed summon) no longer occupies its cell."""
    cols, rows = bm.grid_cols, bm.grid_rows
    if cell.col < 0 or cell.row < 0:
        return False
    if cell.col + size > cols or cell.row + size > rows:
        return False
    if bm.is_blocked(cell, size):
        return False
    for i, pt in enumerate(bm.placed_agents):
        if i == exclude_idx or pt.removed_from_play:
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
    "thrown":          False,
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
        "proficient":       w.proficient,
        "off_hand":         w.off_hand,
        "two_handed":       w.two_handed,
        "heavy":            w.heavy,
        "light":            w.light,
        "is_shield":        w.is_shield,
        "mastery":          w.mastery.name,
        "bonus_hit":        w.bonus_hit,
        "bonus_damage":     w.bonus_damage,
        "ac_bonus":         w.ac_bonus,
        "physical_damage_types": [{"type": r.type.name, "num_dice": r.num_dice, "die_size": r.die_size}
                                   for r in w.physical_damage_types],
        "magic_damage_types":    [{"type": r.type.name, "num_dice": r.num_dice, "die_size": r.die_size}
                                   for r in w.magic_damage_types],
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
    w.proficient      = bool(d.get("proficient",      True))
    w.off_hand        = bool(d.get("off_hand",        False))
    w.two_handed      = bool(d.get("two_handed",      False))
    w.heavy           = bool(d.get("heavy",           False))
    w.light           = bool(d.get("light",           False))
    w.is_shield       = bool(d.get("is_shield",       False))
    w.mastery         = _parse_mastery(d.get("mastery", ""))
    w.bonus_hit       = int(d.get("bonus_hit",       0))
    w.bonus_damage    = int(d.get("bonus_damage",    0))
    w.ac_bonus        = int(d.get("ac_bonus",        0))

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
    uses_line   = geo == "Line"

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
    }


def _dict_to_spell(d: dict):
    s = rpg.Spell()
    s.name         = d.get("name",         "Unnamed Spell")
    s.type         = getattr(rpg.SpellType,     d.get("type",         "Harm"),     rpg.SpellType.Harm)
    s.geometry     = getattr(rpg.SpellGeometry, d.get("geometry",     "Single"),   rpg.SpellGeometry.Single)
    s.attack_type  = getattr(rpg.SpellAttack,   d.get("attack_type",  "AttackRoll"), rpg.SpellAttack.AttackRoll)
    s.save_ability = getattr(rpg.SaveAbility,   d.get("save_ability") or "SaveDex", rpg.SaveAbility.SaveDex)
    # spells.json stores the school lowercase ("enchantment"); the enum members are capitalized.
    s.school       = getattr(rpg.SpellSchool,   d.get("school",       "NONE").capitalize(), rpg.SpellSchool.NONE)
    s.range        = int(d.get("range")  or 30)
    s.radius       = int(d.get("radius") or 10)
    s.width        = int(d.get("width")  or  5)
    s.length       = int(d.get("length") or 30)
    s.duration     = int(d.get("duration",   1))

    # Parse magic damage types - handle both new (object) and old (string) formats
    magic_dmg_raw = d.get("magic_damage_types", [])
    magic_rolls = []
    for dmg in magic_dmg_raw:
        if isinstance(dmg, dict):
            # New format: {"type": "Fire", "num_dice": 2, "die_size": 6}
            dmg_type = _parse_magic_damage(dmg.get("type", "Fire"))
            roll = rpg.MagicDamageRoll()
            roll.type = dmg_type
            roll.num_dice = int(dmg.get("num_dice", 1))
            roll.die_size = int(dmg.get("die_size", 6))
            magic_rolls.append(roll)
        else:
            # Old format: just the string "Fire"
            # Use spell-level num_dice/die_size
            dmg_type = _parse_magic_damage(dmg)
            roll = rpg.MagicDamageRoll()
            roll.type = dmg_type
            roll.num_dice = int(d.get("num_dice", 1))
            roll.die_size = int(d.get("die_size", 6))
            magic_rolls.append(roll)
    s.magic_damage_rolls = magic_rolls

    # Parse physical damage types - handle both new (object) and old (string) formats
    phys_dmg_raw = d.get("physical_damage_types", [])
    phys_rolls = []
    for dmg in phys_dmg_raw:
        if isinstance(dmg, dict):
            # New format: {"type": "Slashing", "num_dice": 1, "die_size": 8}
            dmg_type = _parse_physical_damage(dmg.get("type", "Bludgeoning"))
            roll = rpg.PhysicalDamageRoll()
            roll.type = dmg_type
            roll.num_dice = int(dmg.get("num_dice", 1))
            roll.die_size = int(dmg.get("die_size", 6))
            phys_rolls.append(roll)
        else:
            # Old format: just the string "Slashing"
            # Use spell-level num_dice/die_size
            dmg_type = _parse_physical_damage(dmg)
            roll = rpg.PhysicalDamageRoll()
            roll.type = dmg_type
            roll.num_dice = int(d.get("num_dice", 1))
            roll.die_size = int(d.get("die_size", 6))
            phys_rolls.append(roll)
    s.physical_damage_rolls = phys_rolls

    s.requires_concentration = d.get("requires_concentration", False)

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
            # Condition requires a save if it has a save_ability specified (and it's not just defaulting to spell's ability)
            c.requires_save = ("save_ability" in cond_entry)
            conditions.append(c)
        else:
            # Simple string: just the condition name (legacy support)
            c = rpg.AttackCondition()
            c.condition_name = str(cond_entry)
            c.condition_duration = 0  # will use spell duration
            c.push_ft = 0
            c.save_repeat_turns = 1
            c.save_ability = s.save_ability  # use spell's ability for legacy conditions
            c.save_dc_ability = rpg.SaveAbility.SaveSpellcasterMod
            conditions.append(c)
    s.conditions = conditions

    return s
