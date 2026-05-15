#pragma once

#include <string>

namespace rpg {

// Save ability types (used by spells, weapons, and conditions)
enum SaveAbility_t { SaveStr=0, SaveDex, SaveCon, SaveInt, SaveWis, SaveCha, SaveSpellcasterMod, NumSaveAbility_t };

// Conditions applied by weapon attacks or class features
struct AttackCondition {
    std::string condition_name;           // "Stunned", "Paralyzed", "Push", etc.
    int condition_duration = 0;           // duration in turns (0 = use spell duration placeholder)
    int push_ft = 0;                      // feet to push (for "Push" condition and future mechanics like telekinesis)
    int save_repeat_turns = 1;            // repeat save check every N turns
    SaveAbility_t save_ability = SaveDex;      // target's save type
    SaveAbility_t save_dc_ability = SaveWis;   // attacker's ability for DC
};

} // namespace rpg
