// ─────────────────────────────────────────────────────────────────────────────
//  battle_map_serialization.cpp  –  BattleMap snapshot() / restore()
// ─────────────────────────────────────────────────────────────────────────────
//
//  MULTIPLAYER_PLAN.md M6.2: the board half of a mid-fight save. R5's engine snapshot
//  (combat_serialization.cpp) holds ENGINE state only, and left the board to "its own
//  save" — which, for everything below, did not exist:
//
//    · the terrain, light and spell effects a fight places, and their id counters (the
//      engine's active_effects refer to those ids);
//    · the per-cell terrain types (Wall of Stone overrides), multipliers and base light;
//    · every placed agent at its RAW index — summons and tombstones included — with the
//      state no encounter file writes: Conditions, the movement budgets, the fight-time
//      Stats fields (Hunter's Mark target, legendary actions left, Wild Shape's saved
//      form, …) and the loadout as it stands now.
//
//  ── restore() is an overlay ─────────────────────────────────────────────────
//  The caller has already built the agents (main.py's _load_agents, which also loads
//  sprites and the panel lists). restore() checks the basis — the same names and sizes,
//  at the same raw indices, on a grid of the same size — and then overwrites. It stages
//  everything first and commits only once the whole payload has been read, so a refusal
//  of any kind (basis, version, shape) changes nothing. A key the payload omits keeps
//  the value the caller built.
//
//  ── Stats and Conditions ────────────────────────────────────────────────────
//  Both are far past NLOHMANN_DEFINE_TYPE_*'s 64-member limit, so each is an X-macro
//  field list below. tests/test_board_snapshot.py parses agent.hpp and checks these
//  lists against the structs, so a field added to either struct without a line here
//  fails the suite instead of silently not being saved.
//
#include "battle_map.hpp"
#include "serialization_mappings.hpp"

#include <nlohmann/json.hpp>

#include <string>
#include <vector>

namespace rpg {

// ─────────────────────────────────────────────────────────────────────────────
//  Mappings for the types only the board carries
// ─────────────────────────────────────────────────────────────────────────────

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    Resource,
    name, current, max, short_rest_regen, long_rest_regen, duration, duration_remaining)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    Item,
    name, description, type, action_type, range, healing, damage, save_ability,
    condition_applied, only_vs_fiend_undead, max_target_size, escape_dc,
    quantity, consumable, sprite_path)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    Armor,
    name, description, ac_bonus, ac_base, grants_disadvantage, dex_mod_cap,
    magic_damage_multipliers, physical_damage_multipliers, damage_reduction,
    requires_strength, str_requirement)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    ActiveTerrainEffect,
    id, name, cell_indices, difficulty, turns_remaining, source_agent_idx,
    slip_save_dc, slip_distance_feet, spell_idx, cast_level, requires_concentration,
    anchor_agent_idx, anchor_radius_ft, spares_source_allies,
    ward_creature_mask, ward_traps, ward_all_living, sets_wall, saved_terrain)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    ActiveLightEffect,
    id, name, cell_indices, light_level, turns_remaining, source_agent_idx,
    see_through_agent_idx, anchor_agent_idx, anchor_radius_ft)

NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT(
    ActiveSpellEffect,
    caster_idx, spell_idx, spell, cells, turns_remaining, effect_id,
    anchor_agent_idx, cast_level)

