#pragma once

#include <string>

#include "damage.hpp"

namespace rpg {

// Save ability types (used by spells, weapons, and conditions)
enum SaveAbility_t { SaveStr=0, SaveDex, SaveCon, SaveInt, SaveWis, SaveCha, SaveSpellcasterMod, NumSaveAbility_t };

// How a condition reacts when the affected creature takes damage.
//   None       — damage has no effect on the condition.
//   End        — the condition ends immediately (Sleep, Hypnotic Pattern, Color Spray).
//   RepeatSave — the creature repeats its save at Advantage; success ends it (Tasha's Hideous Laughter).
enum class OnDamage_t { None=0, End, RepeatSave };

// Conditions applied by weapon attacks or class features
struct AttackCondition {
    std::string condition_name;           // "Stunned", "Paralyzed", "Push", etc.
    int condition_duration = 0;           // duration in turns (0 = use spell duration placeholder)
    int push_ft = 0;                      // feet to push (for "Push" condition and future mechanics like telekinesis)
    int save_repeat_turns = 1;            // repeat save check every N turns
    SaveAbility_t save_ability = SaveDex;      // target's save type
    SaveAbility_t save_dc_ability = SaveWis;   // attacker's ability for DC
    bool requires_save = false;           // if false, condition applies automatically; if true, target gets a save
    // When true, the periodic "shrug it off" save is rolled at the END of each of the
    // affected creature's turns (CombatEngine::endTurn) instead of the start — RAW for
    // Hold Person / Hold Monster ("At the end of each of its turns, the target repeats
    // the save"). The creature is still barred from acting on the intervening turn; a
    // success only frees it starting on its NEXT turn. Copied onto the tracked condition.
    bool save_at_end_of_turn = false;
    OnDamage_t on_damage = OnDamage_t::None;   // behavior when the affected creature takes damage

    // ── Damage-over-time rider (Pit Fiend poison, and any future recurring DoT) ──
    // A generic "takes N dice of <type> at the start of each of its turns" effect,
    // carried on the applied condition. When dot_dice > 0 the affected creature
    // takes dot_dice × d(dot_die_size) + dot_flat_bonus of dot_damage_type at the
    // start of each of its turns (CombatEngine::beginTurn), resistances applying.
    // prevents_healing blocks all HP gain (healAgent + Regeneration) while the
    // condition persists — the Pit Fiend's poison "can't regain hit points" clause.
    // These are copied verbatim onto the tracked ActiveAgentCondition.
    int           dot_dice           = 0;         // number of DoT dice (0 = no DoT)
    int           dot_die_size       = 0;         // die size, e.g. 6 → d6
    int           dot_flat_bonus     = 0;         // flat damage added after the dice
    MagicDamage_t dot_damage_type    = Poison;    // damage type dealt each turn
    bool          prevents_healing   = false;     // while active, the creature can't regain HP

    // ── Grappled rider (condition_name == "Grappled") ──────────────────────────
    // The on-hit grapple reuses the standalone Grapple Weapon Action core
    // (CombatEngine::resolveGrapple → applyGrappled), shared with the Grappler feat.
    bool contested = false;   // true  → contested Athletics vs max(Athletics,Acrobatics)
                              // false → grapple lands automatically on the qualifying hit
    int  escape_dc = 0;       // fixed escape DC override; 0 → compute 10 + STR mod + prof

    // ── Vistani Curse authoring ────────────────────────────────────────────────
    // curse_kind selects which curse effect this condition installs when applied
    // (see ActiveAgentCondition). The kickback fields are copied verbatim onto the
    // tracked ActiveAgentCondition so the caster takes damage when the curse ends.
    //   0 = none (ordinary condition), 1 = vulnerability, 2 = weakness (save disadv),
    //   3 = affliction (Blinded/Deafened/Both — chosen at cast time).
    int           curse_kind          = 0;
    int           kickback_dice       = 0;         // e.g. 3 or 5
    int           kickback_die_size    = 0;         // e.g. 6 → d6
    MagicDamage_t kickback_damage_type = Psychic;
};

} // namespace rpg
