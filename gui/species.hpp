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
// SP5:
inline constexpr std::uint32_t kSpeciesBreathWeapon  = 1u << 14;  // Dragonborn: Breath Weapon (D7)
inline constexpr std::uint32_t kSpeciesDraconicFlight = 1u << 15; // Dragonborn: Draconic Flight (D8)
// SP6:
inline constexpr std::uint32_t kSpeciesGiantAncestry = 1u << 16;  // Goliath: Giant Ancestry (D9)
inline constexpr std::uint32_t kSpeciesLargeForm     = 1u << 17;  // Goliath: Large Form (D6)
// MORE_SPECIES_PLAN.md MS1:
inline constexpr std::uint32_t kSpeciesDeathSaveAdv  = 1u << 18;  // Reborn: Adv. on death saves
inline constexpr std::uint32_t kSpeciesFairyFlight   = 1u << 19;  // Fairy: fly = walk unless Medium/Heavy armor (D11)
inline constexpr std::uint32_t kSpeciesStealthProf   = 1u << 20;  // Bugbear: Stealth proficiency
// MS3:
inline constexpr std::uint32_t kSpeciesLongLimbed     = 1u << 21;  // Bugbear: +5 ft melee reach on its turn (D12)
inline constexpr std::uint32_t kSpeciesSurpriseAttack = 1u << 22;  // Bugbear: +2d6 vs a creature yet to act, 1/combat (D13)
inline constexpr std::uint32_t kSpeciesPastLife       = 1u << 23;  // Reborn: +1d6 to a failed check, PB/Long Rest (D10)

// Creature type a species makes its member (MORE_SPECIES_PLAN.md D1). Humanoid is the default
// and sets nothing; Fey sets Stats::is_fey.
enum class SpeciesCreatureType : std::uint8_t { Humanoid, Fey };

// Condition-save Advantage (D5): the condition a flag covers, "" for a flag that covers none.
[[nodiscard]] constexpr bool speciesFlagCoversCondition(std::uint32_t flags,
                                                        std::string_view cond) noexcept {
    return ((flags & kSpeciesBrave) && cond == "Frightened")
        || ((flags & kSpeciesFeyAncestry) && cond == "Charmed")
        || ((flags & kSpeciesResilience) && cond == "Poisoned");
}

