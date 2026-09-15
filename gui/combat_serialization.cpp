// ─────────────────────────────────────────────────────────────────────────────
//  combat_serialization.cpp  –  CombatEngine snapshot() / restore()
// ─────────────────────────────────────────────────────────────────────────────
//
//  R5 of COMBAT_REFACTOR_PLAN.md — the phase MULTIPLAYER_PLAN.md's "Engine-state
//  serialization" TODO is blocked on. Two halves live here:
//
//    · The JSON mapping for every combat data type the engine still holds by
//      value — the combat_types.hpp result/action/in-flight structs plus the
//      Weapon / Spell / AttackCondition / *DamageRoll leaves they embed.
//    · CombatEngine::snapshot() / restore(), which walk the engine's members and
//      delegate to those mappings and to the sub-engines' own to_json/from_json
//      (CombatContext R3, VisibilityService R4a, MovementController R4b,
//      ConditionTracker R4c — each already serializable per plan decision #4).
//
//  Why a TU of its own, and why no header: nothing outside this file calls these
//  mappings. Putting them in a header would hand every combat TU an nlohmann
//  dependency and a few thousand lines of template instantiation for no caller.
//  The only declarations the rest of the tree sees are snapshot()/restore()/
//  snapshotJson()/restoreJson() on CombatEngine in combat.hpp.
//
//  ── What is NOT in a snapshot, and why ──────────────────────────────────────
//   · Host callbacks — ctx_.logger_, ctx_.render_attack_hook_, decider_. These
//     are rebound by whoever owns the process; restore() PRESERVES the live ones
//     rather than nulling them (see restore()).
//   · NPC visual-event plumbing — ctx_.npc_recording_ / npc_visual_events_.
//     Transient GUI animation state, drained every turn (CombatContext already
//     excludes them; noted here because this is where a reader looks).
//   · The npc_automation_config.json cache (npc_config_loaded_ and friends) and
//     npc_nn_level_warned_. A lazy file cache and a one-shot log guard — not
//     gameplay state; both re-derive themselves on demand after a restore.
//
//  ── What a snapshot is NOT ──────────────────────────────────────────────────
//  It holds ENGINE state only. Agent HP/positions/conditions flags, terrain and
//  lighting live in BattleMap and are saved separately (main.py's _save_agents /
//  _save_terrain / _save_lighting). A snapshot is keyed by RAW agent index, so it
//  must be restored against the same BattleMap agent list it was taken from — the
//  encounter save compacts indices (it skips summons and removed agents), so the
//  two are deliberately different artifacts, not interchangeable ones.
//
#include "combat.hpp"
#include "battle_map.hpp"   // full MovementType / TerrainDifficulty definitions for the enum mappings

#include <nlohmann/json.hpp>

#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

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

// ── Declared actions ─────────────────────────────────────────────────────────
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    Attack,
    attacker_idx, target_idx, weapon_idx, is_offhand, no_ability_damage,
    attack_slot, opportunity, thrown)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    SpellAction,
    caster_idx, spell_idx, slot_level, target_indices,
    aoe_col, aoe_row, aoe_col2, aoe_row2,
    metamagic, metamagic2, careful_targets, transmuted_damage_type,
    damage_type_override, chromatic_leap_targets, free_cast,
    command_word, curse_choice, overchannel,
    dispel_condition_ids, dispel_spell_effect_ids, dispel_terrain_ids,
    ward_creature_mask, ward_traps, forcecage_sealed)

// ── Results ──────────────────────────────────────────────────────────────────
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    AttackResult,
    valid, d20, d20_primary, attack_mod, total_roll, target_ac,
    critical, fumble, disadvantage, advantage, hit,
    dice_results, damage_mod, total_damage,
    magic_damage_types, physical_damage_types, damage_breakdown, magic_damage_dealt,
    hp_before, hp_after, target_down, push_ft_applied,
    weapon_thrown, thrown_item_id)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    SpellTargetResult,
    target_idx, saved, hit, d20, attack_mod, total_roll, target_ac, critical,
    dice_results, damage_mod, total_damage, total_healing,
    hp_before, hp_after, target_down,
    save_d20, save_mod, save_dc, log_message,
    concentration_checked, concentration_lost, push_ft_applied)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    SpellResult,
    valid, spell_idx, spell_name, attack_type, target_results,
    concentration_replaced, prev_concentration_spell,
    terrain_effect_ids, light_effect_ids, cast_as_bonus_action)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    TurnStartResult, turn_skipped, skip_reason, save_roll_message)