namespace {

// ── Agent::Stats — every member, one X() each ────────────────────────────────
#define RPG_STATS_FIELDS(X) \
    X(str) X(dex) X(con) X(intel) X(wis) X(cha) X(hp_max) X(hp_cur) X(base_ac) \
    X(ac_temporary_modifications) X(speed_walk) X(speed_swim) X(speed_fly) \
    X(speed_climb) X(speed_burrow) X(speed_walk_remaining) X(speed_swim_remaining) \
    X(speed_fly_remaining) X(speed_climb_remaining) X(speed_burrow_remaining) \
    X(prof_bonus) X(save_prof_str) X(save_prof_dex) X(save_prof_con) \
    X(save_prof_intel) X(save_prof_wis) X(save_prof_cha) X(save_advantage_mask) \
    X(blessed) X(baned) X(hasted) X(haste_speed_bonus) X(haste_action_available) \
    X(aid_hp_bonus) X(longstrider_bonus) X(expeditious_retreat) \
    X(attackers_disadvantage) X(has_foresight) X(barkskin_ac_bonus) X(enfeebled) \
    X(size_damage_dice) X(immune_charm) X(mind_blank_psychic_saved) \
    X(regenerate_saved) X(stealth_prof) X(perception_prof) X(sleight_of_hand_prof) \
    X(sleight_of_hand_expertise) X(athletics_prof) X(athletics_expertise) \
    X(spellcasting_ability) X(num_attacks) X(multiattack) X(bonus_attacks_remaining) \
    X(bonus_actions_max) X(bonus_actions_remaining) X(has_cunning_action) \
    X(has_offhand_attack) X(can_cast_spell) X(has_sentinel) \
    X(has_branches_of_the_tree) X(initiative_prof) X(class_levels) X(character_class) \
    X(char_level) X(spell_slots_max) X(spell_slots_remaining) X(darkvision_range) \
    X(truesight_range) X(devilssight_range) X(blindsight_range) X(is_npc) \
    X(leveled_spell_cast_this_turn) X(temp_hp) X(rage_thp_source_idx) \
    X(available_hit_points) X(magic_damage_multipliers) X(physical_damage_multipliers) \
    X(resources) X(background) X(alignment) X(barbarian_subclass) \
    X(wild_heart_rage_choice) X(wild_heart_aspect) X(wild_heart_power) \
    X(rage_of_gods_used) X(brutal_strike_damage_dice) X(fighter_subclass) \
    X(druid_circle) X(monk_subclass) X(paladin_oath) X(wizard_subclass) \
    X(sorcerer_subclass) X(bard_subclass) X(metamagic_options) X(warlock_subclass) \
    X(rogue_subclass) X(cleric_subclass) X(blessed_strike) X(divine_intervention_lock) \
    X(ranger_subclass) X(hunter_prey) X(defensive_tactics) X(primal_companion) \
    X(hunters_mark_target) X(hunters_mark_dice) X(hunters_mark_die_size) \
    X(hunters_mark_damage_type) X(dread_ambusher) X(dreadful_strike_dice) \
    X(dreadful_strike_die_size) X(fey_dreadful_strikes) \
    X(fey_dreadful_strikes_die_size) X(wild_shape_active) X(wild_shape_form_name) \
    X(wild_shape_saved_ac) X(wild_shape_saved_str) X(wild_shape_saved_dex) \
    X(wild_shape_saved_con) X(wild_shape_saved_weapons) X(starry_form_active) \
    X(starry_constellation) X(land_type) X(wrath_of_sea_active) \
    X(lunar_radiance_available) X(improved_lunar_radiance_available) \
    X(primal_strike_active) X(primal_strike_damage_type) X(is_undead) X(is_fiend) \
    X(is_celestial) X(is_elemental) X(is_fey) X(is_aberration) X(is_vampire) \
    X(magic_resistance) X(cant_heal) X(death_burst_spell) X(regeneration_amount) \
    X(regen_interrupt_damage_types) X(regen_suppressed) X(legendary_resistance_max) \
    X(legendary_resistance_current) X(legendary_actions_max) \
    X(legendary_actions_current) X(has_legendary_actions) X(is_in_lair) \
    X(legendary_action_names) X(weapon_mastery) X(crit_threshold) \
    X(superiority_die_size) X(psionic_die_size) X(bardic_inspiration_die) \
    X(bardic_inspiration_die_size) X(primal_champion_applied) \
    X(monk_body_mind_applied) X(unarmed_damage_override) X(relentless_rage_dc) \
    X(sacred_weapon_bonus) X(sacred_weapon_turns) X(vow_of_enmity_target) \
    X(vow_of_enmity_turns) X(avenging_angel_turns) X(avenging_angel_prior_fly) \
    X(undying_sentinel_used) X(elder_champion_turns) X(living_legend_turns) \
    X(corona_of_light_turns) X(innate_sorcery_turns) X(draconic_hp_applied) \
    X(draconic_affinity_type) X(draconic_affinity_used_this_turn) \
    X(draconic_affinity_resist_turns) X(dragon_wings_active) X(overchannel_uses) \
    X(trance_of_order_turns) X(bastion_ward) X(revelation_in_flesh_turns) \
    X(revelation_prior_fly) X(revelation_prior_swim) X(revelation_prior_truesight) \
    X(mantle_majesty_turns) X(majestic_presence_turns) X(majesty_checked_this_turn) \
    X(majesty_disadv_save_vs) X(shield_active) X(wild_magic_shield_turns) \
    X(wild_magic_regen_turns) X(wild_magic_skip_next_turn) X(wild_magic_extra_action) \
    X(wild_magic_bonus_cast_turns) X(wild_magic_teleport_bonus_turns) \
    X(fiendish_resilience_type) X(portent_dice) X(eldritch_invocations) \
    X(fiendish_vigor_applied) X(feats) X(stolen_spell_names) X(elemental_adept_types) \
    X(irresistible_offense_ability) X(luck_points) X(luck_points_max) \
    X(boon_of_fate_used)

// ── Agent::Conditions — every member, one X() each ───────────────────────────
#define RPG_CONDITIONS_FIELDS(X) \
    X(dashing) X(dodging) X(disengaging) X(reaction_used) X(reactions_denied) \
    X(hidden) X(invisible) X(invisible_persists_on_action) X(attacked_while_invisible) \
    X(incapacitated) X(sanctuary_active) X(sanctuary_dc) X(concentrating) \
    X(concentrating_on) X(has_advantage) X(has_disadvantage) X(paralyzed) X(blinded) \
    X(deafened) X(stunned) X(prone) X(charmed) X(charmed_by) X(frightened) \
    X(slipped_this_turn) X(restrained) X(netted) X(net_escape_dc) X(forcecaged) \
    X(forcecage_dc) X(forcecage_sealed) X(burning) X(poisoned) X(petrified) \
    X(gaseous_form) X(unconscious) X(dead) X(death_save_successes) \
    X(death_save_failures) X(stabilized) X(grappled) X(grappler_idx) \
    X(grapple_escape_dc) X(grapple_range_ft) X(exhaustion_level) X(raging) \
    X(lion_aura_active) X(rage_of_gods_active) X(world_tree_long_teleport_used) \
    X(retaliation_available) X(retaliation_target_idx) X(reckless_attack) \
    X(reckless_reroll_available) X(riposte_available) X(sentinel_guard_available) \
    X(soul_of_vengeance_available) X(inspiring_smite_used) X(unerring_strike_used) \
    X(peerless_aim_used) X(peerless_aim_available) X(blink_steps_available) \
    X(colossus_slayer_used) X(horde_breaker_available) X(horde_breaker_used) \
    X(superior_prey_used) X(bestial_fury_used) X(fey_dreadful_strikes_used) \
    X(multiattack_def_hit_by) X(dreadful_strike_armed) X(dread_ambusher_used) \
    X(sudden_strike_available) X(berserker_frenzy_used) X(vitality_used_this_turn) \
    X(branches_speed_zeroed) X(brutal_strike_used_this_turn) \
    X(zealot_divine_fury_used) X(fanatical_focus_used) X(brutal_strike_available) \
    X(hamstrung) X(sundering_target_idx) X(staggered_next_save) X(radiant_soul_used) \
    X(sneak_attack_used) X(cunning_strike_available) X(steady_aim) \
    X(stunning_strike_available) X(stunning_strike_used) X(open_hand_rider_available) \
    X(open_hand_rider_used) X(quivering_palm_available) X(fleet_step_used) \
    X(divine_strike_available) X(divine_strike_used) X(psionic_strike_available) \
    X(psionic_strike_used) X(hand_of_harm_available) \
    X(elemental_attunement_move_available) X(hand_of_harm_used) \
    X(hand_of_harm_last_target) X(grappler_punch_grab_available) \
    X(grappler_punch_grab_used) X(divine_smite_available) X(divine_smite_used) \
    X(eldritch_smite_available) X(eldritch_smite_used) X(lifedrinker_used) \
    X(war_magic_used) X(eldritch_strike_by) X(guided_strike_available) \
    X(restore_balance_miss_available) X(maneuver_available) \
    X(maneuver_precision_available) X(goaded_by) X(distracted_by) X(disarmed) \
    X(disarmed_by) X(feint_target_idx) X(quick_toss_die_pending) X(sapped) \
    X(sap_used_this_turn) X(slowed) X(slow_used_this_turn) X(vex_target_idx) \
    X(vex_used_this_turn) X(push_available) X(push_used_this_turn) \
    X(poison_used_this_turn) X(topple_available) X(topple_used_this_turn) \
    X(savage_attacker_used_this_turn) X(tavern_brawler_push_used_this_turn) \
    X(crusher_push_used_this_turn) X(piercer_reroll_used_this_turn) \
    X(slasher_slow_used_this_turn) X(gwm_hew_available) X(battle_magic_available) \
    X(crusher_marked) X(crusher_marked_by) X(slasher_marked) X(slasher_marked_by) \
    X(cleave_available) X(cleave_used_this_turn) X(offhand_attack_used) \
    X(zealous_blessing) X(zealous_blessing_by) X(has_taken_turn_this_combat) \
    X(uncanny_metabolism_used_this_combat) X(superior_defense_active) \
    X(shadow_step_advantage) X(bonus_reach_available) X(cloak_of_shadows_active) \
    X(elemental_attunement_active)

// ── PlacedAgent — every member but `agent`, which is written as the name / size /
//    z / stats / conditions / movement keys of the same record ─────────────────────
#define RPG_PLACED_AGENT_FIELDS(X) \
    X(origin) X(weapons) X(spells) X(items) X(armor) X(summoner_idx) \
    X(removed_from_play) X(summon_spell) X(faction) X(controller) X(on_deck) \
    X(is_npc_automated) X(npc_automation_difficulty_level) X(npc_automation_strategy)

template <typename T>
nlohmann::json fieldsToJson(const T& v);

template <>
nlohmann::json fieldsToJson(const Agent::Stats& v)
{
    nlohmann::json j = nlohmann::json::object();
#define X(f) j[#f] = v.f;
    RPG_STATS_FIELDS(X)
#undef X
    return j;
}

template <>
nlohmann::json fieldsToJson(const Agent::Conditions& v)
{
    nlohmann::json j = nlohmann::json::object();
#define X(f) j[#f] = v.f;
    RPG_CONDITIONS_FIELDS(X)
#undef X
    return j;
}

// Overwrite each field the payload carries; a field it omits keeps v's value. False when
// the payload is not an object; a field of the wrong shape throws a
// nlohmann::json::exception, which restore() catches.
bool fieldsFromJson(const nlohmann::json& j, Agent::Stats& v)
{
    if (!j.is_object()) return false;
#define X(f) if (auto it = j.find(#f); it != j.end()) it->get_to(v.f);
    RPG_STATS_FIELDS(X)
#undef X
    return true;
}

bool fieldsFromJson(const nlohmann::json& j, Agent::Conditions& v)
{
    if (!j.is_object()) return false;
#define X(f) if (auto it = j.find(#f); it != j.end()) it->get_to(v.f);
    RPG_CONDITIONS_FIELDS(X)
#undef X
    return true;
}

// Read an optional member, leaving `out` as it is when the payload omits it.
template <typename T>
void readMember(const nlohmann::json& j, const char* field, T& out)
{
    if (auto it = j.find(field); it != j.end())
        it->get_to(out);
}

// Everything restore() writes to one agent, read in full before any of it is applied.
struct StagedAgent {
    PlacedAgent         pa;      // a copy; pa.agent still points at the live agent
    int                 z{0};
    Agent::Stats        stats;
    Agent::Conditions   conditions;
    std::array<int, 4>  movement{};
};

} // namespace

