#!/usr/bin/env python3
"""The board snapshot, `BattleMap.snapshot_json` / `restore_json` (MULTIPLAYER_PLAN.md M6.2).

The restore oracle (`test_restore_oracle.py`) checks that a whole fight comes back. This
suite checks the snapshot's own contract:

  · **No forgotten field.** `Agent::Stats` and `Agent::Conditions` are serialized from
    hand-kept X-macro lists (both are past nlohmann's 64-member macro limit), and the
    effect / loadout types from macro lists. A field added to a struct without a line in
    its list would silently not be saved. `test_field_lists_match_structs` parses the
    headers and the lists from source text and fails on any difference.
  · **Every bound field round-trips**, set to a value that is not its default.
  · **A refusal changes nothing**: a wrong basis, grid, version or shape, or a truncated
    file, returns False and leaves the board exactly as it was.
  · **The overlay keeps what the payload omits.**
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUI = os.path.join(_ROOT, "gui")
sys.path.insert(0, _GUI)
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import re
import shutil
import tempfile

import rpg_battle_map as rpg

from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20261020


# ─────────────────────────────────────────────────────────────────────────────
#  Struct members, from source text
# ─────────────────────────────────────────────────────────────────────────────

def _strip_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def _struct_body(src, header):
    """The text between the braces of the first `header` (e.g. "struct Stats {")."""
    i = src.index("{", src.index(header)) + 1
    depth, k = 1, i
    while depth:
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        k += 1
    return src[i:k - 1]


def _top_level_statements(body):
    """The `;`-terminated statements at brace depth 0. A function body or a nested type
    (anything a `}` closes at depth 0 without a `;`) is dropped."""
    out, cur, depth = [], "", 0
    for ch in body:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        if depth == 0 and ch == ";":
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
        if ch == "}" and depth == 0:
            st = cur.strip()
            if (re.search(r"\)\s*(const)?\s*(noexcept)?\s*(override)?\s*\{.*\}$", st, re.S)
                    or re.match(r"(struct|enum|class|union)\b", st)):
                cur = ""
    return out


def members(path, header):
    """Data member names of the struct `header` in `path`, in declaration order."""
    src = _strip_comments(open(os.path.join(_GUI, path)).read())
    names = []
    for st in _top_level_statements(_struct_body(src, header)):
        st = " ".join(st.split())
        st = re.sub(r"^(public|private|protected)\s*:\s*", "", st)
        if not st or st.startswith(("static", "using", "typedef", "friend", "template",
                                    "enum", "struct")):
            continue
        st = re.sub(r"\{[^{}]*\}", "", re.sub(r"\{[^{}]*\}", "", st))   # brace initializers
        paren, eq = st.find("("), st.find("=")
        if paren >= 0 and (eq < 0 or paren < eq):
            continue                                                   # a function
        if eq >= 0:
            st = re.sub(r"=[^,]*", "", st)                             # `= value` initializers
        parts, depth, cur = [], 0, ""
        for ch in st:                      # split declarators on commas outside <...>
            depth += {"<": 1, ">": -1}.get(ch, 0)
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for p in parts:
            names.append(re.sub(r"\[.*", "", p.split()[-1]))
    return names


def _xmacro(src, name):
    m = re.search(r"#define " + name + r"\(X\)((?:[^\n]*\\\n)*[^\n]*)", src)
    assert m, f"no {name} in battle_map_serialization.cpp"
    return re.findall(r"X\((\w+)\)", m.group(1))


def _nlohmann(src, type_name):
    m = re.search(r"NLOHMANN_DEFINE_TYPE_NON_INTRUSIVE_WITH_DEFAULT\(\s*" + type_name
                  + r"\s*,(.*?)\)\n", src, re.S)
    assert m, f"no mapping for {type_name}"
    return [f.strip() for f in m.group(1).split(",") if f.strip()]


def test_field_lists_match_structs():
    """Each serialized type's field list names exactly the struct's members."""
    board = open(os.path.join(_GUI, "battle_map_serialization.cpp")).read()
    shared = open(os.path.join(_GUI, "serialization_mappings.hpp")).read()
    checks = [
        ("Stats",       members("agent.hpp", "struct Stats {"),
                        _xmacro(board, "RPG_STATS_FIELDS")),
        ("Conditions",  members("agent.hpp", "struct Conditions {"),
                        _xmacro(board, "RPG_CONDITIONS_FIELDS")),
        # `agent` is written as the record's name/size/z/stats/conditions/movement keys.
        ("PlacedAgent", [m for m in members("battle_map.hpp", "struct PlacedAgent {")
                         if m != "agent"],
                        _xmacro(board, "RPG_PLACED_AGENT_FIELDS")),
    ]
    for type_name, path, src in [
            ("ActiveTerrainEffect", "battle_map.hpp", board),
            ("ActiveLightEffect",   "battle_map.hpp", board),
            ("ActiveSpellEffect",   "battle_map.hpp", board),
            ("Resource",            "resource.hpp",   board),
            ("Item",                "item.hpp",       board),
            ("Armor",               "armor.hpp",      board),
            ("Weapon",              "weapon.hpp",     shared),
            ("Spell",               "spell.hpp",      shared),
            ("AttackCondition",     "condition.hpp",  shared)]:
        checks.append((type_name, members(path, f"struct {type_name} {{"),
                       _nlohmann(src, type_name)))
    for type_name, declared, listed in checks:
        assert len(declared) > 3, f"the parser found almost no members in {type_name}"
        missing = [f for f in declared if f not in listed]
        extra = [f for f in listed if f not in declared]
        assert not missing, f"{type_name} members not serialized: {missing}"
        assert not extra, f"{type_name} list names fields the struct lacks: {extra}"
    print(f"✅ test_field_lists_match_structs ({len(checks)} types, "
          f"{sum(len(d) for _, d, _ in checks)} fields)")


# ─────────────────────────────────────────────────────────────────────────────
#  Round trips on a live board
# ─────────────────────────────────────────────────────────────────────────────

def _app(tmpdir):
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "snap_agents.json"))
    for name, col, row in (("Aria", 2, 3), ("Gnasher", 8, 3)):
        cfg = rpg.AgentConfig()
        cfg.name, cfg.start_col, cfg.start_row, cfg.size = name, col, row, 1
        cfg.sprite_path = ""
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    return app


def _public(obj):
    out = {}
    for name in dir(obj):
        if name.startswith("_"):
            continue
        try:
            val = getattr(obj, name)
        except Exception:
            continue
        if not callable(val):
            out[name] = val
    return out


def _shifted(val):
    """A value of the same type as `val` that is not `val`, or None to leave it alone."""
    if isinstance(val, bool):
        return not val
    if isinstance(val, int):
        return val + 3
    if isinstance(val, float):
        return val + 0.25
    if isinstance(val, str):
        return val + "x"
    members_ = getattr(type(val), "__members__", None)
    if members_:
        others = [m for m in members_.values() if m != val]
        return others[0] if others else None
    if isinstance(val, list) and val and all(isinstance(v, int) and not isinstance(v, bool)
                                             for v in val):
        return [v + 1 for v in val]
    return None


def _mutate(obj):
    """Set every writable scalar attribute of a bound struct to a non-default value."""
    changed = 0
    for name, val in _public(obj).items():
        new = _shifted(val)
        if new is None:
            continue
        try:
            setattr(obj, name, new)
        except Exception:
            continue                                      # read-only property
        changed += getattr(obj, name) != val
    return changed


def _plain(d):
    return {k: (str(v) if hasattr(type(v), "__members__") else v) for k, v in d.items()}


def test_bound_fields_round_trip():
    """Every bound Stats and Conditions field, set off its default, survives a restore
    onto an agent reset to defaults."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        bm, combat = app.bm, app.combat
        stats, cond = rpg.Stats(), rpg.Conditions()
        n_stats, n_cond = _mutate(stats), _mutate(cond)
        assert n_stats > 150 and n_cond > 120, (n_stats, n_cond)
        combat.set_agent_stats(bm, 0, stats)
        combat.set_agent_conditions(bm, 0, cond)
        want_stats = _plain(_public(combat.get_agent_stats(bm, 0)))
        want_cond = _plain(_public(combat.get_agent_conditions(bm, 0)))
        snap = bm.snapshot_json()

        combat.set_agent_stats(bm, 0, rpg.Stats())
        combat.set_agent_conditions(bm, 0, rpg.Conditions())
        assert _plain(_public(combat.get_agent_stats(bm, 0))) != want_stats
        assert bm.restore_json(snap)
        got_stats = _plain(_public(combat.get_agent_stats(bm, 0)))
        got_cond = _plain(_public(combat.get_agent_conditions(bm, 0)))
        lost = sorted(k for k in want_stats if got_stats.get(k) != want_stats[k])
        lost += sorted(f"conditions.{k}" for k in want_cond if got_cond.get(k) != want_cond[k])
        assert not lost, f"fields that did not round-trip: {lost}"
        print(f"✅ test_bound_fields_round_trip ({n_stats} stats, {n_cond} conditions)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_budgets_and_placement_round_trip():
    """The raw movement budgets come back exactly, exhaustion and all, and so do the
    PlacedAgent fields (a tombstone stays banished off-map)."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        bm, combat = app.bm, app.combat
        bm.placed_agents[0].init_movement(25, 40, 10, 5)
        cond = combat.get_agent_conditions(bm, 0)
        cond.exhaustion_level = 1
        combat.set_agent_conditions(bm, 0, cond)
        bm.set_agent_faction(1, 2)
        bm.set_agent_controller(1, "p-123")
        bm.set_agent_removed_from_play(1, True)
        before = (bm.placed_agents[0].walk_remaining, bm.placed_agents[0].fly_remaining)
        assert before == (20, 35), before
        snap = bm.snapshot_json()

        bm.placed_agents[0].init_movement(0, 0, 0, 0)
        bm.set_agent_faction(1, 0)
        bm.set_agent_controller(1, "dm")
        assert bm.restore_json(snap)
        pt0, pt1 = bm.placed_agents[0], bm.placed_agents[1]
        assert (pt0.walk_remaining, pt0.fly_remaining, pt0.swim_remaining,
                pt0.burrow_remaining) == (20, 35, 5, 0)
        assert (pt1.faction, pt1.controller, pt1.removed_from_play) == (2, "p-123", True)
        assert (pt1.origin.col, pt1.origin.row) == (-1, -1)
        assert bm.snapshot_json() == snap, "a restore is not a fixed point"
        print("✅ test_budgets_and_placement_round_trip")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_refusals_change_nothing():
    """Every refusal returns False and leaves the board byte-for-byte as it was."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        bm, combat = app.bm, app.combat
        bm.place_terrain_effect("Rubble", [rpg.Cell(4, 8)], rpg.TerrainDifficulty.Halved, 5, -1)
        doc = json.loads(bm.snapshot_json())
        s = combat.get_agent_stats(bm, 0)
        s.hp_cur = 3
        combat.set_agent_stats(bm, 0, s)
        bm.clear_terrain_effects()
        live = bm.snapshot_json()

        def edited(fn):
            d = json.loads(json.dumps(doc))
            fn(d)
            return json.dumps(d)

        def rename(d):
            d["agents"][1]["name"] = "Someone Else"

        def resize(d):
            d["agents"][0]["size"] = 2

        def bad_stats(d):
            d["agents"][0]["stats"]["hp_cur"] = "lots"   # the wrong shape, mid-payload

        cases = {
            "truncated":     json.dumps(doc)[:-40],
            "not an object": "[1, 2, 3]",
            "newer version": edited(lambda d: d.update(version=99)),
            "other grid":    edited(lambda d: d.update(cols=d["cols"] + 1)),
            "fewer agents":  edited(lambda d: d["agents"].pop()),
            "renamed agent": edited(rename),
            "resized agent": edited(resize),
            "short terrain": edited(lambda d: d["terrain_mult"].pop()),
            "stats shape":   edited(bad_stats),
            "stats a list":  edited(lambda d: d["agents"][0].update(stats=[1])),
        }
        for label, text in cases.items():
            assert bm.restore_json(text) is False, f"{label}: accepted"
            assert bm.snapshot_json() == live, f"{label}: refused, but changed the board"
        assert bm.restore_json(json.dumps(doc)), "the unedited payload must still restore"
        assert len(bm.active_terrain_effects) == 1
        print(f"✅ test_refusals_change_nothing ({len(cases)} refusals)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_omitted_keys_keep_the_built_value():
    """The overlay writes what the payload carries and keeps the rest."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        bm, combat = app.bm, app.combat
        cond = combat.get_agent_conditions(bm, 0)
        cond.prone = True
        combat.set_agent_conditions(bm, 0, cond)
        doc = json.loads(bm.snapshot_json())
        del doc["agents"][0]["conditions"]
        del doc["agents"][0]["stats"]["hp_cur"]
        doc["agents"][0]["stats"]["hp_max"] = 77

        s = combat.get_agent_stats(bm, 0)
        s.hp_cur = 4
        combat.set_agent_stats(bm, 0, s)
        cond.prone = False
        cond.blinded = True
        combat.set_agent_conditions(bm, 0, cond)
        assert bm.restore_json(json.dumps(doc))
        s, cond = combat.get_agent_stats(bm, 0), combat.get_agent_conditions(bm, 0)
        assert s.hp_max == 77 and s.hp_cur == 4, (s.hp_max, s.hp_cur)
        assert cond.blinded and not cond.prone, "omitted conditions must keep the built ones"
        print("✅ test_omitted_keys_keep_the_built_value")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sidecar_without_a_board_still_loads():
    """A `_combat.json` written before M6.2 has `agent_budgets` and no board; the resume
    still runs and still re-seeds the budgets from it."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app(tmp)
        app._start_combat()
        actor = app._current_agent_idx()
        app.bm.placed_agents[actor].init_movement(15)
        app._save_agents()
        with open(app._combat_path) as f:
            doc = json.load(f)
        assert "board" in doc and "agent_budgets" not in doc
        del doc["board"]
        doc["agent_budgets"] = [[15, 0, 0, 0] if i == actor else [30, 0, 0, 0]
                                for i in range(len(app.bm.placed_agents))]
        with open(app._combat_path, "w") as f:
            json.dump(doc, f)

        app2 = App(MAP_PATH, seed=SEED)
        app2._on_load_path_chosen(app._save_path)
        assert app2.combat_active
        assert app2.bm.placed_agents[actor].walk_remaining == 15
        print("✅ test_sidecar_without_a_board_still_loads")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    tests = [test_field_lists_match_structs, test_bound_fields_round_trip,
             test_budgets_and_placement_round_trip, test_refusals_change_nothing,
             test_omitted_keys_keep_the_built_value, test_sidecar_without_a_board_still_loads]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as e:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"❌ {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
