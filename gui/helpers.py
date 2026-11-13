# ─────────────────────────────────────────────────────────────────────────────
#  helpers.py  –  Utility functions for D&D mechanics and serialization
# ─────────────────────────────────────────────────────────────────────────────

import json
import math
import os

import rpg_battle_map as rpg


# ─────────────────────────────────────────────────────────────────────────────
#  Grid edges (terrain file form; no pygame dependency)
# ─────────────────────────────────────────────────────────────────────────────

def edge_key(e):
    """(c, r, "E"|"S") for an rpg.Edge, the terrain file's edge form."""
    return (int(e.cell.col), int(e.cell.row), "E" if e.side == rpg.EdgeSide.East else "S")


def edge_from_key(key):
    """rpg.Edge for a (c, r, "E"|"S") key."""
    c, r, s = key
    return rpg.Edge(rpg.Cell(int(c), int(r)),
                    rpg.EdgeSide.East if s == "E" else rpg.EdgeSide.South)


def door_touch_cells(door):
    """The cells a creature acts on ``door`` from: a cell door's own cells, or both
    cells either side of each of an edge door's edges."""
    if door.cells:
        return list(door.cells)
    out = []
    for e in door.edges:
        c, r, s = edge_key(e)
        out += [rpg.Cell(c, r), rpg.Cell(c + 1, r) if s == "E" else rpg.Cell(c, r + 1)]
    return out


# ─────────────────────────────────────────────────────────────────────────────
#  Placement rules (shared by the GUI and unit tests; no pygame dependency)
# ─────────────────────────────────────────────────────────────────────────────

def can_place_agent(bm, cell, size, exclude_idx=-1) -> bool:
    """Return True if a size×size agent fits at top-left `cell`: in bounds, not on a
    wall/blocked cell, and not overlapping another LIVE agent's footprint. A tombstoned
    agent (removed_from_play, e.g. a dismissed summon) no longer occupies its cell, and
    neither does a corpse (conditions.dead) — mirroring the engine's agentOccupancy, so a
    dead agent's square frees up for others to move into or be placed on. An unconscious
    (downed but not dead) body still blocks, like a living creature."""
    cols, rows = bm.grid_cols, bm.grid_rows
    if cell.col < 0 or cell.row < 0:
        return False
    if cell.col + size > cols or cell.row + size > rows:
        return False
    if bm.is_blocked(cell, size):
        return False
    for i, pt in enumerate(bm.placed_agents):
        if i == exclude_idx or pt.removed_from_play or pt.conditions.dead:
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
      · natural-weapon to-hit = Ranger's spell-attack modifier (PB + WIS mod)
      · natural-weapon damage bonus = PB
    The to-hit/damage targets are RAW-fixed regardless of the beast's own ability mod,
    so weapon bonus_hit/bonus_damage cancel the mod the engine will re-add.

    What depends on being commanded is NOT baked in here: the engine sets it each turn
    (CombatEngine::beginTurn) — Exceptional Training's Bonus Action Dash/Disengage/Hide (L7)
    and Bestial Fury's second strike (L11) only on a commanded turn — and picks the L7
    Force-or-natural damage type per attack (determineAdvantage).
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
        "num_attacks": 1,
        "has_cunning_action": False,
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
    return stats, weapon