// ─────────────────────────────────────────────────────────────────────────────
//  BattleMap::snapshot / restore
// ─────────────────────────────────────────────────────────────────────────────

nlohmann::json BattleMap::snapshot() const
{
    nlohmann::json j;
    j["version"] = kBoardSnapshotVersion;
    j["cols"]    = cols_;
    j["rows"]    = rows_;

    j["terrain_effects"]     = activeTerrainEffects_;
    j["next_terrain_id"]     = nextEffectId_;
    j["light_effects"]       = activeLightEffects_;
    j["next_light_id"]       = nextLightEffectId_;
    j["spell_effects"]       = activeSpellEffects_;
    j["next_spell_id"]       = nextSpellEffectId_;
    j["terrain_type"]        = terrainType_;
    j["terrain_mult"]        = terrainMult_;
    j["base_light"]          = baseVisibilityLevel_;

    nlohmann::json agents = nlohmann::json::array();
    for (const auto& pa : placedAgents_) {
        nlohmann::json a;
        a["name"] = std::string(pa.agent->name());
        a["size"] = pa.agent->getSize();
        a["z"]    = pa.agent->getZ();
#define X(f) a[#f] = pa.f;
        RPG_PLACED_AGENT_FIELDS(X)
#undef X
        a["stats"]      = fieldsToJson(pa.agent->getStats());
        a["conditions"] = fieldsToJson(pa.agent->getConditions());
        a["movement"]   = pa.agent->rawMovement();
        agents.push_back(std::move(a));
    }
    j["agents"] = std::move(agents);
    return j;
}

