#pragma once

#include <array>
#include <string>
#include "agent.hpp"

namespace rpg {

struct Armor {
    std::string name;
    std::string description;

    // AC contribution
    int ac_bonus{0};  // +2 for Shield, +1 for magical armor, +0 for decorative pieces

    int dex_mod_cap{30}; // DEX modifier cap: 0=no DEX, 2=medium armor cap, 30=no cap (light/unarmored) 
    // Damage properties (like Agent::Stats)
    // 0.0 = immune, 0.5 = resist, 1.0 = normal, 2.0 = vulnerable
    std::array<float, NumMagicDamage_t> magic_damage_multipliers{};
    std::array<float, NumPhysicalDamage_t> physical_damage_multipliers{};

    // Flat damage reduction: reduces all incoming damage by this amount (e.g., magical protection)
    int damage_reduction{0};  // 0 = no reduction, 2 = reduces all damage by 2

    // Properties (STR requirements for later)
    bool requires_strength{false};
    int str_requirement{0};
};

}  // namespace rpg
