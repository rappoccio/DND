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
//  SP2 fills in the nine SRD species' passive traits. Traits that depend on the option
//  (Drow Darkvision 120, Wood Elf Speed 35, Draconic and Fiendish resistances) come from
//  kSpeciesOptionTable; speciesTraits() merges the two. Condition-save Advantage (D5),
//  Powerful Build and Keen Senses are flags the engine reads live, not folded-in values.
//
#pragma once

#include <array>
#include <cstdint>
#include <span>
#include <string>
#include <string_view>

#include "damage.hpp"

namespace rpg {

// Size options a species allows (D6 reads these once a PC size exists).
inline constexpr std::uint8_t kSpeciesSizeSmall  = 1u << 0;
inline constexpr std::uint8_t kSpeciesSizeMedium = 1u << 1;

// Per-species features the engine checks by flag rather than by name.
inline constexpr std::uint32_t kSpeciesVampiricBite = 1u << 0;   // Dhampir
inline constexpr std::uint32_t kSpeciesSpellAbility = 1u << 1;   // picks INT/WIS/CHA for its spells
inline constexpr std::uint32_t kSpeciesBrave         = 1u << 2;   // Halfling: Adv. vs Frightened
inline constexpr std::uint32_t kSpeciesFeyAncestry   = 1u << 3;   // Elf: Adv. vs Charmed
inline constexpr std::uint32_t kSpeciesResilience    = 1u << 4;   // Dwarf: Adv. vs Poisoned
inline constexpr std::uint32_t kSpeciesToughness     = 1u << 5;   // Dwarf: +1 HP per level
inline constexpr std::uint32_t kSpeciesKeenSenses    = 1u << 6;   // Elf: Perception proficiency
inline constexpr std::uint32_t kSpeciesPowerfulBuild = 1u << 7;   // Goliath: Adv. to escape a grapple
// SP4 (read live by the engine):
inline constexpr std::uint32_t kSpeciesLuck          = 1u << 8;   // Halfling: reroll a natural 1 (D10)
inline constexpr std::uint32_t kSpeciesAdrenaline    = 1u << 9;   // Orc: Adrenaline Rush
inline constexpr std::uint32_t kSpeciesRelentless    = 1u << 10;  // Orc: Relentless Endurance
inline constexpr std::uint32_t kSpeciesHeroic        = 1u << 11;  // Human: Heroic Inspiration on a Long Rest (D11)
inline constexpr std::uint32_t kSpeciesSkillful      = 1u << 12;  // Human: one skill proficiency (D12)
inline constexpr std::uint32_t kSpeciesVersatile     = 1u << 13;  // Human: a second origin feat (D13)

// Condition-save Advantage (D5): the condition a flag covers, "" for a flag that covers none.
[[nodiscard]] constexpr bool speciesFlagCoversCondition(std::uint32_t flags,
                                                        std::string_view cond) noexcept {
    return ((flags & kSpeciesBrave) && cond == "Frightened")
        || ((flags & kSpeciesFeyAncestry) && cond == "Charmed")
        || ((flags & kSpeciesResilience) && cond == "Poisoned");
}

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
// Skillful (D12): the four skills the engine models.
inline constexpr std::array<std::string_view, 4> kSpeciesSkills{
    "Athletics", "Perception", "Sleight of Hand", "Stealth"};

// Gnomish Cunning: INT, WIS and CHA save bits (SaveAbility_t ordinals 3, 4, 5).
inline constexpr int kGnomishCunningBits = (1 << 3) | (1 << 4) | (1 << 5);

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
    // The nine SRD 5.2 species (SPECIES_PLAN.md). SP2: passive traits. Option-driven
    // traits are in kSpeciesOptionTable below.
    SpeciesDef{.name = "Dragonborn", .darkvision = 60, .option_label = "Ancestry",
               .options = kDraconicAncestries},
    SpeciesDef{.name = "Dwarf", .darkvision = 120, .magic_resist_mask = 1u << Poison,
               .flags = kSpeciesResilience | kSpeciesToughness},
    SpeciesDef{.name = "Elf", .darkvision = 60,
               .flags = kSpeciesSpellAbility | kSpeciesFeyAncestry | kSpeciesKeenSenses,
               .option_label = "Lineage", .options = kElvenLineages},
    SpeciesDef{.name = "Gnome", .darkvision = 60, .size_options = kSpeciesSizeSmall,
               .save_advantage_bits = kGnomishCunningBits, .flags = kSpeciesSpellAbility,
               .option_label = "Lineage", .options = kGnomishLineages},
    SpeciesDef{.name = "Goliath", .speed_walk = 35, .flags = kSpeciesPowerfulBuild,
               .option_label = "Ancestry", .options = kGiantAncestries},
    SpeciesDef{.name = "Halfling", .size_options = kSpeciesSizeSmall,
               .flags = kSpeciesBrave | kSpeciesLuck},
    SpeciesDef{.name = "Human", .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesHeroic | kSpeciesSkillful | kSpeciesVersatile},
    SpeciesDef{.name = "Orc", .darkvision = 120, .flags = kSpeciesAdrenaline | kSpeciesRelentless},
    SpeciesDef{.name = "Tiefling", .darkvision = 60,
               .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesSpellAbility, .option_label = "Legacy", .options = kFiendishLegacies},
};