bool BattleMap::restore(const nlohmann::json& j)
{
    if (!j.is_object()) return false;
    if (j.value("version", 0) > kBoardSnapshotVersion) return false;   // a newer build wrote it
    if (j.value("cols", -1) != cols_ || j.value("rows", -1) != rows_) return false;

    const auto ait = j.find("agents");
    if (ait == j.end() || !ait->is_array() || ait->size() != placedAgents_.size()) return false;

    // ── Stage: read the whole payload into copies; nothing live changes here ──────────
    std::vector<StagedAgent>         agents;
    std::vector<ActiveTerrainEffect> terrainEffects = activeTerrainEffects_;
    std::vector<ActiveLightEffect>   lightEffects   = activeLightEffects_;
    std::vector<ActiveSpellEffect>   spellEffects   = activeSpellEffects_;
    int nextTerrainId = nextEffectId_, nextLightId = nextLightEffectId_,
        nextSpellId = nextSpellEffectId_;
    std::vector<TerrainType>     terrainType = terrainType_;
    std::vector<double>          terrainMult = terrainMult_;
    std::vector<VisibilityLevel> baseLight   = baseVisibilityLevel_;
    try {
        agents.reserve(placedAgents_.size());
        for (std::size_t i = 0; i < placedAgents_.size(); ++i) {
            const auto& a  = (*ait)[i];
            const auto& pa = placedAgents_[i];
            if (!a.is_object()) return false;
            // The basis: the same creature at the same raw index, or nothing is restored.
            if (a.value("name", std::string{}) != pa.agent->name()) return false;
            if (a.value("size", -1) != pa.agent->getSize()) return false;

            StagedAgent s{pa, pa.agent->getZ(), pa.agent->getStats(),
                          pa.agent->getConditions(), pa.agent->rawMovement()};
#define X(f) readMember(a, #f, s.pa.f);
            RPG_PLACED_AGENT_FIELDS(X)
#undef X
            s.pa.agent = pa.agent;   // never replaced: the overlay writes INTO the built agent
            readMember(a, "z", s.z);
            if (auto it = a.find("stats"); it != a.end() && !fieldsFromJson(*it, s.stats))
                return false;
            if (auto it = a.find("conditions"); it != a.end() && !fieldsFromJson(*it, s.conditions))
                return false;
            readMember(a, "movement", s.movement);
            agents.push_back(std::move(s));
        }

        readMember(j, "terrain_effects", terrainEffects);
        readMember(j, "next_terrain_id", nextTerrainId);
        readMember(j, "light_effects",   lightEffects);
        readMember(j, "next_light_id",   nextLightId);
        readMember(j, "spell_effects",   spellEffects);
        readMember(j, "next_spell_id",   nextSpellId);
        readMember(j, "terrain_type",    terrainType);
        readMember(j, "terrain_mult",    terrainMult);
        readMember(j, "base_light",      baseLight);
    } catch (const nlohmann::json::exception&) {
        return false;   // a field of the wrong shape: nothing has been applied yet
    }
    // The per-cell arrays must match the live ones cell for cell, or every lookup into them
    // is wrong.
    if (terrainType.size() != terrainType_.size() || terrainMult.size() != terrainMult_.size() ||
        baseLight.size() != baseVisibilityLevel_.size())
        return false;

    // ── Commit ────────────────────────────────────────────────────────────────────────
    for (std::size_t i = 0; i < agents.size(); ++i) {
        auto& s = agents[i];
        Agent& ag = *s.pa.agent;
        ag.setStats(s.stats);
        ag.setConditions(s.conditions);
        ag.setPosition(s.pa.origin.col, s.pa.origin.row, s.z);
        ag.initMovement(s.movement[0], s.movement[1], s.movement[2], s.movement[3]);
        placedAgents_[i] = std::move(s.pa);
    }
    activeTerrainEffects_ = std::move(terrainEffects);
    activeLightEffects_   = std::move(lightEffects);
    activeSpellEffects_   = std::move(spellEffects);
    nextEffectId_         = nextTerrainId;
    nextLightEffectId_    = nextLightId;
    nextSpellEffectId_    = nextSpellId;
    terrainType_          = std::move(terrainType);
    terrainMult_          = std::move(terrainMult);
    baseVisibilityLevel_  = std::move(baseLight);

    // The computed overlays are derived, never stored.
    updateTerrain();
    updateLighting();
    return true;
}

std::string BattleMap::snapshotJson() const
{
    return snapshot().dump();
}

bool BattleMap::restoreJson(const std::string& text)
{
    // A save file is untrusted input (hand-edited, truncated by a crash, written by a
    // different build): a parse error comes back as false, never as an exception.
    nlohmann::json j = nlohmann::json::parse(text, nullptr, /*allow_exceptions=*/false);
    if (j.is_discarded()) return false;
    try {
        return restore(j);
    } catch (const nlohmann::json::exception&) {
        return false;
    }
}

} // namespace rpg