// ── Reaction system ──────────────────────────────────────────────────────────
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(ReactionOption, kind, index, label, feature)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    ReactionCtx, window, reactor_idx, source_idx, options, source_cell,
    d20_value, spell_idx, damage)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(PendingDecision, active, ctx)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(ProvokeEvent, reactor, left_cell, step)

// ── Pre-rolls carried across a suspended window ──────────────────────────────
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    SpellToHit, d20, attack_mod, total_roll, target_ac, critical, hit)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    SpellSave, target_idx, d20, save_mod, bonus, total, dc, saved, auto_fail, ability)

// ── In-flight (park/resume) state ────────────────────────────────────────────
// MULTIPLAYER_PLAN.md's TODO asks for these by name: "cast_stack_ (in-flight casts)
// plus any parked attack / reaction decision state, so a restore can resume a
// suspended reaction window". All four flows round-trip in full, cursors included.
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    InFlightCast,
    active, interactive, action, reactors, cursor, countered, result,
    has_preroll, preroll_target, preroll, attack_window_done,
    has_save_preroll, save_prerolls, save_window_built, savefail_pairs, savefail_cursor,
    is_counterspell, counter_target_caster)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    InFlightMove,
    active, interactive, mover_idx, origin, dest, type,
    provokes, cursor, mover_down, mover_halted, halt_cell, results)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    InFlightAttack,
    active, interactive, action, w, r, adv, dis, auto_hit,
    unerring_fired, peerless_fired, onhit_offered,
    d20_reactors, d20_cursor, d20_window_built,
    can_use_brutal_strike, tgt_incapacitated_at_attack, tgt_unconscious_at_attack,
    consume_vex, consume_sap, consume_distracted, attacker_was_hidden,
    atk_sz, tgt_sz, was_thrown)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    InFlightTurn, active, interactive, agent_idx, result, reactors, cursor, window_built)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    NpcTurnState,
    active, agent_idx, target_idx, weapon_idx, attacks_remaining, phase,
    cast_launched, cast_moving, pending_segments,
    conceal_route, conceal_spell_idx, conceal_move_launched, conceal_act_launched,
    flee_move_launched, resolved_strategy)

// ── Persistent spell effects ─────────────────────────────────────────────────
NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    ActiveEffect, caster_idx, target_idx, spell, turns_remaining)

// ─────────────────────────────────────────────────────────────────────────────
//  Int-keyed container helpers
//
//  Written as arrays of named-field objects rather than leaning on nlohmann's
//  non-string-key map support — the same choice R3 made for agent_portent_round_used_
//  and R4b for the movement budgets, so every int-keyed map in a save file reads the
//  same way. zoneAppliedTurn_'s key is a packed (effect_id, agent_idx) int64 and is
//  stored RAW, mirroring how VisibilityService (R4a) stores its packed pair key: an
//  unpacked key could be reinterpreted wrongly on the way back.
// ─────────────────────────────────────────────────────────────────────────────
namespace {

template <typename Key, typename Value>
nlohmann::json keyedMapToJson(const std::unordered_map<Key, Value>& m,
                              const char* key_name, const char* value_name)
{
    nlohmann::json out = nlohmann::json::array();
    for (const auto& [key, value] : m)
        out.push_back({{key_name, key}, {value_name, value}});
    return out;
}

template <typename Key, typename Value>
void keyedMapFromJson(const nlohmann::json& j, const char* field,
                      const char* key_name, const char* value_name,
                      std::unordered_map<Key, Value>& out)
{
    out.clear();
    auto it = j.find(field);
    if (it == j.end() || !it->is_array()) return;
    for (const auto& entry : *it) {
        if (!entry.contains(key_name) || !entry.contains(value_name)) continue;
        out[entry[key_name].get<Key>()] = entry[value_name].get<Value>();
    }
}

// Read an optional struct field, leaving `out` at its current value when the payload
// omits it. The struct mappings above already default per FIELD; this is the same
// contract one level up, for a whole member.
template <typename T>
void readMember(const nlohmann::json& j, const char* field, T& out)
{
    if (auto it = j.find(field); it != j.end())
        out = it->get<T>();
}

} // namespace

// ─────────────────────────────────────────────────────────────────────────────
//  CombatEngine::snapshot / restore
// ─────────────────────────────────────────────────────────────────────────────

