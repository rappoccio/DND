#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  weapon.hpp  –  Weapon data model
//
//  Kept separate so CombatEngine can include it without pulling in the rest
//  of the battle-map machinery.
// ─────────────────────────────────────────────────────────────────────────────

#include <string>
#include <vector>
#include "condition.hpp"
#include "damage.hpp"  // For MagicDamageRoll and PhysicalDamageRoll

namespace rpg {

enum class WeaponType { Melee, Ranged };

// 2024 Weapon Mastery properties. A creature with the Weapon Mastery feature
// applies its weapon's mastery property when attacking with that weapon.
enum class WeaponMastery {
    None = 0,
    Cleave,   // hit → one extra attack vs a 2nd creature within 5 ft (no ability mod), 1/turn
    Graze,    // miss → deal damage equal to the attack ability modifier
    Nick,     // the light-weapon extra attack is part of the Attack action (frees the bonus action)
    Poison,   // hit → target is Poisoned (disadvantage on attacks/checks), 1/turn
    Push,     // hit → push a Large-or-smaller target 10 ft straight away
    Sap,       // hit → target has disadvantage on its next attack roll
    Slow,     // hit + damage → target's Speed -10 ft until the start of your next turn
    Topple,   // hit → force a CON save or the target is knocked Prone
    Vex       // hit + damage → you have advantage on your next attack vs that target
};

struct Weapon {
    std::string  name            = "Unarmed";

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
    WeaponMastery mastery        = WeaponMastery::None;  // 2024 Weapon Mastery property

    std::vector<MagicDamageRoll>    magicDamageRolls;
    std::vector<PhysicalDamageRoll> physicalDamageRolls;

    // ── Convenience attributes (for simpler API) ───────────────────────────────
    int          damage_dice       = 6;           // primary damage die size (for tests)
    int          damage_dice_count = 1;           // primary damage die count (for tests)
    int          damage_modifier   = 0;           // primary damage modifier (for tests)
    int          attack_bonus      = 0;           // primary attack bonus (for tests)
    int          range_short_feet  = 80;          // primary short range (for tests)
    int          range_long_feet   = 320;         // primary long range (for tests)

    // ── Bonuses ───────────────────────────────────────────────────────────────
    int          bonus_hit    = 0;       // flat bonus to attack rolls
    int          bonus_damage = 0;       // flat bonus to damage total
    int          ac_bonus     = 0;       // for shields: +2 to AC (or other bonuses)

    // ── Conditions applied on hit ─────────────────────────────────────────────
    std::vector<AttackCondition> conditions;  // conditions applied when attack hits

};

} // namespace rpg
