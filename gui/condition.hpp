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
    OnDamage_t on_damage = OnDamage_t::None;   // behavior when the affected creature takes damage

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