def compute_summon_loadout(block: dict, slot_level: int, pb: int, spell_ability_mod: int):
    """Build a (stats_dict, weapon_dict) for a 2024 "Summon X" spirit from its base `block`
    (one entry of summons.json), scaled to the slot level the spell was cast with and
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


def _creature_mask(names) -> int:
    """["Fiend", "Undead"] → the CreatureTypeBit mask (RAVENLOFT M2); unknown names are dropped."""
    mask = 0
    for n in names or []:
        bit = getattr(rpg.CreatureType, str(n), None)
        if bit is not None:
            mask |= int(bit)
    return mask


def _creature_names(mask: int) -> list:
    return [name for name, bit in rpg.CreatureType.__members__.items() if mask & int(bit)]


def _damage_roll_to_dict(r) -> dict:
    """A weapon damage entry; vs_creature_types only when the entry is limited to some types."""
    d = {"type": r.type.name, "num_dice": r.num_dice, "die_size": r.die_size}
    if r.vs_creature_mask:
        d["vs_creature_types"] = _creature_names(r.vs_creature_mask)
    return d


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
        "physical_damage_types": [_damage_roll_to_dict(r) for r in w.physical_damage_types],
        "magic_damage_types":    [_damage_roll_to_dict(r) for r in w.magic_damage_types],
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
        # Enspelled weapons (the Mace of Terror): uses left and `attuned` travel with the weapon.
        **_item_spells_to_dict(w.item_spells),
    }


# Body parts rather than carried weapons, on any creature: they can't be dropped or disarmed.
# "Unnamed" is the placeholder a nameless stat-block attack loads as — never a real item.
_NATURAL_WEAPON_NAMES = frozenset({"Bite", "Claw", "Unnamed"})


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
    # By name too: saved creatures store their own copy of the flag, False on every Bite and Claw
    # written before this rule, and a catalog edit would not reach them.
    w.permanently_armed = (bool(d.get("permanently_armed", False))
                           or w.name in _NATURAL_WEAPON_NAMES)
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
        r.vs_creature_mask = _creature_mask(entry.get("vs_creature_types"))
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
        r.vs_creature_mask = _creature_mask(entry.get("vs_creature_types"))
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

    w.item_spells = _item_spells_from_dict(d)
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

    a.item_spells = _item_spells_from_dict(d)
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
        **_item_spells_to_dict(a.item_spells),
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
    "cantrip_dice_per_tier": 0,      # cantrips: extra dice per tier (char level 5/11/17)
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

    out = {
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
        "excludes_caster":       s.excludes_caster,
        "effects_on_begin_turn": s.effects_on_begin_turn,
        "effects_on_end_turn":   s.effects_on_end_turn,
        "effects_on_enter":      s.effects_on_enter,
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
        "revives_dead":           getattr(s, "revives_dead", False),
        "animates_dead":          getattr(s, "animates_dead", False),
        "binds_creature":         getattr(s, "binds_creature", False),
        "creates_movement_ward":  getattr(s, "creates_movement_ward", False),
        "ward_blocks_living":     getattr(s, "ward_blocks_living", False),
        "creates_wall_terrain":   getattr(s, "creates_wall_terrain", False),
        "ends_conditions":        list(getattr(s, "ends_conditions", [])),
        # Enspelled items (ENSPELLED_ITEMS_PLAN.md E2): the granting item's tag.
        "item_source":            int(s.item_source),
        "item_slot":              s.item_slot,
        "item_name":              s.item_name,
        "item_charge_cost":       s.item_charge_cost,
    }
    # RAVENLOFT M4/M5/M8 — only when set, so ordinary spells' dicts are unchanged.
    if s.affects_creature_mask:
        out["affects_creature_types"] = _creature_names(s.affects_creature_mask)
    if s.no_damage_on_save:
        out["no_damage_on_save"] = True
    if s.weapon_rider.num_dice > 0:
        out["weapon_rider"] = {"type": s.weapon_rider.type.name, "num_dice": s.weapon_rider.num_dice,
                               "die_size": s.weapon_rider.die_size}
    return out


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
    s.excludes_caster = d.get("excludes_caster", False)
    s.resource_name = d.get("resource_name", "") or ""
    s.resource_cost = int(d.get("resource_cost", 1))
    # Enspelled items (ENSPELLED_ITEMS_PLAN.md E2): the granting item's tag; NoItem by default.
    s.item_source      = rpg.SpellItemSource(int(d.get("item_source", 0)))
    s.item_slot        = int(d.get("item_slot", -1))
    s.item_name        = d.get("item_name", "") or ""
    s.item_charge_cost = int(d.get("item_charge_cost", 0))
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
    if hasattr(s, "revives_dead"):
        s.revives_dead = bool(d.get("revives_dead", False))
    if hasattr(s, "animates_dead"):
        s.animates_dead = bool(d.get("animates_dead", False))
    if hasattr(s, "binds_creature"):
        s.binds_creature = bool(d.get("binds_creature", False))
    if hasattr(s, "creates_movement_ward"):
        s.creates_movement_ward = bool(d.get("creates_movement_ward", False))
    if hasattr(s, "ward_blocks_living"):
        s.ward_blocks_living = bool(d.get("ward_blocks_living", False))
    if hasattr(s, "creates_wall_terrain"):
        s.creates_wall_terrain = bool(d.get("creates_wall_terrain", False))
    if hasattr(s, "ends_conditions"):
        s.ends_conditions = list(d.get("ends_conditions", []))
    s.level = int(d.get("level", 0))
    s.upcast_dice_bonus = int(d.get("upcast_dice_bonus", 0))
    s.cantrip_dice_per_tier = int(d.get("cantrip_dice_per_tier", 0))
    s.num_targets = int(d.get("num_targets", 1))
    s.targets_per_upcast_level = int(d.get("targets_per_upcast_level", 0))
    s.effects_on_begin_turn = d.get("effects_on_begin_turn", True)
    s.effects_on_end_turn = d.get("effects_on_end_turn", False)
    s.effects_on_enter = d.get("effects_on_enter", True)
    # RAVENLOFT M4/M8: only these creature types are affected; M5: a weapon damage rider.
    s.affects_creature_mask = _creature_mask(d.get("affects_creature_types"))
    s.no_damage_on_save = bool(d.get("no_damage_on_save", False))
    rider = d.get("weapon_rider")
    if isinstance(rider, dict):
        r = rpg.MagicDamageRoll()
        r.type = _parse_magic_damage(rider.get("type", "Fire"))
        r.num_dice = int(rider.get("num_dice", 1))
        r.die_size = int(rider.get("die_size", 6))
        s.weapon_rider = r

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
            # Hold Person / Hold Monster RAW: the periodic save is rolled at the END of the
            # affected creature's turn, not the start. Guarded with hasattr so an older
            # compiled module still loads spells.json (falls back to start-of-turn saves).
            if hasattr(c, "save_at_end_of_turn"):
                c.save_at_end_of_turn = bool(cond_entry.get("save_at_end_of_turn", False))
            # RAVENLOFT M8: lands on a successful save instead (Disruption's Frightened).
            c.applies_on_save_success = bool(cond_entry.get("applies_on_save_success", False))
            # Condition requires a save if it names its own save_ability, or if the spell itself
            # is a Save spell: a failed spell save is what lands the condition (Hold Person, Web,
            # Entangle carry no per-condition save_ability, and used to apply unconditionally).
            # The engine reuses the spell's own save roll for these — no second roll.
            c.requires_save = bool(cond_entry.get(
                "requires_save",
                "save_ability" in cond_entry or d.get("attack_type") == "Save"))
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


# ─────────────────────────────────────────────────────────────────────────────
#  Enspelled-item fields (plans/ENSPELLED_ITEMS_PLAN.md) — shared by items, weapons
#  and armor. The JSON keys are flat on the item record:
#    requires_attunement, spell_dc, spell_attack, item_spell_groups, charges {max,
#    regain}, charge_spells, spell_overrides          — authored
#    attuned, item_spell_uses {spell: n}, charges.current — runtime, saved with the item
#  A record with neither item_spell_uses nor charges.current is fresh from the catalog
#  and starts full.
# ─────────────────────────────────────────────────────────────────────────────

def _int_keyed_groups(raw) -> dict:
    """{"2": ["Fear"]} → {2: ["Fear"]}; anything malformed is dropped."""
    out = {}
    for k, names in (raw or {}).items():
        try:
            n = int(k)
        except (TypeError, ValueError):
            continue
        if n > 0 and isinstance(names, list):
            out[n] = [str(x) for x in names]
    return out


def _item_spells_from_dict(d: dict):
    """Build an rpg.ItemSpells from an item/weapon/armor record."""
    s = rpg.ItemSpells()
    s.requires_attunement = bool(d.get("requires_attunement", False))
    s.spell_dc     = int(d.get("spell_dc", 0) or 0)
    s.spell_attack = int(d.get("spell_attack", 0) or 0)
    s.spell_groups  = _int_keyed_groups(d.get("item_spell_groups"))
    s.charge_spells = _int_keyed_groups(d.get("charge_spells"))
    charges = d.get("charges") if isinstance(d.get("charges"), dict) else {}
    s.charges_max    = int(charges.get("max", 0) or 0)
    s.charges_regain = str(charges.get("regain", "long_rest") or "long_rest")
    overrides = d.get("spell_overrides")
    s.spell_overrides_json = json.dumps(overrides) if overrides else ""
    _item_bonuses_from_dict(s.bonuses, d.get("item_bonuses"))
    s.luck_max = int(d.get("luck_points", 0) or 0)                 # RAVENLOFT M6
    s.slot_regain = bool(d.get("regain_slot", False))              # RAVENLOFT M10
    s.attuned = bool(d.get("attuned", False))
    s.refill()
    if "luck_remaining" in d:
        s.luck = max(0, min(int(d["luck_remaining"]), s.luck_max))
    s.slot_regain_used = bool(d.get("slot_regain_used", False))
    saved_uses = d.get("item_spell_uses")
    if isinstance(saved_uses, dict):
        uses = dict(s.uses_remaining)
        for name, n in saved_uses.items():
            if name in uses:
                uses[name] = max(0, min(int(n), uses[name]))
        s.uses_remaining = uses
    if "current" in charges:
        s.charges = max(0, min(int(charges["current"]), s.charges_max))
    return s


# RAVENLOFT_ITEMS_PLAN.md M1: "item_bonuses": {"ac": 2, "initiative": 2, "saves": 2,
# "spell_attack": 2, "spell_dc": 1, "spell_class": "Warlock"} — every key optional.
_ITEM_BONUS_KEYS = ("ac", "initiative", "saves", "spell_attack", "spell_dc")


def _item_bonuses_from_dict(b, raw):
    """Fill the rpg.ItemBonuses ``b`` (in place) from an item record's item_bonuses dict."""
    raw = raw if isinstance(raw, dict) else {}
    for k in _ITEM_BONUS_KEYS:
        setattr(b, k, int(raw.get(k, 0) or 0))
    cls = raw.get("spell_class")
    b.spell_class = int(getattr(rpg.CharacterClass, cls, 0)) if isinstance(cls, str) else int(cls or 0)


