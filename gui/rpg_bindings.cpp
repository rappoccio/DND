// ─────────────────────────────────────────────────────────────────────────────
//  rpg_bindings.cpp  –  pybind11 module: exposes C++ RPG types to Python
//
//  Import from Python:
//      import rpg_battle_map as rpg
//
//      bm = rpg.BattleMap("map.png")
//      bm.analyze_grid()
//      bm.detect_walls()
//
//      for w in bm.walls:
//          print(w.a.col, w.a.row, "->", w.b.col, w.b.row)
//
//      cfg = rpg.AgentConfig()
//      cfg.name = "Goblin"; cfg.sprite_path = "goblin.png"
//      cfg.size = 1; cfg.start_col = 2; cfg.start_row = 3
//      bm.add_agent_config(cfg)
//      bm.apply_agent_configs()
// ─────────────────────────────────────────────────────────────────────────────

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>        // std::vector, std::unordered_set → Python list/set
#include <pybind11/operators.h>

#include "battle_map.hpp"
#include "combat.hpp"
#include "map_configs.hpp"
#include "character_class.hpp"

namespace py = pybind11;
using namespace rpg;

// Helper: convert CellSet → Python list (pybind11 can't auto-convert custom hash sets)
static std::vector<Cell> cellSetToVec(const CellSet& s) {
    return {s.begin(), s.end()};
}