nlohmann::json CombatEngine::snapshot() const
{
    nlohmann::json j;
    j["version"] = kSnapshotVersion;

    // Sub-engines serialize themselves (plan decision #4 — each landed with its own
    // to_json in the commit that created it).
    j["context"]    = ctx_.to_json();
    j["movement"]   = mv_.to_json();
    j["conditions"] = conditions_.to_json();
    j["visibility"] = vis_.to_json();

    // Engine-owned state that never got a sub-engine of its own.
    j["agent_turns"]       = keyedMapToJson(agentTurns_, "agent", "turns");
    j["active_effects"]    = activeEffects_;
    j["safe_targets"]      = keyedMapToJson(safeTargets_, "caster", "targets");
    j["zone_applied_turn"] = keyedMapToJson(zoneAppliedTurn_, "key", "turn");
    j["death_burst_fired"] = deathBurstFired_;

    // Park/resume state, so a restore can pick a suspended reaction window back up.
    j["pending_decision"] = pending_decision_;
    j["in_flight_move"]   = in_flight_move_;
    j["in_flight_attack"] = in_flight_attack_;
    j["in_flight_turn"]   = in_flight_turn_;
    j["cast_stack"]       = cast_stack_;
    j["npc_turn"]         = npc_turn_;

    // Last-result readbacks. These are outputs, not inputs to any rule — but the GUI
    // polls them right after a flow finishes, so a restore taken between "the attack
    // resolved" and "the panel read it" would otherwise show a blank result.
    j["last_attack_result"]  = last_attack_result_;
    j["last_cast_result"]    = last_cast_result_;
    j["last_cast_countered"] = last_cast_countered_;

    return j;
}

bool CombatEngine::restore(const nlohmann::json& j)
{
    if (!j.is_object()) return false;
    if (j.value("version", 0) > kSnapshotVersion) return false;   // written by a newer engine

    // The host callbacks are process state, not save state: CombatContext::from_json
    // builds a fresh context with logger_/render_attack_hook_ null, so carry the live
    // ones across rather than silently muting the combat log and the NPC animation hook.
    // decider_ is left alone for the same reason (it is never touched below).
    if (auto it = j.find("context"); it != j.end()) {
        MessageLogger* keep_logger = ctx_.logger_;
        auto           keep_hook   = ctx_.render_attack_hook_;
        ctx_ = CombatContext::from_json(*it);
        ctx_.logger_             = keep_logger;
        ctx_.render_attack_hook_ = std::move(keep_hook);
    }
    if (auto it = j.find("movement");   it != j.end()) mv_.from_json(*it);
    if (auto it = j.find("conditions"); it != j.end()) conditions_.from_json(*it);
    if (auto it = j.find("visibility"); it != j.end()) vis_.from_json(*it);

    keyedMapFromJson(j, "agent_turns",       "agent",  "turns",   agentTurns_);
    keyedMapFromJson(j, "safe_targets",      "caster", "targets", safeTargets_);
    keyedMapFromJson(j, "zone_applied_turn", "key",    "turn",    zoneAppliedTurn_);

    activeEffects_.clear();
    readMember(j, "active_effects", activeEffects_);
    deathBurstFired_.clear();
    readMember(j, "death_burst_fired", deathBurstFired_);

    pending_decision_  = {};
    in_flight_move_    = {};
    in_flight_attack_  = {};
    in_flight_turn_    = {};
    npc_turn_          = {};
    cast_stack_.clear();
    readMember(j, "pending_decision", pending_decision_);
    readMember(j, "in_flight_move",   in_flight_move_);
    readMember(j, "in_flight_attack", in_flight_attack_);
    readMember(j, "in_flight_turn",   in_flight_turn_);
    readMember(j, "cast_stack",       cast_stack_);
    readMember(j, "npc_turn",         npc_turn_);

    last_attack_result_  = {};
    last_cast_result_    = {};
    readMember(j, "last_attack_result", last_attack_result_);
    readMember(j, "last_cast_result",   last_cast_result_);
    last_cast_countered_ = j.value("last_cast_countered", false);

    return true;
}

std::string CombatEngine::snapshotJson() const
{
    return snapshot().dump();
}

bool CombatEngine::restoreJson(const std::string& text)
{
    // A save file is untrusted input (hand-edited, truncated by a crash, written by a
    // different build) — a parse error must come back as false, not as an exception
    // crossing the pybind11 boundary.
    nlohmann::json j = nlohmann::json::parse(text, nullptr, /*allow_exceptions=*/false);
    if (j.is_discarded()) return false;
    try {
        return restore(j);
    } catch (const nlohmann::json::exception&) {
        // A well-formed document with the wrong SHAPE (a string where an array belongs)
        // throws out of one of the get<T>() calls above. The engine is left partially
        // restored; the caller's contract is to treat false as "reload from scratch".
        return false;
    }
}

} // namespace rpg