def _item_bonuses_to_dict(b) -> dict:
    out = {k: getattr(b, k) for k in _ITEM_BONUS_KEYS if getattr(b, k)}
    if out and b.spell_class:
        out["spell_class"] = rpg.CharacterClass(b.spell_class).name
    return out


def item_bonuses_line(b) -> str:
    """'+2 AC, +2 saves, +2 spell attack' — '' when the item has no bonuses."""
    if not b.any():
        return ""
    labels = {"ac": "AC", "initiative": "Initiative", "saves": "saves",
              "spell_attack": "spell attack", "spell_dc": "spell save DC"}
    line = ", ".join(f"{getattr(b, k):+d} {labels[k]}" for k in _ITEM_BONUS_KEYS if getattr(b, k))
    if b.spell_class and (b.spell_attack or b.spell_dc):
        line += f" ({rpg.CharacterClass(b.spell_class).name} spells)"
    return line


def _item_spells_to_dict(s) -> dict:
    """The JSON keys for an rpg.ItemSpells, to merge into its item's record ({} if none)."""
    if not s.magical():
        return {}
    out = {
        "requires_attunement": s.requires_attunement,
        "attuned":             s.attuned,
        "item_spell_groups":   {str(n): list(names) for n, names in s.spell_groups.items()},
        "item_spell_uses":     dict(s.uses_remaining),
    }
    if s.spell_dc:
        out["spell_dc"] = s.spell_dc
    if s.spell_attack:
        out["spell_attack"] = s.spell_attack
    if s.charge_spells:
        out["charge_spells"] = {str(n): list(names) for n, names in s.charge_spells.items()}
    if s.charges_max:
        out["charges"] = {"max": s.charges_max, "regain": s.charges_regain,
                          "current": s.charges}
    if s.spell_overrides_json:
        out["spell_overrides"] = json.loads(s.spell_overrides_json)
    bonuses = _item_bonuses_to_dict(s.bonuses)
    if bonuses:
        out["item_bonuses"] = bonuses
    if s.luck_max:
        out["luck_points"], out["luck_remaining"] = s.luck_max, s.luck
    if s.slot_regain:
        out["regain_slot"], out["slot_regain_used"] = True, s.slot_regain_used
    return out


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
    # RAVENLOFT M11 (Potion of Heroism): temp HP and a condition on the drinker.
    it.temp_hp = int(d.get("temp_hp", 0) or 0)
    it.applies_condition = str(d.get("applies_condition", "") or "")
    it.applies_condition_turns = int(d.get("applies_condition_turns", 0) or 0)

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

    # Keys (plans/ITEMS_AND_CHESTS_PLAN.md P1): what this key unlocks.
    it.opens = [str(o) for o in d.get("opens", []) or []]

    it.quantity = int(d.get("quantity", 1))
    it.consumable = bool(d.get("consumable", True))
    it.sprite_path = d.get("sprite_path", "") or ""
    it.item_spells = _item_spells_from_dict(d)
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
        "opens":                list(it.opens),
        # RAVENLOFT M11 (Potion of Heroism)
        "temp_hp":                 it.temp_hp,
        "applies_condition":       it.applies_condition,
        "applies_condition_turns": it.applies_condition_turns,
        "quantity": it.quantity,
        "consumable": it.consumable,
        "sprite_path": it.sprite_path,
        **_item_spells_to_dict(it.item_spells),
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Enspelled items E3 — the grant / revoke lifecycle (plans/ENSPELLED_ITEMS_PLAN.md)
#
#  A creature's item-granted spells are derived, never authored: they are rebuilt from
#  what it carries (D9) every time that can change. The engine owns the cost state on
#  the item itself (D0), so a rebuild never touches uses or charges — it only re-tags
#  spell entries with the item's current slot.
# ─────────────────────────────────────────────────────────────────────────────

