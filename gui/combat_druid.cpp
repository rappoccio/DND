// ─────────────────────────────────────────────────────────────────────────────
//  combat_druid.cpp  –  CombatEngine Druid features
// ─────────────────────────────────────────────────────────────────────────────
//
//  Part of the split-out CombatEngine implementation (see combat_internal.hpp).
//  Subclasses: Stars, Sea (and every Druid through Wild Shape).
//  Contents: Wild Shape, Starry Form and its Dragon minimum roll, Wrath of the Sea.
//
//  Split out of combat_riders.cpp and combat_resources.cpp in COMBAT_REFACTOR_PLAN.md R6
//  (plans/COMBAT_CLASS_SPLIT_PLAN.md).
//
#include "combat.hpp"
#include "battle_map.hpp"
#include "combat_internal.hpp"
#include "rules.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <string>
#include <string_view>
#include <unordered_set>
#include <vector>

namespace rpg {

bool CombatEngine::activateWildShape(BattleMap& bm, int idx, const std::string& beast_name, std::vector<Weapon> weapons, const std::string& beast_forms_path) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) return false;

  Agent::Stats stats = bm.getAgentStats(idx);

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) return false;

  // Load beast form from JSON to get stats
  nlohmann::json beasts;
  std::vector<std::string> paths;
  if (!beast_forms_path.empty()) paths.push_back(beast_forms_path);
  paths.insert(paths.end(), {"beast_forms.json", "./beast_forms.json", "../gui/beast_forms.json"});

  bool loaded = false;
  for (const auto& path : paths) {
    try {
      std::ifstream f(path);
      if (f.is_open()) {
        f >> beasts;
        loaded = true;
        break;
      }
    } catch (...) {}
  }
  if (!loaded) return false;

  // Find beast
  nlohmann::json beast_data;
  for (const auto& b : beasts) {
    if (b.value("name", "") == beast_name) {
      beast_data = b;
      break;
    }
  }
  if (beast_data.empty()) return false;

  // Save original weapons, stats, and ability scores
  stats.wild_shape_saved_weapons = getAgentWeapons(bm, idx);
  stats.wild_shape_saved_ac = stats.base_ac;
  stats.wild_shape_saved_str = stats.str;
  stats.wild_shape_saved_dex = stats.dex;
  stats.wild_shape_saved_con = stats.con;

  stats.str = beast_data.value("str", 10);
  stats.dex = beast_data.value("dex", 10);
  stats.con = beast_data.value("con", 10);
  stats.base_ac = beast_data.value("ac", 10);
  if (stats.druid_circle == CircleOfMoon) {
    stats.base_ac = std::max(stats.base_ac, 13 + (stats.wis - 10) / 2);
  }
  // The beast/Moon AC above is a FINAL value (its DEX is already folded in). The druid stays a PC
  // (is_npc == false), so calculateAC would otherwise layer the beast's DEX on top again — the
  // base_ac is corrected after the beast stats + weapons are committed below (see wild_shape_desired_ac).
  const int wild_shape_desired_ac = stats.base_ac;

  int temp_hp = stats.classLevel(CharacterClass::Druid) * (stats.druid_circle == CircleOfMoon ? 3 : 1);
  stats.temp_hp += temp_hp;
  stats.rage_thp_source_idx = -1;  // Wild Shape THP is not rage-sourced (don't let endRage wipe it)

  stats.wild_shape_active = true;
  stats.wild_shape_form_name = beast_name;
  stats.num_attacks = 2;

  bm.setAgentStats(idx, stats);

  // Set the beast form weapons on the agent
  bm.setAgentWeapons(idx, weapons);

  // Correct base_ac so the effective AC (calculateAC, which for a PC druid layers in the beast's DEX
  // and any equipped armor/shield) equals the intended final beast/Moon AC. Done after stats AND
  // weapons are committed so the shield scan sees the beast's (shieldless) loadout.
  {
    Agent::Stats st2 = bm.getAgentStats(idx);
    int effective = calculateAC(bm, idx);
    if (effective != wild_shape_desired_ac) {
      st2.base_ac -= (effective - wild_shape_desired_ac);
      bm.setAgentStats(idx, st2);
    }
  }

  return true;
}

bool CombatEngine::deactivateWildShape(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WILD_SHAPE] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Restore saved AC and ability scores
  if (stats.base_ac > 0 && stats.wild_shape_saved_ac > 0) {
    stats.base_ac = stats.wild_shape_saved_ac;
  }
  if (stats.wild_shape_saved_str > 0) stats.str = stats.wild_shape_saved_str;
  if (stats.wild_shape_saved_dex > 0) stats.dex = stats.wild_shape_saved_dex;
  if (stats.wild_shape_saved_con > 0) stats.con = stats.wild_shape_saved_con;

  log_("[WILD_SHAPE] Restored stats: AC={}, STR={}, DEX={}, CON={}", stats.base_ac, stats.str, stats.dex, stats.con);

  // Restore original weapons
  bm.setAgentWeapons(idx, stats.wild_shape_saved_weapons);

  stats.wild_shape_active = false;
  stats.wild_shape_form_name = "";
  stats.lunar_radiance_available = false;

  bm.setAgentStats(idx, stats);
  log_("[WILD_SHAPE] Deactivated Wild Shape");
  return true;
}

