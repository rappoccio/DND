// ─────────────────────────────────────────────────────────────────────────────
//  serialization_mappings.hpp  –  JSON mappings shared by the two snapshot TUs
// ─────────────────────────────────────────────────────────────────────────────
//
//  PRIVATE to combat_serialization.cpp (the engine snapshot, R5) and
//  battle_map_serialization.cpp (the board snapshot, MULTIPLAYER_PLAN.md M6.2).
//  Both carry Cells, Weapons and Spells by value, so the mappings live here once
//  rather than twice. Nothing else includes this file: see combat_serialization.cpp
//  for why these mappings are kept out of the public headers.
//
#pragma once

#include "cell.hpp"
#include "condition.hpp"
#include "damage.hpp"
#include "spell.hpp"
#include "weapon.hpp"

#include <nlohmann/json.hpp>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Type ↔ JSON mappings
//
//  NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT generates ADL to_json/from_json
//  for a type it does not have to be a member of, and — the "_WITH_DEFAULT" half —
//  fills any field a payload OMITS from a default-constructed instance rather than
//  zeroing it. That is exactly the forward-compatible contract R4c hand-wrote for
//  ActiveAgentCondition (`j.value(key, default)` per field); the macro is the same
//  semantics without ~1,500 lines of it. Enums round-trip through their underlying
//  integer, which is nlohmann's default enum handling and matches R4c's explicit
//  static_cast<int>.
//
//  Order matters: a struct's mapping must be declared before any struct that
//  embeds it, so these run leaf-first.
// ─────────────────────────────────────────────────────────────────────────────

// ── Leaves: geometry, dice, conditions ───────────────────────────────────────
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(Cell, col, row, z)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(MagicDamageRoll, type, num_dice, die_size, bonus)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(PhysicalDamageRoll, type, num_dice, die_size, bonus)
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(HealingRoll, num_dice, die_size, bonus)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    AttackCondition,
    condition_name, condition_duration, push_ft, save_repeat_turns,
    save_ability, save_dc_ability, requires_save, save_at_end_of_turn, on_damage,
    dot_dice, dot_die_size, dot_flat_bonus, dot_damage_type, prevents_healing,
    contested, escape_dc,
    curse_kind, kickback_dice, kickback_die_size, kickback_damage_type)

// ── Weapon / Spell ───────────────────────────────────────────────────────────
// Both are carried BY VALUE inside engine state (InFlightAttack::w snapshots the
// resolved weapon mid-attack; ActiveEffect::spell is the cast-time copy a persistent
// effect ticks from, possibly already rewritten by upcasting or Transmuted metamagic).
// Neither can be recovered by name from weapons.json / spells.json after the fact, so
// both round-trip in full.
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    Weapon,
    name, type, reach_ft, normal_range_ft, long_range_ft,
    finesse, thrown, quantity, returns_after_throw, pact_weapon, psychic_blade,
    proficient, off_hand, two_handed, heavy, light, is_shield, mastery,
    auto_hit_if_grappled, save_for_damage, save_for_damage_ability,
    auto_use_when_grappling, permanently_armed,
    uses_max, uses_remaining, recharge_min, expended,
    magicDamageRolls, physicalDamageRolls,
    damage_dice, damage_dice_count, damage_modifier, range_short_feet, range_long_feet,
    bonus_hit, bonus_damage, ac_bonus,
    conditions, condition_rider, sprite_path)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    Spell,
    name, type, geometry, attack_type, save_ability, school, casting_time,
    range, radius, width, length, duration,
    num_targets, targets_per_upcast_level,
    magic_damage_rolls, physical_damage_rolls, healing_type,
    terrain_difficulty, slip_save_dc, slip_distance_feet, light_level,
    requires_concentration, moves_with_caster, requires_los, check_los_on_center,
    requires_sight, selective_targeting, grants_advantage_aura,
    level, upcast_dice_bonus, uses_max, uses_remaining, recharge_min, expended,
    resource_name, resource_cost, opens_doors, dispels_magic,
    instant_kill_threshold, condition_hp_threshold,
    hp_pool, pool_is_temp_hp, heal_to_full, revives_dead, animates_dead,
    creates_movement_ward, ward_blocks_living, creates_wall_terrain, binds_creature,
    ends_conditions,
    teleportation_spell, max_teleport_targets, teleport_range_ft,
    effects_on_begin_turn, effects_on_end_turn, conditions)

} // namespace rpg