def is_item_spell(sp) -> bool:
    """True for a spell granted by a carried item (tagged by item_spell_entries)."""
    return sp.item_source != rpg.SpellItemSource.NoItem


def _item_spell_key(sp) -> tuple:
    return (int(sp.item_source), sp.item_slot, sp.item_name, sp.name, sp.item_charge_cost)


def item_spell_entries(combat, bm, idx: int, spell_catalog: dict) -> list:
    """The tagged Spells creature ``idx`` gets from its carried items right now.

    Items rows, weapons rows and worn armor slots (D9) whose ItemSpells is active (D5:
    attuned, or no attunement needed). Each N/day group spell and each pool spell becomes
    one entry — a spell in both models gets both. ``spell_catalog`` maps name → spells.json
    record; the item's spell_overrides (D3a) are applied over a copy. A name missing from
    the catalog is skipped with a warning."""
    out = []
    sources = (
        (rpg.SpellItemSource.FromItem,   combat.get_agent_items(bm, idx)),
        (rpg.SpellItemSource.FromWeapon, combat.get_agent_weapons(bm, idx)),
        (rpg.SpellItemSource.FromArmor,  combat.get_agent_armor(bm, idx)),
    )
    stats = combat.get_agent_stats(bm, idx)
    for source, rows in sources:
        for slot, row in enumerate(rows):
            spells = row.item_spells
            if not row.name or not spells.active():
                continue
            if (source == rpg.SpellItemSource.FromItem and row.type == rpg.ItemType.Scroll
                    and not all(can_read_scroll(stats, n) for n in spells.spell_names())):
                continue                 # SPELL_SCROLLS S5: unreadable, so not offered
            overrides = json.loads(spells.spell_overrides_json) if spells.spell_overrides_json else {}
            grants = [(name, 0) for _, names in sorted(spells.spell_groups.items()) for name in names]
            if spells.charges_max > 0:
                grants += [(name, cost) for cost, names in sorted(spells.charge_spells.items())
                           for name in names]
            for name, cost in grants:
                record = spell_catalog.get(name)
                if record is None:
                    print(f"⚠ {row.name}: spell '{name}' not in spells.json — not granted")
                    continue
                sp = _dict_to_spell({**record, **overrides.get(name, {})})
                sp.item_source, sp.item_slot = source, slot
                sp.item_name, sp.item_charge_cost = row.name, cost
                out.append(sp)
    return out


