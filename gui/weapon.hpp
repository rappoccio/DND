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

    std::vector<MagicDamageRoll>    magicDamageRolls;
    std::vector<PhysicalDamageRoll> physicalDamageRolls;

    // ── Bonuses ───────────────────────────────────────────────────────────────
    int          bonus_hit    = 0;       // flat bonus to attack rolls
    int          bonus_damage = 0;       // flat bonus to damage total

};

} // namespace rpg