// Traits one option adds on top of its species' entry. Each field replaces the species'
// value when it is larger (Speed, Darkvision) or ORs into it (resistances).
struct SpeciesOptionDef {
    std::string_view species;
    std::string_view option;
    int speed_walk{0};
    int darkvision{0};
    std::uint32_t magic_resist_mask{0};
};

inline constexpr std::array kSpeciesOptionTable{
    // Draconic Ancestry → Damage Resistance.
    SpeciesOptionDef{"Dragonborn", "Black",  0, 0, 1u << Acid},
    SpeciesOptionDef{"Dragonborn", "Blue",   0, 0, 1u << Lightning},
    SpeciesOptionDef{"Dragonborn", "Brass",  0, 0, 1u << Fire},
    SpeciesOptionDef{"Dragonborn", "Bronze", 0, 0, 1u << Lightning},
    SpeciesOptionDef{"Dragonborn", "Copper", 0, 0, 1u << Acid},
    SpeciesOptionDef{"Dragonborn", "Gold",   0, 0, 1u << Fire},
    SpeciesOptionDef{"Dragonborn", "Green",  0, 0, 1u << Poison},
    SpeciesOptionDef{"Dragonborn", "Red",    0, 0, 1u << Fire},
    SpeciesOptionDef{"Dragonborn", "Silver", 0, 0, 1u << Cold},
    SpeciesOptionDef{"Dragonborn", "White",  0, 0, 1u << Cold},
    // Elven Lineage: Drow Darkvision 120, Wood Elf Speed 35.
    SpeciesOptionDef{"Elf", "Drow",     0, 120, 0},
    SpeciesOptionDef{"Elf", "Wood Elf", 35, 0, 0},
    // Fiendish Legacy → Damage Resistance.
    SpeciesOptionDef{"Tiefling", "Abyssal",  0, 0, 1u << Poison},
    SpeciesOptionDef{"Tiefling", "Chthonic", 0, 0, 1u << Necrotic},
    SpeciesOptionDef{"Tiefling", "Infernal", 0, 0, 1u << Fire},
};

// A species' one-time traits with its option folded in: what setSpecies() applies.
struct SpeciesTraits {
    int speed_walk{0};
    int darkvision{0};
    std::uint32_t magic_resist_mask{0};
    int save_advantage_bits{0};
    std::uint32_t flags{0};

    [[nodiscard]] constexpr bool resists(MagicDamage_t t) const noexcept {
        return (magic_resist_mask >> static_cast<unsigned>(t)) & 1u;
    }
};

[[nodiscard]] constexpr SpeciesTraits speciesTraits(const SpeciesDef& d,
                                                    std::string_view option) noexcept {
    SpeciesTraits t{d.speed_walk, d.darkvision, d.magic_resist_mask, d.save_advantage_bits, d.flags};
    for (const auto& o : kSpeciesOptionTable)
        if (o.species == d.name && o.option == option) {
            if (o.speed_walk > t.speed_walk) t.speed_walk = o.speed_walk;
            if (o.darkvision > t.darkvision) t.darkvision = o.darkvision;
            t.magic_resist_mask |= o.magic_resist_mask;
        }
    return t;
}

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
    int hp_bonus{0};                    // Dwarven Toughness HP folded into hp_max / hp_cur
    bool perception_prof{false};        // Keen Senses set perception_prof (it was off)
};