def sync_item_spells(combat, bm, idx: int, spell_catalog: dict):
    """Rebuild creature ``idx``'s item-granted spell entries from what it carries now (E3).

    Its own spells keep their order; item entries that still match are kept in place,
    stale ones (the item left, moved slot, or lost attunement) are dropped and new ones
    appended. Returns None when nothing changed, else ``moved``: for each new spell index,
    the old index it came from (None for a newly granted entry) — so per-index metadata
    can follow."""
    if not (0 <= idx < len(bm.placed_agents)):
        return None
    combat.discard_spent_scrolls(bm, idx)   # SPELL_SCROLLS S3: a used scroll is gone
    current = list(combat.get_agent_spells(bm, idx))
    wanted = item_spell_entries(combat, bm, idx, spell_catalog)
    wanted_keys = [_item_spell_key(sp) for sp in wanted]
    kept, moved, have = [], [], set()
    for j, sp in enumerate(current):
        if is_item_spell(sp):
            k = _item_spell_key(sp)
            if k not in wanted_keys or k in have:
                continue
            have.add(k)
        kept.append(sp)
        moved.append(j)
    for k, sp in zip(wanted_keys, wanted):
        if k not in have:
            have.add(k)
            kept.append(sp)
            moved.append(None)
    if moved == list(range(len(current))):
        return None
    combat.set_agent_spells(bm, idx, kept)
    return moved