// SaveAbility_t ordinals a species spell ability may take (agent.hpp can't see condition.hpp).
inline constexpr int kSpeciesAbilityCon = 2;   // Breath Weapon's fixed ability (D7)
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
// Lupin Werewolf Instincts (MORE_SPECIES_PLAN.md D2). Survival is not modelled: flavor only.
inline constexpr std::array<std::string_view, 3> kLupinSkills{"Perception", "Stealth", "Survival"};
// Reborn Strange Endurance: one Resistance, picked as the species option.
inline constexpr std::array<std::string_view, 3> kStrangeEndurance{"Cold", "Necrotic", "Poison"};

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
    SpeciesCreatureType creature_type{SpeciesCreatureType::Humanoid};
    // Skillful-style skill picks ("" span = kSpeciesSkills), for a species with kSpeciesSkillful.
    std::span<const std::string_view> skill_options{};

    [[nodiscard]] constexpr std::span<const std::string_view> skillOptions() const noexcept {
        return skill_options.empty() ? std::span<const std::string_view>(kSpeciesSkills) : skill_options;
    }
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
    SpeciesDef{.name = "Dragonborn", .darkvision = 60,
               .flags = kSpeciesBreathWeapon | kSpeciesDraconicFlight,
               .option_label = "Ancestry", .options = kDraconicAncestries},
    SpeciesDef{.name = "Dwarf", .darkvision = 120, .magic_resist_mask = 1u << Poison,
               .flags = kSpeciesResilience | kSpeciesToughness},
    SpeciesDef{.name = "Elf", .darkvision = 60,
               .flags = kSpeciesSpellAbility | kSpeciesFeyAncestry | kSpeciesKeenSenses,
               .option_label = "Lineage", .options = kElvenLineages},
    SpeciesDef{.name = "Gnome", .darkvision = 60, .size_options = kSpeciesSizeSmall,
               .save_advantage_bits = kGnomishCunningBits, .flags = kSpeciesSpellAbility,
               .option_label = "Lineage", .options = kGnomishLineages},
    SpeciesDef{.name = "Goliath", .speed_walk = 35,
               .flags = kSpeciesPowerfulBuild | kSpeciesGiantAncestry | kSpeciesLargeForm,
               .option_label = "Ancestry", .options = kGiantAncestries},
    SpeciesDef{.name = "Halfling", .size_options = kSpeciesSizeSmall,
               .flags = kSpeciesBrave | kSpeciesLuck},
    SpeciesDef{.name = "Human", .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesHeroic | kSpeciesSkillful | kSpeciesVersatile},
    SpeciesDef{.name = "Orc", .darkvision = 120, .flags = kSpeciesAdrenaline | kSpeciesRelentless},
    SpeciesDef{.name = "Tiefling", .darkvision = 60,
               .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesSpellAbility, .option_label = "Legacy", .options = kFiendishLegacies},
    // MORE_SPECIES_PLAN.md (MS1, D3). Bugbear and Fairy are the Monsters of the Multiverse
    // text with the ability scores and languages ignored.
    SpeciesDef{.name = "Aasimar", .darkvision = 60,
               .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .magic_resist_mask = (1u << Necrotic) | (1u << Radiant)},
    SpeciesDef{.name = "Hexblood", .darkvision = 60,
               .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesSpellAbility, .creature_type = SpeciesCreatureType::Fey},
    SpeciesDef{.name = "Lupin", .darkvision = 60,
               .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesSkillful, .skill_options = kLupinSkills},
    SpeciesDef{.name = "Reborn", .size_options = kSpeciesSizeSmall | kSpeciesSizeMedium,
               .flags = kSpeciesSkillful | kSpeciesDeathSaveAdv | kSpeciesPastLife,
               .option_label = "Endurance", .options = kStrangeEndurance},
    // Powerful Build is off: MotM's is carrying capacity only (not modelled), not the
    // Goliath grapple-escape Advantage the flag gives (D3).
    SpeciesDef{.name = "Bugbear", .darkvision = 60,
               .flags = kSpeciesFeyAncestry | kSpeciesStealthProf | kSpeciesLongLimbed
                      | kSpeciesSurpriseAttack},
    SpeciesDef{.name = "Fairy", .size_options = kSpeciesSizeSmall,
               .flags = kSpeciesSpellAbility | kSpeciesFairyFlight,
               .creature_type = SpeciesCreatureType::Fey},
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
    // Reborn Strange Endurance → Damage Resistance.
    SpeciesOptionDef{"Reborn", "Cold",     0, 0, 1u << Cold},
    SpeciesOptionDef{"Reborn", "Necrotic", 0, 0, 1u << Necrotic},
    SpeciesOptionDef{"Reborn", "Poison",   0, 0, 1u << Poison},
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

// Breath Weapon (D7): the damage type of a Draconic Ancestry, the type it resists; -1 for
// anything else. Read at cast time, so a changed ancestry needs no rebuilt spell.
[[nodiscard]] constexpr int draconicDamageType(std::string_view option) noexcept {
    for (const auto& o : kSpeciesOptionTable)
        if (o.species == "Dragonborn" && o.option == option)
            for (int t = 0; t < NumMagicDamage_t; ++t)
                if ((o.magic_resist_mask >> static_cast<unsigned>(t)) & 1u) return t;
    return -1;
}

// The pool a Breath Weapon spell's resource_name names. It is a species counter
// (Stats::breath_weapon_used), not an entry in Stats::resources, which class setup clears.
inline constexpr std::string_view kBreathWeaponPool = "Breath Weapon";
inline constexpr int kDraconicFlightRounds = 100;   // 10 minutes (D8)
inline constexpr int kDraconicFlightLevel  = 5;

