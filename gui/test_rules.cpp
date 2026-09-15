// ─────────────────────────────────────────────────────────────────────────────
//  test_rules.cpp  –  direct unit tests for rules.hpp
// ─────────────────────────────────────────────────────────────────────────────
//
//  COMBAT_REFACTOR_PLAN.md success criterion: "rules.hpp has direct unit tests
//  that construct no CombatEngine and no BattleMap." This is that test — and it
//  is a C++ test because it has to be: rules:: is not exposed to pybind11, so
//  every Python suite that exercises these primitives necessarily reaches them
//  through a CombatEngine and cannot satisfy the criterion.
//
//  Scope note (the criterion is only half-achievable as written): the functions
//  covered here are exactly those that need neither an engine nor a map —
//  the dice layer (CombatContext only), the weapon attack/damage modifiers and
//  the spell DCs (Agent::Stats / Weapon only), plus CombatContext's JSON
//  round-trip. calculateAC, isHoldingShield, canEquipArmor, saveModFor,
//  saveAdvantageFor and the five aura queries all take `const BattleMap&` by
//  design and so are deliberately NOT covered here; they stay covered by the
//  Python suites (test_ac_dex.py, test_paladin_auras.py, test_advantage_aura.py,
//  test_bless.py, …) which build a real map.
//
//  Built as its own executable target (see CMakeLists.txt) and driven from
//  tests/test_rules.py so it registers in tests/run_all_tests.py like every
//  other suite.
// ─────────────────────────────────────────────────────────────────────────────

#include "rules.hpp"

#include <cstdint>
#include <cstdio>
#include <string>