# ─────────────────────────────────────────────────────────────────────────────
#  Spell scrolls (plans/SPELL_SCROLLS_PLAN.md)
#
#  A made scroll is an items.json "Spell Scroll" record carrying one use of one
#  spell (item_spell_groups {"1": [spell]}) at a fixed spell_dc / spell_attack
#  (S1, S2). It is readable only by a creature with the spell on one of its class
#  lists, or with the DM's reads_any_scroll tick (S5).
# ─────────────────────────────────────────────────────────────────────────────

SPELL_SCROLL = "Spell Scroll"

# S2 — 2024 DMG Spell Scroll table: spell level → (save DC, attack bonus).
SCROLL_DC_TABLE = {0: (13, 5), 1: (13, 5), 2: (13, 5), 3: (15, 7), 4: (15, 7),
                   5: (17, 9), 6: (17, 9), 7: (18, 10), 8: (18, 10), 9: (19, 11)}

# Class lists for real spells in spells.json that spells_raw.json (the SRD import) lacks.
_EXTRA_SPELL_CLASSES = {
    "Arms of Hadar":      {"Warlock"},
    "Blade Ward":         {"Bard", "Sorcerer", "Warlock", "Wizard"},
    "Crusader's Mantle":  {"Paladin"},
    "Booming Blade":      {"Sorcerer", "Warlock", "Wizard"},
    "Hunger of Hadar":    {"Warlock"},
    "Mind Sliver":        {"Sorcerer", "Warlock", "Wizard"},
    "Power Word Fortify": {"Bard", "Cleric"},
    "Silvery Barbs":      {"Bard", "Sorcerer", "Wizard"},
    "Summon Aberration":  {"Warlock", "Wizard"},
    "Summon Beast":       {"Druid", "Ranger"},
    "Summon Celestial":   {"Cleric", "Paladin"},
    "Summon Construct":   {"Wizard"},
    "Summon Elemental":   {"Druid", "Ranger", "Wizard"},
    "Summon Fey":         {"Druid", "Ranger", "Warlock", "Wizard"},
    "Summon Fiend":       {"Warlock", "Wizard"},
    "Summon Shadowspawn": {"Warlock", "Wizard"},
    "Summon Undead":      {"Warlock", "Wizard"},
    "Toll the Dead":      {"Cleric", "Warlock", "Wizard"},
}

_spell_classes_cache = None


def spell_classes(name: str) -> set:
    """The classes whose spell list has ``name`` (spells_raw.json + the extras). Empty for
    a monster ability or anything unknown — no scroll can hold those."""
    global _spell_classes_cache
    if _spell_classes_cache is None:
        _spell_classes_cache = {k: set(v) for k, v in _EXTRA_SPELL_CLASSES.items()}
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "spells_raw.json")
        try:
            with open(path) as f:
                for r in json.load(f):
                    names = {c.get("name") for c in r.get("classes") or [] if c.get("name")}
                    if names:
                        _spell_classes_cache.setdefault(r.get("name"), set()).update(names)
        except (OSError, ValueError) as e:
            print(f"⚠ spells_raw.json unreadable ({e}) — scroll class lists limited to extras")
    return _spell_classes_cache.get(name, set())


def scroll_spell_names(all_spells) -> list:
    """The spells.json names a scroll can hold (S1): those on some class list, by level then name."""
    recs = [d for d in all_spells if spell_classes(d.get("name", ""))]
    return [d["name"] for d in sorted(recs, key=lambda d: (int(d.get("level", 0) or 0), d["name"]))]


