#pragma once
#include <cstdint>

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
        // A weapon's extra dice rolled only against these creature types (a CreatureTypeBit
        // mask: the Sunsword's +1d8 Radiant vs Undead). 0 = against everything.
        uint32_t vs_creature_mask{0};
    };

    struct PhysicalDamageRoll {
        PhysicalDamage_t type{};
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed damage bonus
        uint32_t vs_creature_mask{0};  // as MagicDamageRoll::vs_creature_mask
    };

    // Does a damage entry with this mask apply to a target of `target_mask` (creatureTypeMask)?
    [[nodiscard]] inline bool damageAppliesTo(uint32_t vs_creature_mask, uint32_t target_mask) noexcept {
        return vs_creature_mask == 0 || (vs_creature_mask & target_mask) != 0;
    }

    // Healing dice (for spells like Healing Word, Cure Wounds, etc.)
    struct HealingRoll {
        int num_dice{1};
        int die_size{6};
        int bonus{0};  // Fixed healing bonus
    };

}  // namespace rpg
