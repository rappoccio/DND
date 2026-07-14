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
    bool         thrown          = false;       // Thrown property: this weapon may be hurled to make a
                                                // ranged attack (out to long_range_ft) using the same
                                                // ability modifier as a melee attack with it (so STR,
                                                // or DEX when finesse). See Attack::thrown.

    // ── Thrown-weapon bundle ──────────────────────────────────────────────
    // How many copies of this weapon the wielder is carrying — javelins, daggers, darts are
    // carried in bundles. A THROW spends one copy and lays it on the ground as a MapItem (a
    // thrown WEAPON is not destroyed, unlike a thrown Item — a flask — which is consumed); the
    // slot is emptied when the last copy is thrown. A melee swing never spends a copy.
    // Always >= 1 for a weapon actually in hand; 0 means every copy has been thrown away.
    int          quantity        = 1;

    // This weapon comes straight back after it is thrown: it is never spent and never lands on
    // the ground. A Soulknife's Psychic Blade ("the blade vanishes after it hits or misses" — and
    // is re-manifested for free), a conjured/pact weapon, a returning magic weapon.
    bool         returns_after_throw = false;
    bool         pact_weapon     = false;       // Warlock Pact of the Blade: may use CHA for attack/damage
    bool         psychic_blade   = false;       // Soulknife Rogue: identifies the Psychic Blade for Homing Strikes / Rend Mind
                                                // (and identifies the pact weapon for Thirsting Blade /
                                                //  Eldritch Smite / Lifedrinker)

    // ── General ───────────────────────────────────────────────────────────
    bool         proficient      = false;       // add proficiency bonus to hit
    bool         off_hand        = false;       // designated off-hand weapon (TWF)
    bool         two_handed      = false;       // requires both hands (main hand only, no off-hand)
    bool         heavy           = false;       // Heavy property (Great Weapon Master, Polearm Master)
    bool         light           = false;       // Light property (Dual Wielder, off-hand / TWF, Crossbow Expert)
    bool         is_shield       = false;       // this "weapon" is a Shield held in the off-hand: grants ac_bonus,
                                                // makes no attack, and counts as "holding a Shield" (Shield Master,
                                                // Interception, Protection, Unarmed Fighting)
    WeaponMastery mastery        = WeaponMastery::None;  // 2024 Weapon Mastery property
    bool         auto_hit_if_grappled = false;  // the attack automatically hits a creature this attacker
                                                // has Grappled (e.g. a vampire's Bite) — skips the roll
                                                // (a natural 20 still crits)
    // Save-delivered damage (e.g. a Vampire's Bite is a CON save, not an attack roll). When true AND the
    // attack qualifies as an auto-hit (auto_hit_if_grappled vs a creature this attacker has Grappled), the
    // target instead makes a `save_for_damage_ability` saving throw vs DC = 8 + attacker PB + attacker
    // ability mod: on a FAILURE the bite lands (full damage + on-hit riders); on a SUCCESS it deals nothing.
    bool         save_for_damage         = false;
    SaveAbility_t save_for_damage_ability = SaveCon;
    // Initiation/prompting flag (distinct from auto_hit_if_grappled, which governs RESOLUTION):
    // when true, this weapon should be auto-offered (manual play) or auto-attempted (NPC automation)
    // against a creature the wielder is currently Grappling, without the DM selecting weapon+target.
    // A vampire's Bite sets BOTH this and auto_hit_if_grappled. See MONSTER_AUTO_EFFECTS_PLAN.md.
    bool         auto_use_when_grappling = false;
    bool         permanently_armed    = false;  // this weapon cannot be disarmed (e.g., unarmed attacks,
                                                // which are part of a creature's natural abilities)

    // ── Limited-use / Recharge (NPC monster actions) ───────────────────────────
    // uses_max == 0  ⇒ unlimited (a normal weapon). uses_max > 0 ⇒ N/day, refilled on
    // a long rest. recharge_min == 0 ⇒ no recharge; recharge_min > 0 ⇒ once spent the
    // weapon is `expended` until, at the owner's turn start, a d6 ≥ recharge_min restores
    // it. A pure-recharge breath weapon uses uses_max = 1 + recharge_min = 5 (or 6).
    int          uses_max        = 0;   // 0 = unlimited
    int          uses_remaining  = 0;   // current remaining uses (for N/day weapons)
    int          recharge_min    = 0;   // 0 = no recharge; 5 ⇒ (Recharge 5–6); 6 ⇒ (Recharge 6)
    bool         expended        = false;  // spent and waiting on a recharge roll

    std::vector<MagicDamageRoll>    magicDamageRolls;
    std::vector<PhysicalDamageRoll> physicalDamageRolls;

    // ── Convenience attributes (for simpler API) ───────────────────────────────
    int          damage_dice       = 6;           // primary damage die size (for tests)
    int          damage_dice_count = 1;           // primary damage die count (for tests)
    int          damage_modifier   = 0;           // primary damage modifier (for tests)
    int          range_short_feet  = 80;          // primary short range (for tests)
    int          range_long_feet   = 320;         // primary long range (for tests)

    // ── Bonuses ───────────────────────────────────────────────────────────────
    int          bonus_hit    = 0;       // flat bonus to attack rolls
    int          bonus_damage = 0;       // flat bonus to damage total
    int          ac_bonus     = 0;       // for shields: +2 to AC (or other bonuses)

    // ── Conditions applied on hit ─────────────────────────────────────────────
    std::vector<AttackCondition> conditions;  // conditions applied when attack hits
    std::string condition_rider = "";         // simple condition name from beast form (e.g., "Poisoned")

    // Icon used when this weapon is lying on the map as a MapItem (authored in weapons.json).
    // Carried on the Weapon so any code path that drops one — a THROW, the GUI's manual drop —
    // lands it with the right sprite. Empty ⇒ the GUI draws its amber fallback box.
    std::string sprite_path = "";

};

} // namespace rpg