def creature_spell_lists(stats) -> set:
    """The class spell lists ``stats`` casts from: each class with levels, plus Wizard for an
    Eldritch Knight or Arcane Trickster (their spells come from the Wizard list)."""
    out = {name for name, c in rpg.CharacterClass.__members__.items()
           if name != "None" and stats.has_class(c)}
    if stats.has_class(rpg.CharacterClass.Fighter) \
            and stats.fighter_subclass == rpg.FighterSubclass.EldritchKnight:
        out.add("Wizard")
    if stats.has_class(rpg.CharacterClass.Rogue) \
            and stats.rogue_subclass == rpg.RogueSubclass.ArcaneTrickster:
        out.add("Wizard")
    return out


def can_read_scroll(stats, spell: str) -> bool:
    """S5: the spell is on one of the creature's class lists, or the DM ticked reads_any_scroll."""
    return bool(stats.reads_any_scroll) or bool(spell_classes(spell) & creature_spell_lists(stats))


def make_spell_scroll(template: dict, spell_record: dict, dc: int | None = None,
                      attack: int | None = None) -> dict:
    """A made scroll's record (S1): the catalog ``template`` holding one use of ``spell_record``
    at ``dc`` / ``attack``, defaulting from the DMG table by spell level (S2); a ``dc`` alone
    gets attack ``dc − 8``."""
    name = spell_record["name"]
    level = max(0, min(9, int(spell_record.get("level", 0) or 0)))
    d_dc, d_atk = SCROLL_DC_TABLE[level]
    rec = {k: v for k, v in template.items()
           if k not in ("item_spell_groups", "item_spell_uses", "spell_dc", "spell_attack")}
    rec.update({
        "name": f"{SPELL_SCROLL} ({name})",
        "type": "Scroll",
        "action_type": "NoAction",
        "consumable": True,
        "quantity": 1,
        "item_spell_groups": {"1": [name]},
        "spell_dc": int(dc) if dc else d_dc,
        # A DC with no attack pairs as the table does: attack = DC − 8 (A3).
        "spell_attack": int(attack) if attack else (int(dc) - 8 if dc else d_atk),
    })
    return rec


def parse_scroll_dc(text: str):
    """The DM's "DC [attack]" answer for a scroll: "15" → (15, 7) (the DMG table always pairs
    attack = DC − 8), "15 +6" / "15/6" / "DC 15 +6" → (15, 6). None if it isn't that shape."""
    t = text.strip().upper()
    if t.startswith("DC"):
        t = t[2:]
    try:
        nums = [int(p) for p in t.replace("/", " ").replace(",", " ").replace("+", " ").split()]
    except ValueError:
        return None
    if len(nums) == 1:
        nums.append(nums[0] - 8)
    if len(nums) != 2 or not (1 <= nums[0] <= 30) or not (0 <= nums[1] <= 20):
        return None
    return nums[0], nums[1]


def is_blank_scroll(d: dict) -> bool:
    """The bare catalog "Spell Scroll" (no spell chosen yet) — SS2 asks for one before it lands."""
    return d.get("type") == "Scroll" and not d.get("item_spell_groups")


# ─────────────────────────────────────────────────────────────────────────────
#  Enspelled items E4 — what the GUI shows (plans/ENSPELLED_ITEMS_PLAN.md)
# ─────────────────────────────────────────────────────────────────────────────

ATTUNEMENT_LIMIT = 3   # D5: more than this many attuned items warns, it never blocks


def item_spells_for(combat, bm, idx: int, sp):
    """The ItemSpells a tagged spell is cast from, or None — Python's rules::itemSpellsFor."""
    rows = {rpg.SpellItemSource.FromItem:   combat.get_agent_items,
            rpg.SpellItemSource.FromWeapon: combat.get_agent_weapons,
            rpg.SpellItemSource.FromArmor:  combat.get_agent_armor}.get(sp.item_source)
    if rows is None or sp.item_slot < 0:
        return None
    carried = rows(bm, idx)
    if sp.item_slot >= len(carried) or carried[sp.item_slot].name != sp.item_name:
        return None
    return carried[sp.item_slot].item_spells


def item_spell_status(s, spell: str, charge_cost: int = 0) -> str:
    """'2/2', 'at will' (D3), or '3 ch · charges 5/7' for a pool spell (D4)."""
    if charge_cost > 0:
        return f"{charge_cost} ch · charges {s.charges}/{s.charges_max}"
    n = s.uses_per_day(spell)
    if n == rpg.ItemSpells.AT_WILL:
        return "at will"
    return f"{s.uses_remaining.get(spell, 0)}/{n}"