PYBIND11_MODULE(rpg_battle_map, m)
{
    m.doc() = "RPG Battle Map – C++ analysis core (grid detection, wall detection, agents)";

    // ── Cell ────────────────────────────────────────────────────────────────
    py::class_<Cell>(m, "Cell")
        .def(py::init<>())
        .def(py::init<int, int>(), py::arg("col"), py::arg("row"))
        .def_readwrite("col", &Cell::col)
        .def_readwrite("row", &Cell::row)
        .def("__eq__",   &Cell::operator==)
        .def("__repr__", [](const Cell& c){
            return "<Cell col=" + std::to_string(c.col)
                 + " row=" + std::to_string(c.row) + ">"; });

    // ── Wall ────────────────────────────────────────────────────────────────
    py::class_<Wall>(m, "Wall")
        .def(py::init<>())
        .def_readwrite("a", &Wall::a)
        .def_readwrite("b", &Wall::b)
        .def("__repr__", [](const Wall& w){
            return "<Wall ("
                 + std::to_string(w.a.col) + "," + std::to_string(w.a.row)
                 + ")->("
                 + std::to_string(w.b.col) + "," + std::to_string(w.b.row) + ")>"; });

    // ── AgentConfig ─────────────────────────────────────────────────────────
    py::class_<AgentConfig>(m, "AgentConfig")
        .def(py::init<>())
        .def_readwrite("name",       &AgentConfig::name)
        .def_property("sprite_path",
            [](const AgentConfig& t){ return t.spritePath.string(); },
            [](AgentConfig& t, const std::string& s){ t.spritePath = s; })
        .def_readwrite("size",       &AgentConfig::size)
        .def_readwrite("start_col",  &AgentConfig::startCol)
        .def_readwrite("start_row",  &AgentConfig::startRow)
        .def("__repr__", [](const AgentConfig& t){
            return "<AgentConfig name='" + t.name
                 + "' size=" + std::to_string(t.size)
                 + " at (" + std::to_string(t.startCol)
                 + "," + std::to_string(t.startRow) + ")>"; });

    // ── PlacedAgent (read-only view) ────────────────────────────────────────
    py::class_<PlacedAgent>(m, "PlacedAgent")
        .def_property_readonly("origin",      [](const PlacedAgent& p){ return p.origin; })
        .def_property_readonly("name",        [](const PlacedAgent& p){ return std::string(p.agent->name()); })
        .def_property_readonly("size",        [](const PlacedAgent& p){ return p.agent->getSize(); })
        .def_property_readonly("sprite_path", [](const PlacedAgent& p){ return p.agent->getSprite().string(); })
        .def_property_readonly("x",           [](const PlacedAgent& p){ return p.agent->getX(); })
        .def_property_readonly("y",           [](const PlacedAgent& p){ return p.agent->getY(); })
        // Delegate actions back to C++
        .def("turn",       [](PlacedAgent& p){ p.agent->turn(); })
        .def("action",     [](PlacedAgent& p){ p.agent->action(); })
        .def("attack",     [](PlacedAgent& p){ p.agent->attack(); })
        .def("dash",       [](PlacedAgent& p){ p.agent->dash(); })
        .def("disengage",  [](PlacedAgent& p){ p.agent->disengage(); })
        .def("dodge",      [](PlacedAgent& p){ p.agent->dodge(); })
        .def("hide",       [](PlacedAgent& p){ p.agent->hide(); })
        .def("bonus_action",[](PlacedAgent& p){ p.agent->bonusAction(); })
        .def("walk",       [](PlacedAgent& p){ p.agent->walk(); })
        .def("fly",        [](PlacedAgent& p){ p.agent->fly();  })
        .def("reaction",   [](PlacedAgent& p){ p.agent->reaction(); })
        .def_property_readonly("conditions",
            [](const PlacedAgent& p) -> const Agent::Conditions& { return p.agent->getConditions(); },
            py::return_value_policy::reference_internal)
        // Movement budget
        .def("init_movement",
            [](PlacedAgent& p, int walk, int fly, int swim, int burrow){
                p.agent->initMovement(walk, fly, swim, burrow); },
            py::arg("walk_ft"), py::arg("fly_ft") = 0,
            py::arg("swim_ft") = 0, py::arg("burrow_ft") = 0)
        .def_property_readonly("walk_remaining",
            [](const PlacedAgent& p){ return p.agent->getWalkRemaining(); })
        .def_property_readonly("fly_remaining",
            [](const PlacedAgent& p){ return p.agent->getFlyRemaining(); })
        .def_property_readonly("swim_remaining",
            [](const PlacedAgent& p){ return p.agent->getSwimRemaining(); })
        .def_property_readonly("burrow_remaining",
            [](const PlacedAgent& p){ return p.agent->getBurrowRemaining(); })
        .def("walk_to",   [](PlacedAgent& p, int x, int y, int z){ return p.agent->walkTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def("fly_to",    [](PlacedAgent& p, int x, int y, int z){ return p.agent->flyTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def("swim_to",   [](PlacedAgent& p, int x, int y, int z){ return p.agent->swimTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def("burrow_to", [](PlacedAgent& p, int x, int y, int z){ return p.agent->burrowTo(x, y, z); },
            py::arg("x"), py::arg("y"), py::arg("z") = 0)
        .def_property_readonly("weapons",
            [](const PlacedAgent& p) -> std::vector<Weapon> { return p.weapons; })
        .def_property_readonly("spells",
            [](const PlacedAgent& p) -> std::vector<Spell> { return p.spells; })
        .def_property_readonly("stats",
            [](PlacedAgent& p) -> Agent::Stats& { return p.stats; },
            py::return_value_policy::reference_internal)
        .def("set_advantage", [](PlacedAgent& p, bool adv){ p.agent->setAdvantage(adv); },
             py::arg("advantage"), "Set whether the agent has advantage on rolls.")
        .def("has_advantage", [](const PlacedAgent& p){ return p.agent->hasAdvantage(); },
             "Get whether the agent has advantage on rolls.")
        .def("set_disadvantage", [](PlacedAgent& p, bool dis){ p.agent->setDisadvantage(dis); },
             py::arg("disadvantage"), "Set whether the agent has disadvantage on rolls.")
        .def("has_disadvantage", [](const PlacedAgent& p){ return p.agent->hasDisadvantage(); },
             "Get whether the agent has disadvantage on rolls.")
        .def("__repr__", [](const PlacedAgent& p){
            return "<PlacedAgent '" + std::string(p.agent->name())
                 + "' size=" + std::to_string(p.agent->getSize())
                 + " at (" + std::to_string(p.origin.col)
                 + "," + std::to_string(p.origin.row) + ")>"; });

    // ── Stats (nested inside Agent) ──────────────────────────────────────────
    py::class_<Agent::Stats>(m, "Stats")
        .def(py::init<>())
        .def_static("from_json_string", &Agent::Stats::fromJsonString,
                    py::arg("json_str"),
                    "Create Stats from a JSON string (e.g., from DND2024_MonsterStats.json).")
        // Ability scores
        .def_readwrite("str",        &Agent::Stats::str)
        .def_readwrite("dex",        &Agent::Stats::dex)
        .def_readwrite("con",        &Agent::Stats::con)
        .def_readwrite("intel",      &Agent::Stats::intel)
        .def_readwrite("wis",        &Agent::Stats::wis)
        .def_readwrite("cha",        &Agent::Stats::cha)
        // Combat
        .def_readwrite("hp_max",          &Agent::Stats::hp_max)
        .def_readwrite("hp_cur",          &Agent::Stats::hp_cur)
        .def_readwrite("ac",              &Agent::Stats::ac)
        .def_readwrite("speed_walk",   &Agent::Stats::speed_walk)
        .def_readwrite("speed_swim",   &Agent::Stats::speed_swim)
        .def_readwrite("speed_fly",    &Agent::Stats::speed_fly)
        .def_readwrite("speed_burrow", &Agent::Stats::speed_burrow)
        .def_readwrite("prof_bonus",      &Agent::Stats::prof_bonus)
        // Saving throw proficiency flags (one per ability)
        .def_readwrite("save_prof_str",   &Agent::Stats::save_prof_str)
        .def_readwrite("save_prof_dex",   &Agent::Stats::save_prof_dex)
        .def_readwrite("save_prof_con",   &Agent::Stats::save_prof_con)
        .def_readwrite("save_prof_intel", &Agent::Stats::save_prof_intel)
        .def_readwrite("save_prof_wis",   &Agent::Stats::save_prof_wis)
        .def_readwrite("save_prof_cha",   &Agent::Stats::save_prof_cha)
        // Class-feature capability flags
        .def_readwrite("num_attacks",          &Agent::Stats::num_attacks)
        .def_readwrite("has_cunning_action",   &Agent::Stats::has_cunning_action)
        .def_readwrite("has_offhand_attack",   &Agent::Stats::has_offhand_attack)
        .def_readwrite("can_cast_spell",       &Agent::Stats::can_cast_spell)
        .def_readwrite("spellcasting_ability", &Agent::Stats::spellcasting_ability)
        // Initiative
        .def_readwrite("initiative_prof", &Agent::Stats::initiative_prof)
        .def_property_readonly("initiative_modifier", &Agent::Stats::initiativeModifier)
        // Character Class & Spell Slots
        .def_readwrite("character_class",       &Agent::Stats::character_class)
        .def_readwrite("char_level",            &Agent::Stats::char_level)
        .def_readwrite("spell_slots_max",       &Agent::Stats::spell_slots_max)
        .def_readwrite("spell_slots_remaining", &Agent::Stats::spell_slots_remaining)
        .def("set_class_level", &Agent::Stats::set_class_level,
             py::arg("cls"), py::arg("level"),
             "Set the character class and level. Automatically computes spell_slots_max and updates can_cast_spell.")
        .def("restore_spell_slots", &Agent::Stats::restore_spell_slots,
             "Restore spell_slots_remaining to their maximum (Long Rest).")
        // Spell Save DCs (computed read-only: 8 + mod [+ prof_bonus if proficient])
        .def_property_readonly("spell_save_dc_str",   &Agent::Stats::spellSaveDcStr)
        .def_property_readonly("spell_save_dc_dex",   &Agent::Stats::spellSaveDcDex)
        .def_property_readonly("spell_save_dc_con",   &Agent::Stats::spellSaveDcCon)
        .def_property_readonly("spell_save_dc_intel", &Agent::Stats::spellSaveDcIntel)
        .def_property_readonly("spell_save_dc_wis",   &Agent::Stats::spellSaveDcWis)
        .def_property_readonly("spell_save_dc_cha",   &Agent::Stats::spellSaveDcCha)
        .def("__repr__", [](const Agent::Stats& s){
            return "<Stats STR=" + std::to_string(s.str)
                 + " DEX=" + std::to_string(s.dex)
                 + " CON=" + std::to_string(s.con)
                 + " INT=" + std::to_string(s.intel)
                 + " WIS=" + std::to_string(s.wis)
                 + " CHA=" + std::to_string(s.cha)
                 + " HP=" + std::to_string(s.hp_cur) + "/" + std::to_string(s.hp_max)
                 + " AC=" + std::to_string(s.ac) + ">"; });

    // ── Conditions (nested inside Agent) ────────────────────────────────────
    py::class_<Agent::Conditions>(m, "Conditions")
        .def(py::init<>())
        .def_readwrite("dashing",       &Agent::Conditions::dashing)
        .def_readwrite("dodging",       &Agent::Conditions::dodging)
        .def_readwrite("disengaging",   &Agent::Conditions::disengaging)
        .def_readwrite("reaction_used", &Agent::Conditions::reaction_used)
        .def_readwrite("hidden",        &Agent::Conditions::hidden)
        .def_readwrite("invisible",     &Agent::Conditions::invisible)
        .def_readwrite("incapacitated", &Agent::Conditions::incapacitated)
        .def_readwrite("concentrating",    &Agent::Conditions::concentrating)
        .def_readwrite("concentrating_on", &Agent::Conditions::concentrating_on)
        .def_readwrite("has_advantage",   &Agent::Conditions::has_advantage)
        .def_readwrite("has_disadvantage", &Agent::Conditions::has_disadvantage)
        .def("__repr__", [](const Agent::Conditions& c){
            std::string s = "<Conditions";
            if (c.dashing)       s += " dashing";
            if (c.dodging)       s += " dodging";
            if (c.disengaging)   s += " disengaging";
            if (c.hidden)        s += " hidden";
            if (c.invisible)     s += " invisible";
            if (c.incapacitated) s += " incapacitated";
            return s + ">"; });

    // ── Damage type enums ─────────────────────────────────────────────────────
    py::enum_<MagicDamage_t>(m, "MagicDamage")
        .value("Acid",      MagicDamage_t::Acid)
        .value("Cold",      MagicDamage_t::Cold)
        .value("Fire",      MagicDamage_t::Fire)
        .value("Force",     MagicDamage_t::Force)
        .value("Lightning", MagicDamage_t::Lightning)
        .value("Necrotic",  MagicDamage_t::Necrotic)
        .value("Poison",    MagicDamage_t::Poison)
        .value("Psychic",   MagicDamage_t::Psychic)
        .value("Radiant",   MagicDamage_t::Radiant)
        .value("Thunder",   MagicDamage_t::Thunder);

    py::enum_<PhysicalDamage_t>(m, "PhysicalDamage")
        .value("Bludgeoning", PhysicalDamage_t::Bludgeoning)
        .value("Piercing",    PhysicalDamage_t::Piercing)
        .value("Slashing",    PhysicalDamage_t::Slashing);

    // ── WeaponType ────────────────────────────────────────────────────────────
    py::enum_<WeaponType>(m, "WeaponType")
        .value("Melee",  WeaponType::Melee,  "Close-quarters weapon.")
        .value("Ranged", WeaponType::Ranged, "Projectile weapon.")
        .export_values();

    // ── Weapon ────────────────────────────────────────────────────────────────
    py::class_<Weapon>(m, "Weapon")
        .def(py::init<>())
        .def_readwrite("name",             &Weapon::name)
        .def_readwrite("type",             &Weapon::type)
        .def_readwrite("reach_ft",         &Weapon::reach_ft)
        .def_readwrite("normal_range_ft",  &Weapon::normal_range_ft)
        .def_readwrite("long_range_ft",    &Weapon::long_range_ft)
        .def_readwrite("finesse",          &Weapon::finesse)
        .def_readwrite("thrown",           &Weapon::thrown)
        .def_readwrite("proficient",       &Weapon::proficient)
        .def_readwrite("off_hand",         &Weapon::off_hand)
        .def_readwrite("physical_damage_types", &Weapon::physicalDamageRolls)
        .def_readwrite("magic_damage_types",    &Weapon::magicDamageRolls)
        .def_readwrite("bonus_hit",        &Weapon::bonus_hit)
        .def_readwrite("bonus_damage",     &Weapon::bonus_damage)
        .def("__repr__", [](const Weapon& w){
            std::string dmg_str;
            if (!w.physicalDamageRolls.empty()) {
                dmg_str = std::to_string(w.physicalDamageRolls[0].num_dice) +
                         "d" + std::to_string(w.physicalDamageRolls[0].die_size);
            } else if (!w.magicDamageRolls.empty()) {
                dmg_str = std::to_string(w.magicDamageRolls[0].num_dice) +
                         "d" + std::to_string(w.magicDamageRolls[0].die_size);
            } else {
                dmg_str = "0d0";
            }
            return "<Weapon '" + w.name + "' "
                 + (w.type == WeaponType::Melee ? "Melee" : "Ranged")
                 + " " + dmg_str + ">"; });

    // ── Spell enums ──────────────────────────────────────────────────────────
    py::enum_<Spell::Geometry_t>(m, "SpellGeometry")
        .value("Single", Spell::Single)
        .value("Line",   Spell::Line)
        .value("Cone",   Spell::Cone)
        .value("Sphere", Spell::Sphere)
        .export_values();

    py::enum_<Spell::SpellType_t>(m, "SpellType")
        .value("Harm", Spell::Harm)
        .value("Heal", Spell::Heal)
        .export_values();

    py::enum_<Spell::SpellAttack_t>(m, "SpellAttack")
        .value("AttackRoll", Spell::AttackRoll)
        .value("Save",       Spell::Save)
        .value("Automatic",  Spell::Automatic)
        .export_values();

    py::enum_<Spell::SaveAbility_t>(m, "SaveAbility")
        .value("SaveStr", Spell::SaveStr)
        .value("SaveDex", Spell::SaveDex)
        .value("SaveCon", Spell::SaveCon)
        .value("SaveInt", Spell::SaveInt)
        .value("SaveWis", Spell::SaveWis)
        .value("SaveCha", Spell::SaveCha)
        .export_values();

    // ── Character Class & Caster Type ─────────────────────────────────────────
    py::enum_<CharacterClass>(m, "CharacterClass")
        .value("None",      CharacterClass::CharClassNone)
        .value("Barbarian", CharacterClass::Barbarian)
        .value("Fighter",   CharacterClass::Fighter)
        .value("Monk",      CharacterClass::Monk)
        .value("Rogue",     CharacterClass::Rogue)
        .value("Bard",      CharacterClass::Bard)
        .value("Cleric",    CharacterClass::Cleric)
        .value("Druid",     CharacterClass::Druid)
        .value("Sorcerer",  CharacterClass::Sorcerer)
        .value("Wizard",    CharacterClass::Wizard)
        .value("Paladin",   CharacterClass::Paladin)
        .value("Ranger",    CharacterClass::Ranger)
        .value("Warlock",   CharacterClass::Warlock)
        .export_values();

    py::enum_<CasterType>(m, "CasterType")
        .value("None", CasterType::CasterNone)
        .value("Full", CasterType::CasterFull)
        .value("Half", CasterType::CasterHalf)
        .value("Pact", CasterType::CasterPact)
        .export_values();

    // Free functions for class/spell slot logic
    m.def("compute_class_slots", &rpg::compute_class_slots,
          py::arg("character_class"), py::arg("level"),
          "Compute spell slots for a character class at a given level. Returns array of 9 ints (one per spell level).");
    m.def("get_caster_type", &rpg::get_caster_type,
          py::arg("character_class"),
          "Get the caster type (None/Full/Half/Pact) for a character class.");

    // ── MagicDamageRoll ───────────────────────────────────────────────────────
    py::class_<MagicDamageRoll>(m, "MagicDamageRoll")
        .def(py::init<>())
        .def_readwrite("type", &MagicDamageRoll::type)
        .def_readwrite("num_dice", &MagicDamageRoll::num_dice)
        .def_readwrite("die_size", &MagicDamageRoll::die_size);

    // ── PhysicalDamageRoll ────────────────────────────────────────────────────
    py::class_<PhysicalDamageRoll>(m, "PhysicalDamageRoll")
        .def(py::init<>())
        .def_readwrite("type", &PhysicalDamageRoll::type)
        .def_readwrite("num_dice", &PhysicalDamageRoll::num_dice)
        .def_readwrite("die_size", &PhysicalDamageRoll::die_size);

    // ── Spell ─────────────────────────────────────────────────────────────────
    py::class_<Spell>(m, "Spell")
        .def(py::init<>())
        .def_readwrite("name",                 &Spell::name)
        .def_readwrite("type",                 &Spell::type)
        .def_readwrite("geometry",             &Spell::geometry)
        .def_readwrite("attack_type",          &Spell::attack_type)
        .def_readwrite("save_ability",         &Spell::save_ability)
        .def_readwrite("range",                &Spell::range)
        .def_readwrite("radius",               &Spell::radius)
        .def_readwrite("width",                &Spell::width)
        .def_readwrite("length",               &Spell::length)
        .def_readwrite("duration",             &Spell::duration)
        .def_readwrite("magic_damage_rolls",   &Spell::magic_damage_rolls)
        .def_readwrite("physical_damage_rolls",&Spell::physical_damage_rolls)
        .def_readwrite("terrain_difficulty",   &Spell::terrain_difficulty,
             "Terrain difficulty applied by this spell (Normal = no terrain effect).\n"
             "The duration is the same as spell.duration (in rounds).")
        .def_readwrite("requires_concentration", &Spell::requires_concentration,
             "If true, caster must maintain concentration; breaks on damage (CON save).")
        .def_readwrite("requires_los", &Spell::requires_los,
             "If true, spell requires line of sight to the target or area origin.")
        .def_readwrite("check_los_on_center", &Spell::check_los_on_center,
             "If true, only the spell center needs line of sight (not all affected cells). User configurable.")
        .def_readwrite("level", &Spell::level,
             "Spell level: 0 = cantrip (unlimited casts); 1-9 = requires a spell slot of that level.")
        .def_readwrite("upcast_dice_bonus", &Spell::upcast_dice_bonus,
             "Extra dice added to damage when cast at a higher slot level. Calculated as upcast_dice_bonus * (slot_level - spell_level).")
        .def("__repr__", [](const Spell& s){
            return "<Spell '" + s.name + "'>"; });

    // ── SpellAction ───────────────────────────────────────────────────────────
    py::class_<SpellAction>(m, "SpellAction")
        .def(py::init<>())
        .def_readwrite("caster_idx",     &SpellAction::caster_idx)
        .def_readwrite("spell_idx",      &SpellAction::spell_idx)
        .def_readwrite("target_indices", &SpellAction::target_indices)
        .def_readwrite("aoe_col",        &SpellAction::aoe_col)
        .def_readwrite("aoe_row",        &SpellAction::aoe_row)
        .def("__repr__", [](const SpellAction& a){
            return "<SpellAction caster=" + std::to_string(a.caster_idx)
                 + " spell=" + std::to_string(a.spell_idx)
                 + " targets=" + std::to_string(a.target_indices.size()) + ">"; });

    // ── SpellTargetResult ─────────────────────────────────────────────────────
    py::class_<SpellTargetResult>(m, "SpellTargetResult")
        .def(py::init<>())
        .def_readonly("target_idx",    &SpellTargetResult::target_idx)
        .def_readonly("saved",         &SpellTargetResult::saved)
        .def_readonly("hit",           &SpellTargetResult::hit)
        .def_readonly("d20",           &SpellTargetResult::d20)
        .def_readonly("attack_mod",    &SpellTargetResult::attack_mod)
        .def_readonly("total_roll",    &SpellTargetResult::total_roll)
        .def_readonly("target_ac",     &SpellTargetResult::target_ac)
        .def_readonly("critical",      &SpellTargetResult::critical)
        .def_readonly("dice_results",  &SpellTargetResult::dice_results)
        .def_readonly("damage_mod",    &SpellTargetResult::damage_mod)
        .def_readonly("total_damage",  &SpellTargetResult::total_damage)
        .def_readonly("total_healing", &SpellTargetResult::total_healing)
        .def_readonly("hp_before",     &SpellTargetResult::hp_before)
        .def_readonly("hp_after",      &SpellTargetResult::hp_after)
        .def_readonly("target_down",   &SpellTargetResult::target_down)
        .def_readonly("save_d20",      &SpellTargetResult::save_d20)
        .def_readonly("save_dc",       &SpellTargetResult::save_dc)
        .def("__repr__", [](const SpellTargetResult& r){
            return "<SpellTargetResult tgt=" + std::to_string(r.target_idx)
                 + (r.hit ? " HIT" : " MISS")
                 + " dmg=" + std::to_string(r.total_damage)
                 + " heal=" + std::to_string(r.total_healing) + ">"; });

    // ── SpellResult ───────────────────────────────────────────────────────────
    py::class_<SpellResult>(m, "SpellResult")
        .def(py::init<>())
        .def_readonly("valid",                      &SpellResult::valid)
        .def_readonly("spell_idx",                  &SpellResult::spell_idx)
        .def_readonly("spell_name",                 &SpellResult::spell_name)
        .def_readonly("attack_type",                &SpellResult::attack_type)
        .def_readonly("target_results",             &SpellResult::target_results)
        .def_readonly("concentration_replaced",     &SpellResult::concentration_replaced)
        .def_readonly("prev_concentration_spell",   &SpellResult::prev_concentration_spell)
        .def("__repr__", [](const SpellResult& r){
            if (!r.valid) return std::string("<SpellResult invalid>");
            return "<SpellResult '" + r.spell_name + "' "
                 + std::to_string(r.target_results.size()) + " target(s)>"; });

    // ── ActiveEffect ──────────────────────────────────────────────────────────
    py::class_<ActiveEffect>(m, "ActiveEffect")
        .def(py::init<>())
        .def_readwrite("caster_idx",      &ActiveEffect::caster_idx)
        .def_readwrite("target_idx",      &ActiveEffect::target_idx)
        .def_readwrite("spell",           &ActiveEffect::spell)
        .def_readwrite("turns_remaining", &ActiveEffect::turns_remaining)
        .def("__repr__", [](const ActiveEffect& e){
            return "<ActiveEffect '" + e.spell.name
                 + "' caster=" + std::to_string(e.caster_idx)
                 + " tgt=" + std::to_string(e.target_idx)
                 + " turns=" + std::to_string(e.turns_remaining) + ">"; });

    // ── ConcentrationSaveResult ───────────────────────────────────────────────
    py::class_<ConcentrationSaveResult>(m, "ConcentrationSaveResult")
        .def(py::init<>())
        .def_readonly("checked",            &ConcentrationSaveResult::checked)
        .def_readonly("save_d20",           &ConcentrationSaveResult::save_d20)
        .def_readonly("save_dc",            &ConcentrationSaveResult::save_dc)
        .def_readonly("con_mod",            &ConcentrationSaveResult::con_mod)
        .def_readonly("passed",             &ConcentrationSaveResult::passed)
        .def_readonly("concentration_lost", &ConcentrationSaveResult::concentration_lost)
        .def_readonly("spell_name",         &ConcentrationSaveResult::spell_name);

    // ── AttackResult ─────────────────────────────────────────────────────────
    py::class_<AttackResult>(m, "AttackResult")
        .def(py::init<>())
        .def_readonly("valid",        &AttackResult::valid)
        .def_readonly("d20",          &AttackResult::d20)
        .def_readonly("attack_mod",   &AttackResult::attack_mod)
        .def_readonly("total_roll",   &AttackResult::total_roll)
        .def_readonly("target_ac",    &AttackResult::target_ac)
        .def_readonly("critical",     &AttackResult::critical)
        .def_readonly("fumble",       &AttackResult::fumble)
        .def_readonly("disadvantage", &AttackResult::disadvantage)
        .def_readonly("hit",          &AttackResult::hit)
        .def_readonly("dice_results",          &AttackResult::dice_results)
        .def_readonly("damage_mod",            &AttackResult::damage_mod)
        .def_readonly("total_damage",          &AttackResult::total_damage)
        .def_readonly("physical_damage_types", &AttackResult::physical_damage_types)
        .def_readonly("magic_damage_types",    &AttackResult::magic_damage_types)
        .def_readonly("hp_before",             &AttackResult::hp_before)
        .def_readonly("hp_after",     &AttackResult::hp_after)
        .def_readonly("target_down",  &AttackResult::target_down)
        .def("__repr__", [](const AttackResult& r){
            if (!r.valid) return std::string("<AttackResult invalid>");
            std::string s = "<AttackResult d20=" + std::to_string(r.d20)
                          + " mod=" + std::to_string(r.attack_mod)
                          + " vs AC=" + std::to_string(r.target_ac)
                          + (r.hit ? " HIT dmg=" + std::to_string(r.total_damage)
                                   : " MISS")
                          + ">";
            return s; });

    // ── InitiativeEntry ───────────────────────────────────────────────────────
    py::class_<InitiativeEntry>(m, "InitiativeEntry")
        .def(py::init<>())
        .def_readonly("agent_idx", &InitiativeEntry::agent_idx)
        .def_readonly("d20",       &InitiativeEntry::d20)
        .def_readonly("modifier",  &InitiativeEntry::modifier)
        .def_readonly("total",     &InitiativeEntry::total)
        .def("__repr__", [](const InitiativeEntry& e){
            return "<InitiativeEntry agent=" + std::to_string(e.agent_idx)
                 + " d20=" + std::to_string(e.d20)
                 + " mod=" + std::to_string(e.modifier)
                 + " total=" + std::to_string(e.total) + ">"; });

    // ── Attack ──────────────────────────────────────────────────────────
    py::class_<Attack>(m, "Attack")
        .def(py::init<>())
        .def(py::init<int,int,int>(),
             py::arg("attacker_idx"), py::arg("target_idx"),
             py::arg("weapon_idx") = 0)
        .def_readwrite("attacker_idx", &Attack::attacker_idx)
        .def_readwrite("target_idx",   &Attack::target_idx)
        .def_readwrite("weapon_idx",   &Attack::weapon_idx)
        .def_readwrite("is_offhand",   &Attack::is_offhand)
        .def("__repr__", [](const Attack& a){
            std::string s = "<Attack atk=" + std::to_string(a.attacker_idx)
                 + " tgt=" + std::to_string(a.target_idx)
                 + " wpn=" + std::to_string(a.weapon_idx);
            if (a.is_offhand) s += " offhand";
            return s + ">"; });

    // ── TurnActions ───────────────────────────────────────────────────────────
    py::class_<TurnActions>(m, "TurnActions")
        .def(py::init<>())
        .def(py::init([](int agent_idx,
                         std::vector<Attack>      attacks,
                         std::vector<Attack>      bonus_attacks,
                         std::vector<SpellAction> spell_actions,
                         std::vector<SpellAction> bonus_spells) {
            TurnActions t;
            t.agent_idx     = agent_idx;
            t.attacks       = std::move(attacks);
            t.bonus_attacks = std::move(bonus_attacks);
            t.spell_actions = std::move(spell_actions);
            t.bonus_spells  = std::move(bonus_spells);
            return t;
        }),
        py::arg("agent_idx"),
        py::arg("attacks")       = std::vector<Attack>{},
        py::arg("bonus_attacks") = std::vector<Attack>{},
        py::arg("spell_actions") = std::vector<SpellAction>{},
        py::arg("bonus_spells")  = std::vector<SpellAction>{})
        .def_readwrite("agent_idx",     &TurnActions::agent_idx)
        .def_readwrite("attacks",       &TurnActions::attacks)
        .def_readwrite("bonus_attacks", &TurnActions::bonus_attacks)
        .def_readwrite("spell_actions", &TurnActions::spell_actions)
        .def_readwrite("bonus_spells",  &TurnActions::bonus_spells)
        .def("__repr__", [](const TurnActions& t){
            std::string s = "<TurnActions agent=" + std::to_string(t.agent_idx);
            if (!t.attacks.empty())
                s += " attacks=" + std::to_string(t.attacks.size());
            if (!t.bonus_attacks.empty())
                s += " bonus_attacks=" + std::to_string(t.bonus_attacks.size());
            if (!t.spell_actions.empty())
                s += " spell_actions=" + std::to_string(t.spell_actions.size());
            if (!t.bonus_spells.empty())
                s += " bonus_spells=" + std::to_string(t.bonus_spells.size());
            return s + ">"; });

    // ── MessageLogger ──────────────────────────────────────────────────────────
    py::class_<MessageLogger>(m, "MessageLogger")
        .def(py::init<>())
        .def("log", &MessageLogger::log, py::arg("message"),
             "Log a single message.")
        .def("flush", &MessageLogger::flush,
             "Return all buffered messages and clear the buffer.")
        .def("set_file", &MessageLogger::setFile, py::arg("path"),
             "Optional: open a log file for debug output.");

    // ── CombatEngine ──────────────────────────────────────────────────────────
    py::class_<CombatEngine>(m, "CombatEngine")
        .def(py::init<uint32_t>(), py::arg("seed") = 0,
             "Construct with a fixed seed (0 = random).")

        // Static / deterministic helpers
        .def_static("attack_modifier",
                    &CombatEngine::attackModifier,
                    py::arg("weapon"), py::arg("stats"),
                    "Total attack-roll modifier for weapon + attacker stats.")
        .def_static("damage_ability_mod",
                    &CombatEngine::damageAbilityMod,
                    py::arg("weapon"), py::arg("stats"),
                    "Ability modifier added to damage rolls.")
        .def_static("can_attack",
                    &CombatEngine::canAttack,
                    py::arg("weapon"), py::arg("battle_map"),
                    py::arg("atk_origin"), py::arg("atk_size"),
                    py::arg("tgt_origin"), py::arg("tgt_size"),
                    "True iff weapon can reach target with LoS.")
        .def_static("has_disadvantage",
                    &CombatEngine::hasDisadvantage,
                    py::arg("weapon"), py::arg("battle_map"),
                    py::arg("atk_origin"), py::arg("atk_size"),
                    py::arg("tgt_origin"), py::arg("tgt_size"),
                    "True iff the attack should be rolled at disadvantage.")
        .def_static("damage_agent",
                    &CombatEngine::damageAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Reduce hp_cur of agent[idx] by amount (clamped to 0). "
                    "Returns new hp_cur.")
        .def_static("heal_agent",
                    &CombatEngine::healAgent,
                    py::arg("battle_map"), py::arg("idx"), py::arg("amount"),
                    "Raise hp_cur of agent[idx] by amount (clamped to hp_max). "
                    "Returns new hp_cur.")

        // Dice rollers
        .def("roll",              &CombatEngine::roll,            py::arg("sides"))
        .def("roll_advantage",    &CombatEngine::rollAdvantage,   py::arg("sides"))
        .def("roll_disadvantage", &CombatEngine::rollDisadvantage,py::arg("sides"))

        // Core mechanics
        .def("roll_to_hit",
             &CombatEngine::rollToHit,
             py::arg("weapon"), py::arg("attacker_stats"),
             py::arg("target_ac"), py::arg("advantage") = false,
             py::arg("disadvantage") = false,
             "Roll d20 + modifier vs AC.  Does not apply damage.")
        .def("resolve_attack",
             &CombatEngine::resolveAttack,
             py::arg("weapon"), py::arg("attacker_stats"),
             py::arg("target_stats"), py::arg("advantage") = false,
             py::arg("disadvantage") = false,
             "Roll to hit, roll damage, apply to target_stats in place.")

        // High-level
        // Initiative
        .def("roll_initiative",
             &CombatEngine::rollInitiative,
             py::arg("battle_map"),
             "Roll d20 + DEX mod [+ prof_bonus if initiative_prof] for every\n"
             "living agent.  Returns a list of InitiativeEntry sorted highest\n"
             "first.  Call once at combat start; reuse the order each round.")

        .def("execute_action",
             &CombatEngine::executeAction,
             py::arg("battle_map"), py::arg("action"),
             "Validate + execute an Attack; writes HP change to BattleMap.")
        .def("threatening_agents",
             &CombatEngine::threateningAgents,
             py::arg("battle_map"), py::arg("target_idx"), py::arg("reach_cells") = 1,
             "Indices of non-incapacitated agents within reach_cells of target's footprint.")
        .def("available_attacks",
             &CombatEngine::availableAttacks,
             py::arg("battle_map"), py::arg("attacker_idx"),
             "Return all legal (weapon, target) pairs for the attacker.")
        .def("get_battle_observation",
             &CombatEngine::getBattleObservation,
             py::arg("battle_map"), py::arg("attacker_idx"),
             py::arg("target_indices"), py::arg("max_targets") = 8,
             "Fixed-length float vector for NN input (12 + max_targets×14 floats).")

        // Per-agent turn counts
        .def("get_agent_turns",
             &CombatEngine::getAgentTurns,
             py::arg("idx"),
             "Number of turns agent[idx] takes per round (default 1).")
        .def("set_agent_turns",
             &CombatEngine::setAgentTurns,
             py::arg("idx"), py::arg("turns"),
             "Override turn count for agent[idx]. set_agent_turns(idx, 1) "
             "removes the override and restores the default.")
        .def("clear_agent_turns",
             &CombatEngine::clearAgentTurns,
             "Reset every agent to the default of 1 turn per round.")

        // ── Movement budget ───────────────────────────────────────────────
        .def("begin_turn",
             &CombatEngine::beginTurn,
             py::arg("agent_idx"), py::arg("battle_map"),
             "Seed walk/fly movement budgets from agent stats. Call at turn start.")
        .def("get_walk_remaining",
             &CombatEngine::getWalkRemaining,
             py::arg("agent_idx"),
             "Remaining walk movement in feet for agent_idx this turn.")
        .def("get_fly_remaining",
             &CombatEngine::getFlyRemaining,
             py::arg("agent_idx"),
             "Remaining fly movement in feet for agent_idx this turn.")
        .def("get_swim_remaining",
             &CombatEngine::getSwimRemaining,
             py::arg("agent_idx"),
             "Remaining swim movement in feet for agent_idx this turn.")
        .def("get_burrow_remaining",
             &CombatEngine::getBurrowRemaining,
             py::arg("agent_idx"),
             "Remaining burrow movement in feet for agent_idx this turn.")
        .def("spend_walk",
             &CombatEngine::spendWalk,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from walk budget (clamped to 0). Returns amount spent.")
        .def("spend_fly",
             &CombatEngine::spendFly,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from fly budget (clamped to 0). Returns amount spent.")
        .def("spend_swim",
             &CombatEngine::spendSwim,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from swim budget (clamped to 0). Returns amount spent.")
        .def("spend_burrow",
             &CombatEngine::spendBurrow,
             py::arg("agent_idx"), py::arg("feet"),
             "Deduct feet from burrow budget (clamped to 0). Returns amount spent.")
        .def("clear_movement",
             &CombatEngine::clearMovement,
             "Clear all movement budgets (call at end of combat).")

        .def("set_logger",
             &CombatEngine::setLogger,
             py::arg("logger"),
             py::keep_alive<1, 2>(),
             "Attach a MessageLogger; flush() it after each action to read messages.")

        // Round execution
        .def("run_round",
             &CombatEngine::runRound,
             py::arg("battle_map"), py::arg("turns"),
             "Execute one combat round from an ordered list of TurnActions.\n"
             "Each entry triggers action(), bonusAction(), walk(), fly() on\n"
             "the acting agent, resolves any weapon Attacks, and calls\n"
             "reaction() on any targeted agent.\n"
             "Returns a list of AttackResult (one per resolved Attack).")

        // Spell mechanics
        .def("execute_spell",
             &CombatEngine::executeSpell,
             py::arg("battle_map"), py::arg("action"),
             "Validate + execute a SpellAction; applies damage/healing to targets\n"
             "and writes HP changes back to BattleMap.\n"
             "Registers persistent effects when spell.duration > 1.")
        .def("tick_effects",
             &CombatEngine::tickEffects,
             py::arg("battle_map"),
             "Apply per-turn damage/healing for active persistent effects;\n"
             "decrement turns_remaining and remove expired effects.")
        .def_property_readonly("active_effects",
             [](const CombatEngine& e) { return e.activeEffects(); },
             "List of ActiveEffect objects currently in play.")
        .def("clear_effects",
             &CombatEngine::clearEffects,
             "Remove all persistent spell effects.")
        .def("concentration_save",
             &CombatEngine::concentrationSave,
             py::arg("battle_map"), py::arg("agent_idx"), py::arg("damage_taken"),
             "Check if concentrating agent must save (on damage).\n"
             "Rolls CON save (DC = max(10, damage/2)).\n"
             "Clears concentration on failed save.\n"
             "Returns ConcentrationSaveResult with details.")

        // RNG
        .def("reseed", &CombatEngine::reseed, py::arg("seed"));

    // ── MovementType ─────────────────────────────────────────────────────────
    py::enum_<MovementType>(m, "MovementType")
        .value("Walk",   MovementType::Walk,
               "Ground movement: BFS through passable cells, respects walls.")
        .value("Fly",    MovementType::Fly,
               "Aerial movement: Chebyshev radius, ignores terrain obstacles.")
        .value("Swim",   MovementType::Swim,
               "Aquatic movement: through water terrain.")
        .value("Burrow", MovementType::Burrow,
               "Underground movement: ignores surface obstacles.")
        .export_values();

    // ── DetectionParams ─────────────────────────────────────────────────────
    py::class_<BattleMap::DetectionParams>(m, "DetectionParams")
        .def(py::init<>())
        .def_readwrite("canny_low",            &BattleMap::DetectionParams::cannyLow)
        .def_readwrite("canny_high",           &BattleMap::DetectionParams::cannyHigh)
        .def_readwrite("hough_threshold",      &BattleMap::DetectionParams::houghThreshold)
        .def_readwrite("min_line_length",      &BattleMap::DetectionParams::minLineLength)
        .def_readwrite("max_line_gap",         &BattleMap::DetectionParams::maxLineGap)
        // Primary wall method: cells darker than this threshold (0–255) are obstacles
        .def_readwrite("dark_cell_threshold",  &BattleMap::DetectionParams::darkCellThreshold)
        // Secondary wall method: detect thick lines drawn between cells (opt-in)
        .def_readwrite("detect_edge_walls",    &BattleMap::DetectionParams::detectEdgeWalls)
        .def_readwrite("wall_min_px",          &BattleMap::DetectionParams::wallMinPx)
        .def_readwrite("flood_fill",           &BattleMap::DetectionParams::floodFill)
        .def_readwrite("flood_seed",           &BattleMap::DetectionParams::floodSeed);

    // ── TerrainType enum ────────────────────────────────────────────────────
    py::enum_<TerrainType>(m, "TerrainType")
        .value("Standard", TerrainType::Standard)
        .value("Water",    TerrainType::Water)
        .value("Wall",     TerrainType::Wall)
        .value("Chasm",    TerrainType::Chasm)
        .export_values();

    // ── TerrainDifficulty enum ──────────────────────────────────────────────
    py::enum_<TerrainDifficulty>(m, "TerrainDifficulty")
        .value("Normal",    TerrainDifficulty::Normal)
        .value("Halved",    TerrainDifficulty::Halved)
        .value("Quartered", TerrainDifficulty::Quartered)
        .export_values();

    // ── ActiveTerrainEffect struct ───────────────────────────────────────────
    py::class_<ActiveTerrainEffect>(m, "ActiveTerrainEffect")
        .def_readonly("id",                &ActiveTerrainEffect::id)
        .def_readonly("name",              &ActiveTerrainEffect::name)
        .def_readonly("cell_indices",      &ActiveTerrainEffect::cell_indices)
        .def_readonly("difficulty",        &ActiveTerrainEffect::difficulty)
        .def_readonly("turns_remaining",   &ActiveTerrainEffect::turns_remaining)
        .def_readonly("source_agent_idx",  &ActiveTerrainEffect::source_agent_idx);

    // ── BattleMap ───────────────────────────────────────────────────────────
    py::class_<BattleMap>(m, "BattleMap")
        .def(py::init<std::string>(),   // accept plain str from Python
             py::arg("map_image_path"))

        // Grid analysis
        .def("analyze_grid",  &BattleMap::analyzeGrid,
             "Detect grid lines; call before detect_walls().")
        .def("detect_walls",  &BattleMap::detectWalls,
             "Detect thick walls and compute disallowed cells via flood fill.")

        // Grid geometry (used by Python renderer to draw overlays)
        .def_property_readonly("grid_cols",       &BattleMap::gridCols)
        .def_property_readonly("grid_rows",       &BattleMap::gridRows)
        .def_property_readonly("cell_pixel_size", &BattleMap::cellPixelSize)
        .def_property_readonly("h_line_positions",&BattleMap::hLinePositions)
        .def_property_readonly("v_line_positions",&BattleMap::vLinePositions)

        // Wall / passability data
        .def_property_readonly("walls", [](const BattleMap& bm) -> std::vector<Wall> {
            return {bm.walls().begin(), bm.walls().end()};
        })
        .def_property_readonly("disallowed_cells", [](const BattleMap& bm){
            return cellSetToVec(bm.disallowedCells());
        })
        .def("is_blocked", &BattleMap::isBlocked,
             py::arg("origin"), py::arg("agent_size"), py::arg("movement_type") = MovementType::Walk)

        // Agent management
        .def("add_agent_config",   &BattleMap::addAgentConfig,   py::arg("config"))
        .def("apply_agent_configs",&BattleMap::applyAgentConfigs)
        .def("clear_agents",       &BattleMap::clearAgents)
        .def("move_agent",         &BattleMap::moveAgent,
             py::arg("idx"), py::arg("new_origin"),
             py::arg("movement_type") = MovementType::Walk,
             "Move placed agent[idx] to new_origin using the given movement type.\n"
             "Returns False if the agent lacks sufficient movement budget.")
        .def("jump_agent",         &BattleMap::jumpAgent,
             py::arg("idx"), py::arg("new_origin"), py::arg("is_running"),
             "Jump placed agent[idx] to new_origin (ignores walls, deducts from walk budget).\n"
             "is_running: True for running jump (up to STR), False for standing jump (up to STR/2).\n"
             "Returns False if out of range or insufficient movement budget.")
        .def("remove_agent",       &BattleMap::removeAgent,
             py::arg("idx"),
             "Remove placed agent[idx] from the map.")
        .def("get_agent_stats",    &BattleMap::getAgentStats,
             py::arg("idx"),
             "Return a copy of the Stats for placed agent[idx].")
        .def("set_agent_stats",    &BattleMap::setAgentStats,
             py::arg("idx"), py::arg("stats"),
             "Replace the Stats for placed agent[idx].")
        .def("apply_dash",         &BattleMap::applyDash,
             py::arg("idx"),
             "Set dashing condition and add base speeds to remaining movement for agent[idx].")

        // Weapon accessors
        .def("get_agent_weapons",  &BattleMap::getAgentWeapons,
             py::arg("idx"),
             "Return a copy of the weapon list for placed agent[idx].")
        .def("set_agent_weapons",  &BattleMap::setAgentWeapons,
             py::arg("idx"), py::arg("weapons"),
             "Replace the weapon list for placed agent[idx].")
        .def("add_weapon_to_agent",&BattleMap::addWeaponToAgent,
             py::arg("idx"), py::arg("weapon"),
             "Append a weapon to placed agent[idx]'s weapon list.")
        .def("remove_weapon_from_agent", &BattleMap::removeWeaponFromAgent,
             py::arg("idx"), py::arg("weapon_idx"),
             "Remove weapon at weapon_idx from placed agent[idx]'s list.")

        // Spell accessors
        .def("get_agent_spells",   &BattleMap::getAgentSpells,
             py::arg("idx"),
             "Return a copy of the spell list for placed agent[idx].")
        .def("set_agent_spells",   &BattleMap::setAgentSpells,
             py::arg("idx"), py::arg("spells"),
             "Replace the spell list for placed agent[idx].")
        .def("add_spell_to_agent", &BattleMap::addSpellToAgent,
             py::arg("idx"), py::arg("spell"),
             "Append a spell to placed agent[idx]'s spell list.")
        .def("remove_spell_from_agent", &BattleMap::removeSpellFromAgent,
             py::arg("idx"), py::arg("spell_idx"),
             "Remove spell at spell_idx from placed agent[idx]'s list.")

        // Condition accessors
        .def("get_agent_conditions", &BattleMap::getAgentConditions,
             py::arg("idx"),
             "Return a copy of the Conditions for placed agent[idx].")
        .def("set_agent_conditions", &BattleMap::setAgentConditions,
             py::arg("idx"), py::arg("conditions"),
             "Replace the Conditions for placed agent[idx].")

        // Line-of-sight
        .def("has_line_of_sight",
             &BattleMap::hasLineOfSight,
             py::arg("from_origin"), py::arg("from_size"),
             py::arg("to_origin"),   py::arg("to_size"),
             "Bresenham ray from centre of 'from' agent to centre of 'to' agent.\n"
             "Returns False if any intermediate cell is a wall/obstacle.")

        .def("filter_spell_cells",
             &BattleMap::filterSpellCells,
             py::arg("cells"), py::arg("caster_origin"), py::arg("caster_size"),
             py::arg("spell"), py::arg("center_cell"),
             "Filter spell cells by range and line-of-sight requirements.\n"
             "Respects spell.requires_los and spell.check_los_on_center flags.\n"
             "If check_los_on_center, only the center cell needs LOS (D&D 5e standard).")

        // Attack target cells (melee reach or ranged range, with LoS filter)
        .def("attack_target_cells",
             [](const BattleMap& bm, Cell origin, int agentSize, int rangeFt) {
                 return bm.attackTargetCells(origin, agentSize, rangeFt);
             },
             py::arg("origin"), py::arg("agent_size"), py::arg("range_ft"),
             "Return cells within range_ft feet (Chebyshev from footprint edge)\n"
             "that have line-of-sight from the agent.\n"
             "Use for melee (range_ft = 5/10/15) and ranged (call twice for\n"
             "normal/long zones and subtract).")

        // Movement reach
        .def("reachable_cells",
             [](const BattleMap& bm, Cell origin, int agentSize,
                int speedFt, MovementType type) {
                 return cellSetToVec(bm.reachableCells(origin, agentSize,
                                                       speedFt, type));
             },
             py::arg("origin"), py::arg("agent_size"),
             py::arg("speed_ft"), py::arg("movement_type"),
             "Return a list of Cell origins reachable from origin.\n"
             "Walk: Dijkstra BFS through passable cells.\n"
             "Fly:  Chebyshev radius ignoring terrain.")

        .def_property_readonly("placed_agents", [](const BattleMap& bm){
            auto sp = bm.placedAgents();
            return std::vector<PlacedAgent>(sp.begin(), sp.end());
        })

        // Terrain multipliers (for difficult terrain, spells, etc.)
        .def("get_terrain_multiplier", &BattleMap::getTerrainMultiplier,
             py::arg("cell"), py::arg("movement_type") = MovementType::Walk,
             "Get the movement cost multiplier for a cell (default 1.0).")
        .def("set_terrain_multiplier", &BattleMap::setTerrainMultiplier,
             py::arg("cell"), py::arg("multiplier"),
             "Set the movement cost multiplier for a single cell.")
        .def("set_terrain_multiplier_rect", &BattleMap::setTerrainMultiplierRect,
             py::arg("top_left"), py::arg("width"), py::arg("height"), py::arg("multiplier"),
             "Set the movement cost multiplier for a rectangular region.")
        .def("reset_terrain_multipliers", &BattleMap::resetTerrainMultipliers,
             "Reset all terrain multipliers to 1.0 (default).")

        // Terrain types (Standard, Water, Wall, Chasm)
        .def("get_terrain_type", &BattleMap::getTerrainType,
             py::arg("cell"),
             "Get the terrain type for a cell (Standard, Water, Wall, or Chasm).")
        .def("set_terrain_type", &BattleMap::setTerrainType,
             py::arg("cell"), py::arg("terrain_type"),
             "Set the terrain type for a cell.")

        // Temporary terrain effects (spells, items, etc. with duration)
        .def("place_terrain_effect", &BattleMap::placeTerrainEffect,
             py::arg("name"), py::arg("cells"), py::arg("difficulty"),
             py::arg("turns_remaining"), py::arg("source_agent_idx"),
             "Place a temporary terrain effect covering the given cells.\n"
             "Returns unique effect id (for later removal/metadata).")
        .def("tick_terrain_effects", &BattleMap::tickTerrainEffects,
             py::arg("source_agent_idx"),
             "Decrement turns_remaining for effects from this source.\n"
             "Removes expired effects (turns_remaining <= 0).\n"
             "Returns list of removed effect ids.")
        .def("tick_dm_terrain_effects", &BattleMap::tickDMTerrainEffects,
             "Decrement turns_remaining for DM-placed effects (source_agent_idx == -1).\n"
             "Called at round boundary. Returns list of removed effect ids.")
        .def("remove_terrain_effects_by_source", &BattleMap::removeTerrainEffectsBySource,
             py::arg("source_agent_idx"),
             "Remove all effects sourced from the given agent (concentration drop, death, etc.).\n"
             "Returns list of removed effect ids.")
        .def("remove_terrain_effect", &BattleMap::removeTerrainEffect,
             py::arg("effect_id"),
             "Remove a specific effect by id (manual DM removal).")
        .def("clear_terrain_effects", &BattleMap::clearTerrainEffects,
             "Clear all terrain effects (end of combat).")
        .def_property_readonly("active_terrain_effects", &BattleMap::activeTerrainEffects,
             "Get a copy of all active terrain effects (for rendering).")
        .def("has_active_terrain_effects", &BattleMap::hasActiveTerrainEffects,
             "Check if there are any active terrain effects.")

        // Expose params so Python can tune detection
        .def_readwrite("params", &BattleMap::params);

    // ── Map Configuration Functions ───────────────────────────────────────
    m.def("apply_terrain_configuration", &applyTerrainConfiguration,
         py::arg("bm"), py::arg("json_path"),
         "Load and apply terrain configuration from a JSON file to the BattleMap.\n"
         "JSON format: {\"terrain_features\": [{\"type\": \"rect|column|row|cell\", ...}]}");
}
