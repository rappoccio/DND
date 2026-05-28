#pragma once

namespace rpg {

    // Damage type enums (duplicated from agent.hpp to avoid circular dependency)
    enum MagicDamage_t{Acid=0,Cold,Fire,Force,Lightning,Necrotic,Poison,Psychic,Radiant,Thunder,NumMagicDamage_t};
    enum PhysicalDamage_t{Bludgeoning=0,Piercing,Slashing,NumPhysicalDamage_t};

    // Damage type with dice information
    struct MagicDamageRoll {
        MagicDamage_t type{};
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed damage bonus (e.g., 1d4+1 has bonus=1)
    };

    struct PhysicalDamageRoll {
        PhysicalDamage_t type{};
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed damage bonus
    };

    // Healing dice (for spells like Healing Word, Cure Wounds, etc.)
    struct HealingRoll {
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed healing bonus
    };

}  // namespace rpg