bool CombatEngine::activateStarryForm(BattleMap& bm, int idx, int constellation) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[STARRY_FORM] ERROR: Invalid agent index {}", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);
  log_("[STARRY_FORM] Activating constellation {}", constellation);

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) {
    log_("[STARRY_FORM] ERROR: Could not spend Wild Shape resource");
    return false;
  }

  stats.starry_form_active = true;
  stats.starry_constellation = constellation;

  // Dragon constellation: add fly speed at L10+
  if (constellation == 3 && stats.classLevel(CharacterClass::Druid) >= 10) {  // 3 = Dragon
    stats.speed_fly = stats.speed_walk;
    log_("[STARRY_FORM] Added fly speed for Dragon constellation");
  }

  // Full of Stars (L14): add resistances to B/P/S
  if (stats.classLevel(CharacterClass::Druid) >= 14) {
    stats.set_physical_damage_multiplier(0, 0.5f);  // Bludgeoning
    stats.set_physical_damage_multiplier(1, 0.5f);  // Piercing
    stats.set_physical_damage_multiplier(2, 0.5f);  // Slashing
    log_("[STARRY_FORM] Added B/P/S resistances at level 14+");
  }

  bm.setAgentStats(idx, stats);
  log_("[STARRY_FORM] SUCCESS: Activated constellation {}", constellation);
  return true;
}

bool CombatEngine::deactivateStarryForm(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[STARRY_FORM] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Restore fly speed
  stats.speed_fly = 0;

  // Clear resistances
  stats.set_physical_damage_multiplier(0, 1.0f);  // Bludgeoning
  stats.set_physical_damage_multiplier(1, 1.0f);  // Piercing
  stats.set_physical_damage_multiplier(2, 1.0f);  // Slashing

  stats.starry_form_active = false;
  stats.starry_constellation = 0;

  bm.setAgentStats(idx, stats);
  log_("[STARRY_FORM] Deactivated Starry Form");
  return true;
}

bool CombatEngine::activateWrathOfSea(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WRATH_OF_SEA] ERROR: Invalid agent index {}", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);
  log_("[WRATH_OF_SEA] Activating Wrath of the Sea");

  // Check and spend Wild Shape resource
  Resource* ws = stats.getResource("Wild Shape");
  if (!ws || !ws->spend(1)) {
    log_("[WRATH_OF_SEA] ERROR: Could not spend Wild Shape resource");
    return false;
  }

  stats.wrath_of_sea_active = true;

  // Stormborn (L10): add fly speed and resistances
  if (stats.classLevel(CharacterClass::Druid) >= 10) {
    stats.speed_fly = stats.speed_walk;
    // Cold, Lightning, Thunder
    stats.set_magic_damage_multiplier(1, 0.5f);   // Cold
    stats.set_magic_damage_multiplier(4, 0.5f);   // Lightning
    stats.set_magic_damage_multiplier(9, 0.5f);   // Thunder
    log_("[WRATH_OF_SEA] Added fly speed and resistances at level 10+");
  }

  bm.setAgentStats(idx, stats);
  log_("[WRATH_OF_SEA] SUCCESS: Activated Wrath of the Sea");
  return true;
}

bool CombatEngine::deactivateWrathOfSea(BattleMap& bm, int idx) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    log_("[WRATH_OF_SEA] ERROR: Invalid agent index {} in deactivate", idx);
    return false;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  stats.speed_fly = 0;
  stats.set_magic_damage_multiplier(1, 1.0f);   // Cold
  stats.set_magic_damage_multiplier(4, 1.0f);   // Lightning
  stats.set_magic_damage_multiplier(9, 1.0f);   // Thunder

  stats.wrath_of_sea_active = false;

  bm.setAgentStats(idx, stats);
  log_("[WRATH_OF_SEA] Deactivated Wrath of the Sea");
  return true;
}

int CombatEngine::applyDragonMinRoll(BattleMap& bm, int idx, int d20_roll) noexcept {
  auto agents = bm.placedAgents();
  if (idx < 0 || idx >= static_cast<int>(agents.size())) {
    return d20_roll;
  }

  Agent::Stats stats = bm.getAgentStats(idx);

  // Dragon constellation (value 3) with level 10+ gets min-roll-10
  if (stats.starry_form_active && stats.starry_constellation == 3 && stats.classLevel(CharacterClass::Druid) >= 10) {
    int result = std::max(d20_roll, 10);
    if (result > d20_roll) {
      log_("[DRAGON_MIN_ROLL] Applied min-10: rolled {} -> {}", d20_roll, result);
    }
    return result;
  }

  return d20_roll;
}

} // namespace rpg