def is_scroll(row) -> bool:
    """A made spell scroll: an rpg.Item of type Scroll that holds a spell (SPELL_SCROLLS_PLAN.md)."""
    return getattr(row, "type", None) == rpg.ItemType.Scroll and not row.item_spells.empty()


def scroll_line(s) -> str:
    """A scroll's one summary line (SS3): 'DC 15 · +7'. The spell is already in its name."""
    return f"DC {s.spell_dc} · +{s.spell_attack}"


def item_spell_label(combat, bm, idx: int, sp) -> str:
    """The spell-menu row for an item-granted spell: 'Fear (Mace of Terror) 2/2', or for a
    spell scroll 'Fear (scroll, DC 15)'."""
    s = item_spells_for(combat, bm, idx, sp)
    if s is not None and sp.item_source == rpg.SpellItemSource.FromItem:
        row = combat.get_agent_items(bm, idx)[sp.item_slot]
        if is_scroll(row):
            return f"{sp.name} (scroll, DC {s.spell_dc})"
    tail = f" {item_spell_status(s, sp.name, sp.item_charge_cost)}" if s is not None else ""
    return f"{sp.name} ({sp.item_name}){tail}"


def item_spells_summary(s) -> list[str]:
    """One line per cost group of an item's spells, for item info and sheets:
    ['Fear 2/2'], ['Protection from Evil and Good at will', 'Cure Wounds 1/1'],
    ['charges 5/7: Burning Hands (1), Fireball (3)']. A line of passive bonuses comes first
    ('+2 AC, +2 saves', RAVENLOFT M1). [] for an ordinary item."""
    bonus = [l for l in (item_bonuses_line(s.bonuses),
                         f"luck {s.luck}/{s.luck_max}" if s.luck_max else "",
                         ("slot regain used" if s.slot_regain_used else "slot regain ready")
                         if s.slot_regain else "") if l]
    if s.empty():
        return bonus
    lines = list(bonus)
    lines += [f"{name} {item_spell_status(s, name)}"
             for _, names in sorted(s.spell_groups.items(), reverse=True) for name in names]
    if s.charges_max > 0 and s.charge_spells:
        pool = ", ".join(f"{name} ({cost})"
                         for cost, names in sorted(s.charge_spells.items()) for name in names)
        lines.append(f"charges {s.charges}/{s.charges_max}: {pool}")
    return lines


def item_dict_summary(d: dict) -> list[str]:
    """item_spells_summary for an item/weapon/armor record (catalog or dialog row); a spell
    scroll's is its one 'DC 15 · +7' line (SS3)."""
    s = _item_spells_from_dict(d)
    if d.get("type") == "Scroll" and not s.empty():
        return [scroll_line(s)]
    return item_spells_summary(s)


def attuned_count(combat, bm, idx: int, kinds=("items", "weapons", "armor")) -> int:
    """How many carried items (D9) creature ``idx`` is attuned to, over ``kinds`` — a dialog
    editing one kind passes the other two, and counts its own rows itself."""
    getters = {"items": combat.get_agent_items, "weapons": combat.get_agent_weapons,
               "armor": combat.get_agent_armor}
    rows = [r for k in kinds for r in getters[k](bm, idx)]
    return sum(1 for r in rows
               if r.name and r.item_spells.requires_attunement and r.item_spells.attuned)


def item_slot_regain_ready(combat, bm, idx: int) -> bool:
    """RAVENLOFT M10: a carried, switched-on item can regain a slot now (the Rod of the Pact
    Keeper unused since the last long rest) and the creature has a slot to regain."""
    if not (0 <= idx < len(bm.placed_agents)):
        return False
    rows = (list(combat.get_agent_items(bm, idx)) + list(combat.get_agent_weapons(bm, idx))
            + list(combat.get_agent_armor(bm, idx)))
    if not any(r.name and r.item_spells.slot_regain and not r.item_spells.slot_regain_used
               and r.item_spells.attuned_or_free() for r in rows):
        return False
    s = combat.get_agent_stats(bm, idx)
    return any(rem < mx for rem, mx in zip(s.spell_slots_remaining, s.spell_slots_max))


def attunement_warning(n: int) -> str:
    """'' at or under the limit, else the D5 warning text."""
    return (f"⚠ attuned to {n} items (limit {ATTUNEMENT_LIMIT})"
            if n > ATTUNEMENT_LIMIT else "")