namespace {

int g_failures = 0;
int g_checks   = 0;

void check(bool ok, const std::string& what)
{
    ++g_checks;
    if (!ok) {
        ++g_failures;
        std::printf("  FAIL: %s\n", what.c_str());
    }
}

void checkEq(int got, int want, const std::string& what)
{
    ++g_checks;
    if (got != want) {
        ++g_failures;
        std::printf("  FAIL: %s (got %d, want %d)\n", what.c_str(), got, want);
    }
}

using rpg::CombatContext;
namespace rules = rpg::rules;

constexpr uint32_t kSeed = 12345u;

CombatContext seeded(uint32_t seed = kSeed)
{
    CombatContext ctx;
    ctx.rng_.seed(seed);
    return ctx;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Dice — rules::roll / rollAdvantage / rollDisadvantage
// ─────────────────────────────────────────────────────────────────────────────

void testRollBounds()
{
    std::printf("roll: bounds and determinism\n");

    CombatContext ctx = seeded();
    bool in_range = true;
    for (int i = 0; i < 500; ++i) {
        int r = rules::roll(ctx, 20);
        if (r < 1 || r > 20) in_range = false;
    }
    check(in_range, "roll(20) always lands in [1,20]");

    // Same seed → same stream. This is the property the whole determinism
    // harness rests on, tested here with no engine in the picture.
    CombatContext a = seeded();
    CombatContext b = seeded();
    bool same = true;
    for (int i = 0; i < 100; ++i)
        if (rules::roll(a, 20) != rules::roll(b, 20)) same = false;
    check(same, "two contexts seeded alike produce identical roll streams");

    CombatContext c = seeded(777u);
    CombatContext d = seeded(778u);
    bool differs = false;
    for (int i = 0; i < 100; ++i)
        if (rules::roll(c, 20) != rules::roll(d, 20)) differs = true;
    check(differs, "different seeds diverge");
}

void testRollModifier()
{
    std::printf("roll: flat modifier\n");

    CombatContext a = seeded();
    CombatContext b = seeded();
    checkEq(rules::roll(a, 20, 5), rules::roll(b, 20) + 5, "roll(20,+5) == roll(20) + 5");
}

void testPendingRollBonus()
{
    std::printf("roll: Bardic Inspiration pending bonus\n");

    CombatContext a = seeded();
    CombatContext b = seeded();
    a.pending_roll_bonus_ = 3;

    checkEq(rules::roll(a, 20), rules::roll(b, 20) + 3, "pending roll bonus applies to the next d20");
    checkEq(a.pending_roll_bonus_, 0, "pending roll bonus is cleared after one use");
    checkEq(rules::roll(a, 20), rules::roll(b, 20), "pending roll bonus does not apply twice");
}

void testPortentDie()
{
    std::printf("roll: Portent die replaces the roll\n");

    CombatContext ctx = seeded();
    ctx.pending_portent_die_ = 17;
    checkEq(rules::roll(ctx, 20), 17, "portent die replaces the d20 result");
    checkEq(ctx.pending_portent_die_, -1, "portent die is consumed");

    // Portent replaces the DIE; the flat modifier and the Bardic bonus still stack on top.
    CombatContext ctx2 = seeded();
    ctx2.pending_portent_die_ = 17;
    ctx2.pending_roll_bonus_ = 3;
    checkEq(rules::roll(ctx2, 20, 2), 22, "portent 17 + modifier 2 + bardic 3 == 22");
}

void testPendingAdvantageIsD20Only()
{
    std::printf("roll: one-shot advantage applies to d20 Tests only\n");

    CombatContext ctx = seeded();
    ctx.pending_advantage_ = 1;
    (void)rules::roll(ctx, 6);
    checkEq(ctx.pending_advantage_, 1, "a damage die does not consume pending advantage");
    (void)rules::roll(ctx, 20);
    checkEq(ctx.pending_advantage_, 0, "a d20 Test does consume pending advantage");
}

void testAdvantageDisadvantageDistribution()
{
    std::printf("rollAdvantage / rollDisadvantage: distribution\n");

    constexpr int N = 4000;
    CombatContext adv = seeded();
    CombatContext str = seeded();
    CombatContext dis = seeded();

    long adv_sum = 0, str_sum = 0, dis_sum = 0;
    for (int i = 0; i < N; ++i) {
        adv_sum += rules::rollAdvantage(adv, 20);
        str_sum += rules::roll(str, 20);
        dis_sum += rules::rollDisadvantage(dis, 20);
    }
    const double adv_mean = static_cast<double>(adv_sum) / N;
    const double str_mean = static_cast<double>(str_sum) / N;
    const double dis_mean = static_cast<double>(dis_sum) / N;

    // Expectations: 13.825 / 10.5 / 7.175. Margins are wide enough that a fixed
    // seed can never flake, but tight enough to catch a swapped min/max.
    check(adv_mean > 13.0, "advantage mean is well above straight");
    check(str_mean > 9.5 && str_mean < 11.5, "straight d20 mean is near 10.5");
    check(dis_mean < 8.0, "disadvantage mean is well below straight");
    check(adv_mean > str_mean && str_mean > dis_mean, "adv > straight > dis");
}

void testAdvantageCancellation()
{
    std::printf("rollAdvantage / rollDisadvantage: 5e cancellation rule\n");

    // A pending DISadvantage cancels an explicit advantage → one straight roll.
    {
        CombatContext a = seeded();
        CombatContext b = seeded();
        a.pending_advantage_ = -1;
        checkEq(rules::rollAdvantage(a, 20), rules::roll(b, 20),
                "pending disadvantage cancels explicit advantage (single straight roll)");
        checkEq(a.pending_advantage_, 0, "the cancelling pending value is consumed");
    }

    // ...and the mirror: a pending ADVantage cancels an explicit disadvantage.
    {
        CombatContext a = seeded();
        CombatContext b = seeded();
        a.pending_advantage_ = 1;
        checkEq(rules::rollDisadvantage(a, 20), rules::roll(b, 20),
                "pending advantage cancels explicit disadvantage (single straight roll)");
        checkEq(a.pending_advantage_, 0, "the cancelling pending value is consumed");
    }
}

void testBardicBonusAddedOnceUnderAdvantage()
{
    std::printf("rollAdvantage: Bardic bonus is added once, not per inner roll\n");

    // rollAdvantage captures the bonus before its two inner roll()s precisely so the
    // inner rolls can't each consume it. Two contexts on the same seed draw the same
    // two dice, so the only difference must be a single +5.
    CombatContext a = seeded();
    CombatContext b = seeded();
    a.pending_roll_bonus_ = 5;
    checkEq(rules::rollAdvantage(a, 20), rules::rollAdvantage(b, 20) + 5,
            "advantage adds the bardic bonus exactly once");

    CombatContext c = seeded();
    CombatContext d = seeded();
    c.pending_roll_bonus_ = 5;
    checkEq(rules::rollDisadvantage(c, 20), rules::rollDisadvantage(d, 20) + 5,
            "disadvantage adds the bardic bonus exactly once");
}

// ─────────────────────────────────────────────────────────────────────────────
//  Weapon modifiers — rules::attackModifier / damageAbilityMod
// ─────────────────────────────────────────────────────────────────────────────

rpg::Agent::Stats statBlock(int str, int dex, int cha = 10, int pb = 3)
{
    rpg::Agent::Stats s;
    s.str = str;
    s.dex = dex;
    s.cha = cha;
    s.prof_bonus = pb;
    return s;
}

void testAttackModifier()
{
    std::printf("attackModifier / damageAbilityMod\n");

    const rpg::Agent::Stats s = statBlock(/*str*/ 18, /*dex*/ 12, /*cha*/ 16);  // +4 / +1 / +3

    {   // Plain melee: STR, no proficiency.
        rpg::Weapon w;
        w.type = rpg::WeaponType::Melee;
        checkEq(rules::attackModifier(w, s), 4, "melee non-proficient uses STR");
        w.proficient = true;
        checkEq(rules::attackModifier(w, s), 7, "proficiency adds the bonus");
        checkEq(rules::damageAbilityMod(w, s), 4, "damage mod takes STR but never proficiency");
    }

    {   // Finesse takes the better of STR/DEX — here STR.
        rpg::Weapon w;
        w.type = rpg::WeaponType::Melee;
        w.finesse = true;
        checkEq(rules::attackModifier(w, s), 4, "finesse takes max(STR, DEX)");

        const rpg::Agent::Stats dexy = statBlock(/*str*/ 8, /*dex*/ 18);  // -1 / +4
        checkEq(rules::attackModifier(w, dexy), 4, "finesse takes DEX when DEX is higher");
    }

    {   // Ranged uses DEX; Archery is +2 but only for true Ranged weapons.
        rpg::Weapon bow;
        bow.type = rpg::WeaponType::Ranged;
        checkEq(rules::attackModifier(bow, s), 1, "ranged uses DEX");

        rpg::Agent::Stats archer = s;
        archer.feats.push_back("Archery");
        checkEq(rules::attackModifier(bow, archer), 3, "Archery adds +2 to a ranged weapon");

        rpg::Weapon javelin;                       // a Melee weapon with the Thrown property
        javelin.type = rpg::WeaponType::Melee;
        javelin.thrown = true;
        checkEq(rules::attackModifier(javelin, archer), 4,
                "Archery does NOT apply to a thrown melee weapon");
        checkEq(rules::attackModifier(javelin, s), 4, "a thrown melee weapon uses STR");
    }

    {   // Pact of the Blade: CHA option, "never worse".
        rpg::Weapon pact;
        pact.type = rpg::WeaponType::Melee;
        pact.pact_weapon = true;

        checkEq(rules::attackModifier(pact, s), 4, "pact weapon keeps STR when STR beats CHA");
        checkEq(rules::damageAbilityMod(pact, s), 4, "pact damage keeps STR when STR beats CHA");

        const rpg::Agent::Stats warlock = statBlock(/*str*/ 8, /*dex*/ 10, /*cha*/ 20);  // -1 / 0 / +5
        checkEq(rules::attackModifier(pact, warlock), 5, "pact weapon uses CHA when CHA is best");
        checkEq(rules::damageAbilityMod(pact, warlock), 5, "pact damage uses CHA when CHA is best");
    }
}

// ─────────────────────────────────────────────────────────────────────────────
//  Spell DCs — rules::spellAttackMod / spellSaveDc / spellSaveDcFromAbility
// ─────────────────────────────────────────────────────────────────────────────

void testSpellMods()
{
    std::printf("spellAttackMod / spellSaveDc / spellSaveDcFromAbility\n");

    rpg::Agent::Stats s;
    s.prof_bonus = 3;
    s.intel = 18;
    s.cha   = 14;
    s.wis   = 10;

    s.spellcasting_ability = 5;   // CHA
    checkEq(rules::spellAttackMod(s), 5, "spell attack mod uses CHA (+2) + PB (3)");
    checkEq(rules::spellSaveDc(s), 13, "spell save DC is 8 + spell attack mod");

    s.spellcasting_ability = 3;   // INT
    checkEq(rules::spellAttackMod(s), 7, "spell attack mod uses INT (+4) + PB (3)");
    checkEq(rules::spellSaveDc(s), 15, "spell save DC follows the casting ability");

    // Sorcerer Innate Sorcery: +1 DC while active, and it must not leak into the attack mod.
    s.innate_sorcery_turns = 2;
    checkEq(rules::spellSaveDc(s), 16, "Innate Sorcery adds +1 to the save DC");
    checkEq(rules::spellAttackMod(s), 7, "Innate Sorcery does not change the attack mod here");
    s.innate_sorcery_turns = 0;

    // spellSaveDcFromAbility names its own ability and ignores spellcasting_ability.
    checkEq(rules::spellSaveDcFromAbility(s, rpg::SaveWis), 11, "DC from WIS (10 → +0) is 8+3+0");
    checkEq(rules::spellSaveDcFromAbility(s, rpg::SaveInt), 15, "DC from INT (18 → +4) is 8+3+4");
    s.innate_sorcery_turns = 2;
    checkEq(rules::spellSaveDcFromAbility(s, rpg::SaveInt), 16,
            "Innate Sorcery also lifts an ability-named DC");
}

void testNegativeAbilityRounding()
{
    std::printf("spellAttackMod: negative modifiers round DOWN, not toward zero\n");

    // The one genuinely subtle line in the modifier code: C++ integer division
    // truncates toward zero, so (7-10)/2 == -1, but 5e wants -2. Both DC helpers
    // carry an explicit correction for odd sub-10 scores; this pins it.
    rpg::Agent::Stats s;
    s.prof_bonus = 2;
    s.spellcasting_ability = 5;

    s.cha = 7;
    checkEq(rules::spellAttackMod(s), 0, "CHA 7 is -2, not -1 (attack mod 2-2 == 0)");
    checkEq(rules::spellSaveDc(s), 8, "CHA 7 save DC is 8+2-2");

    s.cha = 8;
    checkEq(rules::spellAttackMod(s), 1, "CHA 8 is -1 (even score needs no correction)");

    s.cha = 9;
    checkEq(rules::spellAttackMod(s), 1, "CHA 9 is -1, not 0");

    s.cha = 11;
    checkEq(rules::spellAttackMod(s), 2, "CHA 11 is +0 (above 10, truncation is already correct)");

    s.wis = 7;
    checkEq(rules::spellSaveDcFromAbility(s, rpg::SaveWis), 8,
            "the ability-named DC applies the same rounding correction");
}

// ─────────────────────────────────────────────────────────────────────────────
//  CombatContext JSON round-trip (R3 landed it; R5 depends on it)
// ─────────────────────────────────────────────────────────────────────────────

void testContextRoundTrip()
{
    std::printf("CombatContext: to_json / from_json round-trip\n");

    CombatContext a = seeded(999u);
    for (int i = 0; i < 17; ++i) (void)rules::roll(a, 20);   // advance the generator

    a.pending_roll_bonus_        = 4;
    a.pending_damage_bonus_      = 6;
    a.pending_advantage_         = -1;
    a.force_max_damage_          = true;
    a.pending_portent_die_       = 11;
    a.resolving_sentinel_guard_  = true;
    a.turnCounter_               = 7;
    a.agent_portent_round_used_[3] = 2;
    a.agent_portent_round_used_[5] = 9;

    const CombatContext b = CombatContext::from_json(a.to_json());

    checkEq(b.pending_roll_bonus_, 4, "pending_roll_bonus_ round-trips");
    checkEq(b.pending_damage_bonus_, 6, "pending_damage_bonus_ round-trips");
    checkEq(b.pending_advantage_, -1, "pending_advantage_ round-trips");
    check(b.force_max_damage_, "force_max_damage_ round-trips");
    checkEq(b.pending_portent_die_, 11, "pending_portent_die_ round-trips");
    check(b.resolving_sentinel_guard_, "resolving_sentinel_guard_ round-trips");
    checkEq(b.turnCounter_, 7, "turnCounter_ round-trips");
    checkEq(static_cast<int>(b.agent_portent_round_used_.size()), 2,
            "agent_portent_round_used_ keeps both entries");
    checkEq(b.agent_portent_round_used_.at(3), 2, "portent round for agent 3 round-trips");
    checkEq(b.agent_portent_round_used_.at(5), 9, "portent round for agent 5 round-trips");

    // The point of serializing mt19937's STATE rather than the seed: a restored
    // context must CONTINUE the stream, not restart it. `reseeded` is what storing
    // the seed would have produced — it must diverge, or the distinction is untested.
    CombatContext live = seeded(4242u);
    for (int i = 0; i < 9; ++i) (void)rules::roll(live, 20);

    CombatContext restored = CombatContext::from_json(live.to_json());
    CombatContext reseeded = seeded(4242u);

    bool stream_continues   = true;
    bool seed_would_diverge = false;
    for (int i = 0; i < 25; ++i) {
        const int expect = rules::roll(live, 20);
        if (rules::roll(restored, 20) != expect) stream_continues = false;
        if (rules::roll(reseeded, 20) != expect) seed_would_diverge = true;
    }
    check(stream_continues, "a restored context continues the RNG stream exactly");
    check(seed_would_diverge,
          "restoring from the seed instead of the state would diverge (why to_json stores state)");
}

} // namespace

int main()
{
    std::printf("\n=== rules.hpp unit tests (no CombatEngine, no BattleMap) ===\n\n");

    testRollBounds();
    testRollModifier();
    testPendingRollBonus();
    testPortentDie();
    testPendingAdvantageIsD20Only();
    testAdvantageDisadvantageDistribution();
    testAdvantageCancellation();
    testBardicBonusAddedOnceUnderAdvantage();
    testAttackModifier();
    testSpellMods();
    testNegativeAbilityRounding();
    testContextRoundTrip();

    std::printf("\n");
    if (g_failures == 0) {
        std::printf("✓ All %d checks passed\n\n", g_checks);
        return 0;
    }
    std::printf("✗ %d of %d checks FAILED\n\n", g_failures, g_checks);
    return 1;
}