// Goliath (SP6). Giant Ancestry (D9): one benefit by ancestry, PB uses per Long Rest shared
// by every use. Fire / Frost / Hill ride a hit (offered like a maneuver); Cloud is a Bonus
// Action teleport; Stone and Storm are reactions to taking damage.
enum class GiantAncestry { None, Cloud, Fire, Frost, Hill, Stone, Storm };
[[nodiscard]] constexpr GiantAncestry giantAncestryOf(std::string_view option) noexcept {
    return option == "Cloud" ? GiantAncestry::Cloud : option == "Fire" ? GiantAncestry::Fire
         : option == "Frost" ? GiantAncestry::Frost : option == "Hill" ? GiantAncestry::Hill
         : option == "Stone" ? GiantAncestry::Stone : option == "Storm" ? GiantAncestry::Storm
         : GiantAncestry::None;
}
inline constexpr int kCloudsJauntCells   = 6;    // 30 ft
inline constexpr int kStormsThunderCells = 12;   // 60 ft
inline constexpr int kFrostsChillSpeed   = 10;   // ft of Speed lost
// Large Form (D6, level 5): a Bonus Action, 10 minutes, once per Long Rest. Large is a 2×2
// footprint; +10 ft Speed; Advantage on Strength checks.
inline constexpr int kLargeFormLevel  = 5;
inline constexpr int kLargeFormRounds = 100;
inline constexpr int kLargeFormSpeed  = 10;

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
    bool fey{false};                    // a Fey species set is_fey (it was off) (D1)
    int fly_from{0};                    // Fairy Flight: fly Speed before / as last set (D11)
    int fly_to{0};
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
// ability: a fixed SaveAbility_t ordinal, or -1 for the species' pick (kSpeciesSpellAbility).
struct SpeciesSpellDef {
    std::string_view species;
    std::string_view option;
    std::string_view spell;
    int unlock_level;
    int uses;
    int ability{-1};
};

inline constexpr std::array kSpeciesSpellTable{
    // Breath Weapon (D7): one entry per shape, at will here; the casts come out of the
    // PB-per-Long-Rest pool the spells' resource_name names. CON sets the DC.
    SpeciesSpellDef{"Dragonborn", "", "Breath Weapon (Cone)", 1, 0, kSpeciesAbilityCon},
    SpeciesSpellDef{"Dragonborn", "", "Breath Weapon (Line)", 1, 0, kSpeciesAbilityCon},
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
    // MORE_SPECIES_PLAN.md MS2 (D4). Aasimar Light Bearer: Light, cast with CHA.
    SpeciesSpellDef{"Aasimar", "", "Light", 1, 0, kSpeciesAbilityCha},
    // Hexblood Hex Magic: Disguise Self and Hex, each once per Long Rest, picked ability.
    SpeciesSpellDef{"Hexblood", "", "Disguise Self", 1, 1},
    SpeciesSpellDef{"Hexblood", "", "Hex",           1, 1},
    // Fairy Magic: Druidcraft; Faerie Fire at 3 and Enlarge/Reduce at 5, once per Long Rest each.
    SpeciesSpellDef{"Fairy", "", "Druidcraft",     1, 0},
    SpeciesSpellDef{"Fairy", "", "Faerie Fire",    3, 1},
    SpeciesSpellDef{"Fairy", "", "Enlarge/Reduce", 5, 1},
};

// Out of the struct so tests/test_board_snapshot.py's member parser sees only fields.
[[nodiscard]] constexpr bool operator==(const SpeciesApplied& a, const SpeciesApplied& b) noexcept {
    return a.speed_from == b.speed_from && a.speed_to == b.speed_to
        && a.darkvision_from == b.darkvision_from && a.darkvision_to == b.darkvision_to
        && a.magic_resist_mask == b.magic_resist_mask
        && a.save_advantage_bits == b.save_advantage_bits
        && a.hp_bonus == b.hp_bonus && a.perception_prof == b.perception_prof
        && a.fey == b.fey && a.fly_from == b.fly_from && a.fly_to == b.fly_to;
}

} // namespace rpg
