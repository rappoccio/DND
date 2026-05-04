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
    int          num_dice        = 1;           // e.g. 2d6 → num_dice = 2
    int          die_size        = 6;           //              die_size = 6

    std::vector<MagicDamage_t>    magicDamages;
    std::vector<PhysicalDamage_t> physicalDamages;
    
};

} // namespace rpg
