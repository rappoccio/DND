# ─────────────────────────────────────────────────────────────────────────────
#  helpers.py  –  Utility functions for D&D mechanics and serialization
# ─────────────────────────────────────────────────────────────────────────────

import rpg_battle_map as rpg


# ─────────────────────────────────────────────────────────────────────────────
#  D&D mechanics helpers
# ─────────────────────────────────────────────────────────────────────────────

def _dnd_mod(score: int) -> int:
    """Return the D&D ability modifier for a given score (floor((score-10)/2))."""
    return (score - 10) // 2

def _mod_str(score: int) -> str:
    m = _dnd_mod(score)
    return f"+{m}" if m >= 0 else str(m)


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
        "bonus_hit":        w.bonus_hit,
        "bonus_damage":     w.bonus_damage,
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
    w.bonus_hit       = int(d.get("bonus_hit",       0))
    w.bonus_damage    = int(d.get("bonus_damage",    0))

    # Physical damage rolls
    w.physical_damage_types = []
    for entry in d.get("physical_damage_types", []):
        r = rpg.PhysicalDamageRoll()
        r.type     = _parse_physical_damage(entry.get("type", "Slashing"))
        r.num_dice = int(entry.get("num_dice", 1))
        r.die_size = int(entry.get("die_size", 6))
        w.physical_damage_types.append(r)

    # Magic damage rolls
    w.magic_damage_types = []
    for entry in d.get("magic_damage_types", []):
        r = rpg.MagicDamageRoll()
        r.type     = _parse_magic_damage(entry.get("type", "Fire"))
        r.num_dice = int(entry.get("num_dice", 1))
        r.die_size = int(entry.get("die_size", 6))
        w.magic_damage_types.append(r)

    return w


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
    return s
