// ─────────────────────────────────────────────────────────────────────────────
//  species.hpp  –  the species table (SPECIES_PLAN.md D1)
// ─────────────────────────────────────────────────────────────────────────────
//
//  One SpeciesDef per species gives the one-time traits Agent::Stats::setSpecies()
//  folds into the stat block: base walk Speed, Darkvision, damage resistances and
//  save-advantage bits. setSpecies() records exactly what it changed in a
//  SpeciesApplied, which is saved with the agent, and a later swap undoes that record
//  instead of guessing from the values (the old Dhampir code stripped Speed 35 back to
//  30 whatever had set it).
//
//  Sub-choices (D2): `options` lists a species' one pick (dragon colour, lineage, Giant
//  ancestry, Fiendish legacy) under `option_label`; `size_options` the sizes it may be;
//  kSpeciesSpellAbility marks a species whose granted spells use a chosen INT/WIS/CHA.
//  The nine SRD species' traits (Speed, Darkvision, resistances, …) are filled in by
//  SP2; SP1 gives them names, options and sizes only.
//
#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <string_view>

#include "damage.hpp"

namespace rpg {

// Size options a species allows (D6 reads these once a PC size exists).
inline constexpr std::uint8_t kSpeciesSizeSmall  = 1u << 0;
inline constexpr std::uint8_t kSpeciesSizeMedium = 1u << 1;

// Per-species features the engine checks by flag rather than by name.
inline constexpr std::uint32_t kSpeciesVampiricBite = 1u << 0;   // Dhampir
inline constexpr std::uint32_t kSpeciesSpellAbility = 1u << 1;   // picks INT/WIS/CHA for its spells

// SaveAbility_t ordinals a species spell ability may take (agent.hpp can't see condition.hpp).
inline constexpr int kSpeciesAbilityInt = 3;
inline constexpr int kSpeciesAbilityWis = 4;
inline constexpr int kSpeciesAbilityCha = 5;

inline constexpr std::array<std::string_view, 10> kDraconicAncestries{
    "Black", "Blue", "Brass", "Bronze", "Copper", "Gold", "Green", "Red", "Silver", "White"};
inline constexpr std::array<std::string_view, 3> kElvenLineages{"Drow", "High Elf", "Wood Elf"};
inline constexpr std::array<std::string_view, 2> kGnomishLineages{"Forest Gnome", "Rock Gnome"};
inline constexpr std::array<std::string_view, 6> kGiantAncestries{
    "Cloud", "Fire", "Frost", "Hill", "Stone", "Storm"};
inline constexpr std::array<std::string_view, 3> kFiendishLegacies{"Abyssal", "Chthonic", "Infernal"};

struct SpeciesDef {
    std::string_view name;
    int speed_walk{0};                  // base walk Speed (0 = leave it alone)
    int darkvision{0};                  // Darkvision range in feet (0 = none)
    std::uint8_t size_options{kSpeciesSizeMedium};
    std::uint32_t magic_resist_mask{0}; // bit (1 << MagicDamage_t): Resistance to that type
    int save_advantage_bits{0};         // OR'd into Stats::save_advantage_mask
    std::uint32_t flags{0};
    std::string_view option_label{};              // "Lineage", "Legacy", … ("" = no option)
    std::span<const std::string_view> options{};  // the picks; the first is the default

    [[nodiscard]] constexpr bool hasOption(std::string_view o) const noexcept {
        for (const auto& x : options)
            if (x == o) return true;
        return false;
    }
    [[nodiscard]] constexpr bool allowsSize(std::uint8_t size_bit) const noexcept {
        return (size_options & size_bit) != 0;
    }
    // Medium when the species allows it, else its one size.
    [[nodiscard]] constexpr std::uint8_t defaultSize() const noexcept {
        return allowsSize(kSpeciesSizeMedium) ? kSpeciesSizeMedium : kSpeciesSizeSmall;
    }

    [[nodiscard]] constexpr bool resists(MagicDamage_t t) const noexcept {
        return (magic_resist_mask >> static_cast<unsigned>(t)) & 1u;
    }
};

inline constexpr std::array kSpeciesTable{
    // Dhampir (Ravenloft): Speed 35, Darkvision 60, Trace of Undeath (Necrotic
    // Resistance), Vampiric Bite. Spider Climb is not modeled.
    SpeciesDef{"Dhampir", 35, 60, kSpeciesSizeSmall | kSpeciesSizeMedium,
               1u << Necrotic, 0, kSpeciesVampiricBite},
    // The nine SRD 5.2 species (SPECIES_PLAN.md). Traits: SP2.
    SpeciesDef{.name = "Dragonborn", .option_label = "Ancestry", .options = kDraconicAncestries},
    SpeciesDef{.name = "Dwarf"},
    SpeciesDef{.name = "Elf", .flags = kSpeciesSpellAbility, .option_label = "Lineage",
               .options = kElvenLineages},
    SpeciesDef{.name = "Gnome", .size_options = kSpeciesSizeSmall, .flags = kSpeciesSpellAbility,
               .option_label = "Lineage", .options = kGnomishLineages},
    SpeciesDef{.name = "Goliath", .option_label = "Ancestry", .options = kGiantAncestries},
    SpeciesDef{.name = "Halfling", .size_options = kSpeciesSizeSmall},
    SpeciesDef{.name = "Human", .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium},
    SpeciesDef{.name = "Orc"},
    SpeciesDef{.name = "Tiefling", .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesSpellAbility, .option_label = "Legacy", .options = kFiendishLegacies},
};

// Size bit <-> the name saved and shown ("Small", "Medium"; "" for an unknown bit).
[[nodiscard]] constexpr std::string_view speciesSizeName(std::uint8_t bit) noexcept {
    return bit == kSpeciesSizeSmall ? "Small" : bit == kSpeciesSizeMedium ? "Medium" : "";
}
[[nodiscard]] constexpr std::uint8_t speciesSizeBit(std::string_view name) noexcept {
    return name == "Small" ? kSpeciesSizeSmall : name == "Medium" ? kSpeciesSizeMedium : 0;
}

// The table entry for `name`, or nullptr ("" and unknown names carry no traits).
[[nodiscard]] constexpr const SpeciesDef* findSpecies(std::string_view name) noexcept {
    for (const auto& d : kSpeciesTable)
        if (d.name == name) return &d;
    return nullptr;
}

// What setSpecies() changed, so the swap away undoes exactly that. A field is put back
// only while it still holds the value the species set: a hand edit since then wins.
struct SpeciesApplied {
    int speed_from{0};                  // walk Speed before / after (equal = untouched)
    int speed_to{0};
    int darkvision_from{0};             // Darkvision before / after (equal = untouched)
    int darkvision_to{0};
    std::uint32_t magic_resist_mask{0}; // types this species lowered to 0.5 (from 1.0 or more)
    int save_advantage_bits{0};         // bits this species added (not already set)
};

// Out of the struct so tests/test_board_snapshot.py's member parser sees only fields.
[[nodiscard]] constexpr bool operator==(const SpeciesApplied& a, const SpeciesApplied& b) noexcept {
    return a.speed_from == b.speed_from && a.speed_to == b.speed_to
        && a.darkvision_from == b.darkvision_from && a.darkvision_to == b.darkvision_to
        && a.magic_resist_mask == b.magic_resist_mask
        && a.save_advantage_bits == b.save_advantage_bits;
}

} // namespace rpg
