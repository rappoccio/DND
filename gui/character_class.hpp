#pragma once
#include <array>
#include <algorithm>
#include <vector>
#include <string>

namespace rpg {

enum CharacterClass {
    CharClassNone=0, Barbarian, Fighter, Monk, Rogue,
    Bard, Cleric, Druid, Sorcerer, Wizard,
    Paladin, Ranger, Warlock, NumCharacterClass
};

enum CasterType { CasterNone=0, CasterFull, CasterHalf, CasterPact };

inline CasterType get_caster_type(CharacterClass cls) {
    switch (cls) {
        case Bard: case Cleric: case Druid:
        case Sorcerer: case Wizard:  return CasterFull;
        case Paladin: case Ranger:   return CasterHalf;
        case Warlock:                return CasterPact;
        default:                     return CasterNone;
    }
}

inline std::array<int,9> compute_class_slots(CharacterClass cls, int lvl) {
    if (lvl < 1 || lvl > 20) lvl = 1;
    lvl--;  // Convert to 0-indexed

    // Full caster table A (Bard, Cleric, Druid — 0 slots at level 1)
    static constexpr std::array<std::array<int,9>,20> kFullA{{
        {0,0,0,0,0,0,0,0,0},  // 1
        {2,0,0,0,0,0,0,0,0},  // 2
        {3,0,0,0,0,0,0,0,0},  // 3
        {3,2,0,0,0,0,0,0,0},  // 4
        {4,3,0,0,0,0,0,0,0},  // 5
        {4,3,0,0,0,0,0,0,0},  // 6
        {4,3,2,0,0,0,0,0,0},  // 7
        {4,3,3,0,0,0,0,0,0},  // 8
        {4,3,3,1,0,0,0,0,0},  // 9
        {4,3,3,2,0,0,0,0,0},  // 10
        {4,3,3,2,1,0,0,0,0},  // 11
        {4,3,3,2,1,0,0,0,0},  // 12
        {4,3,3,2,1,1,0,0,0},  // 13
        {4,3,3,2,1,1,0,0,0},  // 14
        {4,3,3,2,2,1,1,0,0},  // 15
        {4,3,3,2,2,1,1,0,0},  // 16
        {4,3,3,2,2,1,1,1,0},  // 17
        {4,3,3,3,2,1,1,1,0},  // 18
        {4,3,3,3,2,2,1,1,1},  // 19
        {4,3,3,3,2,2,2,1,1}   // 20
    }};

    // Full caster table B (Sorcerer, Wizard — start with 2 slots at level 1)
    static constexpr std::array<std::array<int,9>,20> kFullB{{
        {2,0,0,0,0,0,0,0,0},  // 1
        {3,0,0,0,0,0,0,0,0},  // 2
        {4,2,0,0,0,0,0,0,0},  // 3
        {4,3,0,0,0,0,0,0,0},  // 4
        {4,3,2,0,0,0,0,0,0},  // 5
        {4,3,3,0,0,0,0,0,0},  // 6
        {4,3,3,1,0,0,0,0,0},  // 7
        {4,3,3,2,0,0,0,0,0},  // 8
        {4,3,3,3,1,0,0,0,0},  // 9
        {4,3,3,3,2,0,0,0,0},  // 10
        {4,3,3,3,2,1,0,0,0},  // 11
        {4,3,3,3,2,1,0,0,0},  // 12
        {4,3,3,3,2,1,1,0,0},  // 13
        {4,3,3,3,2,1,1,0,0},  // 14
        {4,3,3,3,2,2,1,1,0},  // 15
        {4,3,3,3,2,2,1,1,0},  // 16
        {4,3,3,3,2,2,1,1,1},  // 17
        {4,3,3,3,3,2,1,1,1},  // 18
        {4,3,3,3,3,2,2,1,1},  // 19
        {4,3,3,3,3,2,2,2,1}   // 20
    }};

    // Half caster table (Paladin, Ranger)
    static constexpr std::array<std::array<int,9>,20> kHalf{{
        {0,0,0,0,0,0,0,0,0},  // 1
        {2,0,0,0,0,0,0,0,0},  // 2
        {3,0,0,0,0,0,0,0,0},  // 3
        {3,0,0,0,0,0,0,0,0},  // 4
        {4,2,0,0,0,0,0,0,0},  // 5
        {4,2,0,0,0,0,0,0,0},  // 6
        {4,3,0,0,0,0,0,0,0},  // 7
        {4,3,0,0,0,0,0,0,0},  // 8
        {4,3,2,0,0,0,0,0,0},  // 9
        {4,3,2,0,0,0,0,0,0},  // 10
        {4,3,3,0,0,0,0,0,0},  // 11
        {4,3,3,0,0,0,0,0,0},  // 12
        {4,3,3,1,0,0,0,0,0},  // 13
        {4,3,3,1,0,0,0,0,0},  // 14
        {4,3,3,2,0,0,0,0,0},  // 15
        {4,3,3,2,0,0,0,0,0},  // 16
        {4,3,3,2,1,0,0,0,0},  // 17
        {4,3,3,2,1,0,0,0,0},  // 18
        {4,3,3,2,1,1,0,0,0},  // 19
        {4,3,3,2,1,1,0,0,0}   // 20
    }};

    // Pact magic table (Warlock — all slots packed into one level)
    static constexpr std::array<std::array<int,9>,20> kPact{{
        {1,0,0,0,0,0,0,0,0},  // 1: 1 slot at 1st level
        {2,0,0,0,0,0,0,0,0},  // 2: 2 slots at 1st level
        {0,2,0,0,0,0,0,0,0},  // 3: 2 slots at 2nd level
        {0,2,0,0,0,0,0,0,0},  // 4
        {0,0,2,0,0,0,0,0,0},  // 5: 2 slots at 3rd level
        {0,0,2,0,0,0,0,0,0},  // 6
        {0,0,0,2,0,0,0,0,0},  // 7: 2 slots at 4th level
        {0,0,0,2,0,0,0,0,0},  // 8
        {0,0,0,0,2,0,0,0,0},  // 9: 2 slots at 5th level
        {0,0,0,0,2,0,0,0,0},  // 10
        {0,0,0,0,3,0,0,0,0},  // 11: 3 slots at 5th level
        {0,0,0,0,3,0,0,0,0},  // 12
        {0,0,0,0,3,0,0,0,0},  // 13
        {0,0,0,0,3,0,0,0,0},  // 14
        {0,0,0,0,3,0,0,0,0},  // 15
        {0,0,0,0,3,0,0,0,0},  // 16
        {0,0,0,0,4,0,0,0,0},  // 17: 4 slots at 5th level
        {0,0,0,0,4,0,0,0,0},  // 18
        {0,0,0,0,4,0,0,0,0},  // 19
        {0,0,0,0,4,0,0,0,0}   // 20
    }};

    switch (cls) {
        case Bard: case Cleric: case Druid:
            return kFullA[lvl];
        case Sorcerer: case Wizard:
            return kFullB[lvl];
        case Paladin: case Ranger:
            return kHalf[lvl];
        case Warlock:
            return kPact[lvl];
        default:
            return {};  // Non-casters: all zeros
    }
}

// ── Skill Enum (18 D&D 5e skills) ───────────────────────────────────────
enum Skill {
    SkillNone = 0,
    Acrobatics, AnimalHandling, Arcana, Athletics, Deception,
    History, Insight, Intimidation, Investigation, Medicine,
    Nature, Perception, Performance, Persuasion, Religion,
    SleigtOfHand, Stealth, Survival,
    NumSkill
};

// ── Background Enum (16 D&D 5e 2024 PHB backgrounds) ───────────────────
enum Background {
    BackgroundNone = 0,
    Acolyte, Artisan, Charlatan, Criminal, Entertainer,
    Farmer, Guard, Guide, Hermit, Merchant,
    Noble, Sage, Sailor, Scribe, Soldier,
    Wayfarer,
    NumBackground
};

// ── Alignment Enum (9 D&D alignments) ────────────────────────────────────
enum Alignment {
    AlignmentNone = 0,
    LawfulGood, LawfulNeutral, LawfulEvil,
    NeutralGood, TrueNeutral, NeutralEvil,
    ChaoticGood, ChaoticNeutral, ChaoticEvil,
    NumAlignment
};

// ── Barbarian Subclass Enum (2024 D&D) ──────────────────────────────────
enum BarbianSubclass {
    BarbianSubclassNone = 0,
    BerserkerPath, WildHeartPath, WorldTreePath, ZealotPath,
    NumBarbianSubclass
};

// Wild Heart Rage of the Wilds animal choice
enum WildHeartRageChoice {
    WildHeartNone = 0,
    BearForm, EagleForm, WolfForm,
    NumWildHeartRageChoice
};

enum WildHeartAspect {
    AspectNone = 0,
    OwlAspect,      // Darkvision 60ft
    PantherAspect,  // Climb speed = Walk speed
    SalmonAspect,   // Swim speed = Walk speed
    NumWildHeartAspect
};

// ── Wizard Subclass Enum (2024 D&D) ──────────────────────────────────
enum WizardSubclass {
    WizardSubclassNone = 0,
    AbjurerPath, DivinierPath, EvokerPath, IllusionistPath,
    NumWizardSubclass
};

// ── Warlock Subclass (Patron) Enum (2024 D&D) ────────────────────────
enum WarlockSubclass {
    WarlockSubclassNone = 0,
    ArchfeyPath, CelestialPath, FiendPath, GreatOldOnePath,
    NumWarlockSubclass
};

// ── Rogue Subclass Enum (2024 D&D) ───────────────────────────────────
enum RogueSubclass {
    RogueSubclassNone = 0,
    ArcaneTricksterPath, AssassinPath, SoulknifePath, ThiefPath,
    NumRogueSubclass
};

// ── Cleric Subclass (Divine Domain) Enum (2024 D&D) ──────────────────
enum ClericSubclass {
    ClericSubclassNone = 0,
    LifeDomain, LightDomain, TrickeryDomain, WarDomain,
    NumClericSubclass
};

// ── Cleric Blessed Strikes choice (L7): Divine Strike or Potent Spellcasting ──
enum BlessedStrike {
    BlessedStrikeNone = 0,
    BlessedStrikeDivineStrike,
    BlessedStrikePotentSpellcasting,
    NumBlessedStrike
};

// ── Fighter Subclass Enum (2024 D&D) ─────────────────────────────────────
enum FighterSubclass {
    FighterSubclassNone = 0,
    ChampionPath, BattleMasterPath, PsiWarriorPath, EldritchKnightPath,
    NumFighterSubclass
};

// ── Druid Circle Enum (2024 D&D) ──────────────────────────────────────
enum DruidCircle {
    DruidCircleNone = 0,
    CircleOfMoon, CircleOfLand, CircleOfSea, CircleOfStars, CircleOfSpores, CircleOfWildfire,
    NumDruidCircle
};

// ── Monk Subclass Enum (2024 D&D) ────────────────────────────────────
enum MonkSubclass {
    MonkSubclassNone = 0,
    WarriorOfTheOpenHandPath, WarriorOfMercyPath, WarriorOfShadowPath, WarriorOfFourElementsPath,
    NumMonkSubclass
};

// ── Paladin Oath Enum (2024 D&D) ────────────────────────────────────
enum PaladinOath {
    PaladinOathNone = 0,
    OathOfDevotionPath, OathOftheMountedWarriorPath, OathOfRedemptionPath, OathOfVengeancePath,
    NumPaladinOath
};

// ── Origin Struct (Background with abilities, feat, and skills) ──────────
struct Origin {
    Background background;
    std::array<int, 3> ability_increases;  // 3 ability indices (0-5)
    std::string origin_feat;                // e.g., "Magic Initiate (Cleric)"
    std::vector<Skill> skill_proficiencies; // skills granted by origin
};

// ── Origin Data (all 16 2024 PHB backgrounds) ────────────────────────────
static const std::array<Origin, 16> kOrigins = {{
    // Acolyte: INT, WIS, CHA | Magic Initiate (Cleric) | Insight, Religion
    {Acolyte, {3, 4, 5}, "Magic Initiate (Cleric)", {Insight, Religion}},

    // Artisan: STR, DEX, INT | Crafter | Investigation, Persuasion
    {Artisan, {0, 1, 3}, "Crafter", {Investigation, Persuasion}},

    // Charlatan: DEX, CON, CHA | Skilled | Deception, Sleight of Hand
    {Charlatan, {1, 2, 5}, "Skilled", {Deception, SleigtOfHand}},

    // Criminal: DEX, CON, INT | Alert | Sleight of Hand, Stealth
    {Criminal, {1, 2, 3}, "Alert", {SleigtOfHand, Stealth}},

    // Entertainer: STR, DEX, CHA | Musician | Acrobatics, Performance
    {Entertainer, {0, 1, 5}, "Musician", {Acrobatics, Performance}},

    // Farmer: STR, CON, WIS | Tough | Animal Handling, Nature
    {Farmer, {0, 2, 4}, "Tough", {AnimalHandling, Nature}},

    // Guard: STR, INT, WIS | Alert | Athletics, Perception
    {Guard, {0, 3, 4}, "Alert", {Athletics, Perception}},

    // Guide: DEX, CON, WIS | Magic Initiate (Druid) | Stealth, Survival
    {Guide, {1, 2, 4}, "Magic Initiate (Druid)", {Stealth, Survival}},

    // Hermit: CON, WIS, CHA | Healer | Medicine, Religion
    {Hermit, {2, 4, 5}, "Healer", {Medicine, Religion}},

    // Merchant: CON, INT, CHA | Lucky | Animal Handling, Persuasion
    {Merchant, {2, 3, 5}, "Lucky", {AnimalHandling, Persuasion}},

    // Noble: STR, INT, CHA | Skilled | History, Persuasion
    {Noble, {0, 3, 5}, "Skilled", {History, Persuasion}},

    // Sage: CON, INT, WIS | Magic Initiate (Wizard) | Arcana, History
    {Sage, {2, 3, 4}, "Magic Initiate (Wizard)", {Arcana, History}},

    // Sailor: STR, DEX, WIS | Tavern Brawler | Acrobatics, Perception
    {Sailor, {0, 1, 4}, "Tavern Brawler", {Acrobatics, Perception}},

    // Scribe: DEX, INT, WIS | Skilled | Investigation, Perception
    {Scribe, {1, 3, 4}, "Skilled", {Investigation, Perception}},

    // Soldier: STR, DEX, CON | Savage Attacker | Athletics, Intimidation
    {Soldier, {0, 1, 2}, "Savage Attacker", {Athletics, Intimidation}},

    // Wayfarer: DEX, WIS, CHA | Lucky | Insight, Stealth
    {Wayfarer, {1, 4, 5}, "Lucky", {Insight, Stealth}},
}};

// Helper to get Origin by Background
inline const Origin& getOrigin(Background bg) {
    if (bg >= 1 && bg < static_cast<int>(kOrigins.size()) + 1) {
        return kOrigins[bg - 1];  // 0-indexed array, 1-indexed enum
    }
    // Fallback (should never happen in practice)
    return kOrigins[0];
}

} // namespace rpg
