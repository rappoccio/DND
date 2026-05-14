#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  weapon.hpp  –  Weapon data model
//
//  Kept separate so CombatEngine can include it without pulling in the rest
//  of the battle-map machinery.
// ─────────────────────────────────────────────────────────────────────────────

#include <string>
#include <vector>
#include "agent.hpp"
#include "spell.hpp"

namespace rpg {

enum class WeaponType { Melee, Ranged };

// ─────────────────────────────────────────────────────────────────────────────
//  AttackCondition – Conditions applied by weapon attacks or class features
// ─────────────────────────────────────────────────────────────────────────────

struct AttackCondition {
    std::string condition_name;           // "Stunned", "Paralyzed", etc.
    int condition_duration = 0;           // duration in turns (0 = use spell duration placeholder)
    int save_repeat_turns = 1;            // repeat save check every N turns
    Spell::SaveAbility_t save_ability = Spell::SaveDex;      // target's save type
    Spell::SaveAbility_t save_dc_ability = Spell::SaveWis;   // attacker's ability for DC
};

struct Weapon {
    std::string  name            = "Unnamed";

    WeaponType   type            = WeaponType::Melee;

    // ── Melee ─────────────────────────────────────────────────────────────
    int          reach_ft        = 5;           // 5, 10, or 15 ft

    // ── Ranged ────────────────────────────────────────────────────────────
    int          normal_range_ft = 80;          // full-attack bonus up to this
    int          long_range_ft   = 320;         // disadvantage beyond normal

    // ── Attack-roll modifier rules ─────────────────────────────────────────
    bool         finesse         = false;       // use STR or DEX (whichever is higher)
    bool         thrown          = false;       // ranged but uses STR

    // ── General ───────────────────────────────────────────────────────────
    bool         proficient      = false;       // add proficiency bonus to hit
    bool         off_hand        = false;       // designated off-hand weapon (TWF)
    bool         two_handed      = false;       // requires both hands (main hand only, no off-hand)

    std::vector<MagicDamageRoll>    magicDamageRolls;
    std::vector<PhysicalDamageRoll> physicalDamageRolls;

    // ── Bonuses ───────────────────────────────────────────────────────────────
    int          bonus_hit    = 0;       // flat bonus to attack rolls
    int          bonus_damage = 0;       // flat bonus to damage total
    int          ac_bonus     = 0;       // for shields: +2 to AC (or other bonuses)

    // ── Conditions applied on hit ─────────────────────────────────────────────
    std::vector<AttackCondition> conditions;  // conditions applied when attack hits

};

} // namespace rpg