// A spell a trait grants (D3): always prepared, cast with its own ability, and (for a
// leveled spell) a few casts per Long Rest that need no slot. Generic so a feat (Magic
// Initiate, Fey Touched) can add entries later; species entries carry source "species"
// and are rebuilt by Stats::syncSpeciesSpells(). A leveled spell can also be cast with a
// slot when the caster has one. Every entry recharges on a Long Rest.
struct GrantedSpell {
    std::string name;
    std::string source;      // "species", …
    int unlock_level{1};     // character level the spell needs
    int uses{0};             // 0 = cantrip (at will); > 0 = free casts per Long Rest; -1 = PB
    int free_used{0};        // free casts spent since the last Long Rest
    int ability{-1};         // SaveAbility_t ordinal its casts use; -1 = the caster's own
};

// What a species (and option) grants. option "" = every option of the species.
// uses as in GrantedSpell (0 cantrip, 1 = once per Long Rest, -1 = PB per Long Rest).
struct SpeciesSpellDef {
    std::string_view species;
    std::string_view option;
    std::string_view spell;
    int unlock_level;
    int uses;
};

inline constexpr std::array kSpeciesSpellTable{
    // Elven Lineage: a cantrip at 1, a spell at 3 and at 5, each once per Long Rest.
    SpeciesSpellDef{"Elf", "Drow",     "Dancing Lights",     1, 0},
    SpeciesSpellDef{"Elf", "Drow",     "Faerie Fire",        3, 1},
    SpeciesSpellDef{"Elf", "Drow",     "Darkness",           5, 1},
    SpeciesSpellDef{"Elf", "High Elf", "Prestidigitation",   1, 0},
    SpeciesSpellDef{"Elf", "High Elf", "Detect Magic",       3, 1},
    SpeciesSpellDef{"Elf", "High Elf", "Misty Step",         5, 1},
    SpeciesSpellDef{"Elf", "Wood Elf", "Druidcraft",         1, 0},
    SpeciesSpellDef{"Elf", "Wood Elf", "Longstrider",        3, 1},
    SpeciesSpellDef{"Elf", "Wood Elf", "Pass without Trace", 5, 1},
    // Gnomish Lineage. Forest Gnome: Speak with Animals PB times per Long Rest.
    SpeciesSpellDef{"Gnome", "Forest Gnome", "Minor Illusion",     1, 0},
    SpeciesSpellDef{"Gnome", "Forest Gnome", "Speak with Animals", 1, -1},
    SpeciesSpellDef{"Gnome", "Rock Gnome",   "Mending",            1, 0},
    SpeciesSpellDef{"Gnome", "Rock Gnome",   "Prestidigitation",   1, 0},
    // Fiendish Legacy, plus Otherworldly Presence (Thaumaturgy) for every legacy.
    SpeciesSpellDef{"Tiefling", "",         "Thaumaturgy",         1, 0},
    SpeciesSpellDef{"Tiefling", "Abyssal",  "Poison Spray",        1, 0},
    SpeciesSpellDef{"Tiefling", "Abyssal",  "Ray of Sickness",     3, 1},
    SpeciesSpellDef{"Tiefling", "Abyssal",  "Hold Person",         5, 1},
    SpeciesSpellDef{"Tiefling", "Chthonic", "Chill Touch",         1, 0},
    SpeciesSpellDef{"Tiefling", "Chthonic", "False Life",          3, 1},
    SpeciesSpellDef{"Tiefling", "Chthonic", "Ray of Enfeeblement", 5, 1},
    SpeciesSpellDef{"Tiefling", "Infernal", "Fire Bolt",           1, 0},
    SpeciesSpellDef{"Tiefling", "Infernal", "Hellish Rebuke",      3, 1},
    SpeciesSpellDef{"Tiefling", "Infernal", "Darkness",            5, 1},
};

// Out of the struct so tests/test_board_snapshot.py's member parser sees only fields.
[[nodiscard]] constexpr bool operator==(const SpeciesApplied& a, const SpeciesApplied& b) noexcept {
    return a.speed_from == b.speed_from && a.speed_to == b.speed_to
        && a.darkvision_from == b.darkvision_from && a.darkvision_to == b.darkvision_to
        && a.magic_resist_mask == b.magic_resist_mask
        && a.save_advantage_bits == b.save_advantage_bits
        && a.hp_bonus == b.hp_bonus && a.perception_prof == b.perception_prof;
}

} // namespace rpg
