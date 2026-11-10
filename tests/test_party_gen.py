#!/usr/bin/env python3
"""Generated parties (NPC_LEARNING_PLAN.md Step 3b, gui/party_gen.py + gui/pc_templates.json).

Every build in the role table resolves against the catalogs and loads in the engine at levels
1, 5, 11 and 17 with the HP, AC, spells and slots the rules say; a seed always gives the same
party; the composition, role-split and level proportions hold over many draws; the arena draws
generated parties 80% of the time; and in a fight, a PC with signature spells casts them first.
"""

import json
import os
import random
from collections import Counter

import gui_driver   # noqa: F401 — sets the dummy SDL drivers and gui/ on sys.path first

import rpg_battle_map as rpg
import arena
import party_gen as G
import import_character

LEVELS = (1, 5, 11, 17)
_GUI = os.path.dirname(os.path.abspath(G.__file__))


def _features() -> set:
    with open(os.path.join(_GUI, "classfeatures.json")) as f:
        return {x["name"] for x in json.load(f)}


# ── The data ─────────────────────────────────────────────────────────────────
def test_role_table_and_catalog_names_resolve():
    subs = G.subclasses()
    assert len(subs) == 48 and len(G.builds()) == 94
    t = G.data().t
    cat = G.data().spells
    feats_ok = import_character.KNOWN_FEATS
    for key, sc in subs.items():
        cls = key.split(".")[0]
        enum_names = getattr(rpg, {"Barbarian": "BarbianSubclass", "Druid": "DruidCircle",
                                   "Paladin": "PaladinOath", "Bard": "BardCollege"}
                             .get(cls, f"{cls}Subclass")).__members__
        assert sc["enum"] in enum_names, key
        for name in (sc.get("signatures") or {}).get("spells", []):
            assert name in cat or name in _features(), f"{key}: signature {name!r} unknown"
    for (key, role) in G.builds():
        b = G.resolved_build(key, role)
        assert f"{key.split('.')[0]}.{role}" in t["builds"]
        for w in (b.get("weapons") or {}).values():
            assert w in G.data().weapons, f"{key}/{role}: weapon {w!r}"
        for f in (b.get("origin_feat"), b.get("feat"), b.get("style")):
            assert f is None or f in feats_ok, f"{key}/{role}: feat {f!r}"
        for n in b.get("cantrips", []):
            assert cat.get(n, {}).get("level") == 0, f"{key}/{role}: cantrip {n!r}"
        for lv, names in (b.get("spells") or {}).items():
            for n in names:
                assert n in cat and cat[n]["level"] == int(lv), f"{key}/{role}: {n!r} at {lv}"
    print("✅ test_role_table_and_catalog_names_resolve passed")


def test_ability_scores_hp_and_asis():
    pc = G.build_pc("Fighter.Champion", "ST", 1)
    s = pc["stats"]
    assert sorted((s[a] for a in G.ABILITIES), reverse=True) == list(G.SCORES)
    assert (s["str"], s["con"], s["dex"]) == (17, 16, 14)
    assert s["hp_max"] == 10 + 3 and s["feats"] == ["Savage Attacker", "Great Weapon Fighting"]
    hi = G.build_pc("Fighter.Champion", "ST", 20)["stats"]
    # Fighter ASIs at 4 6 8 12 14 16 (19 ignored): the feat, then 10 points: STR 17→20,
    # CON 16→20, DEX 14→17.
    assert hi["feats"][-1] == "Great Weapon Master"
    assert hi["str"] == 20 and hi["con"] == 20 and hi["dex"] == 17
    assert hi["num_attacks"] == 4 and hi["prof_bonus"] == 6
    tough = G.build_pc("Barbarian.WildHeart", "DEF", 10)["stats"]
    con = (tough["con"] - 10) // 2
    assert tough["hp_max"] == 12 + con + 9 * (7 + con) + 2 * 10
    print("✅ test_ability_scores_hp_and_asis passed")


# ── In the engine ────────────────────────────────────────────────────────────
def _expected_ac(rec, b, eng_stats) -> int | None:
    """The AC B7 promises, or None where the engine's Unarmored Defense decides."""
    cls, lv = rec["agent_class"], rec["agent_char_level"]
    dex = (rec["stats"]["dex"] - 10) // 2
    armor = b["armor"]
    shield = 2 if (b.get("weapons") or {}).get("off_hand") == "Shield" else 0
    if armor == "unarmored" or cls in ("Barbarian", "Monk"):
        return None
    if cls == "Sorcerer" and rec["agent_sorcerer_subclass"] == "Draconic" and lv >= 3:
        return None
    if cls == "Warlock" and 5 in rec.get("agent_eldritch_invocations", []):
        return 13 + dex + shield
    defense = 1 if "Defense" in rec["stats"]["feats"] else 0
    ac = {"heavy": 16 if lv < 9 else 18, "medium": (14 if lv < 5 else 15) + min(dex, 2),
          "light": 12 + dex, "mage": 13 + dex}[armor]
    return ac + shield + (defense if armor != "mage" else 0)


def test_every_build_loads_at_each_tier():
    ar = arena.arena()
    for lv in LEVELS:
        recs = []
        for i, (key, role) in enumerate(G.builds()):
            r = G.build_pc(key, role, lv, name=f"{key}/{role}")
            r["col"], r["row"] = i % 12, i // 12
            recs.append(r)
        bm, eng = ar.load_board("gui/TestGrid12x12.png", None, 1)
        ar.load_agents(recs)
        for i, r in enumerate(recs):
            key, role = r["pc_build"]["subclass"], r["pc_build"]["role"]
            st = eng.get_agent_stats(bm, i)
            assert st.character_class.name == r["agent_class"] and st.char_level == lv, r["name"]
            # The engine adds Draconic Resilience (+1 HP per level from 3) when it loads the PC.
            resil = lv if key == "Sorcerer.Draconic" and lv >= 3 else 0
            assert st.hp_max == r["stats"]["hp_max"] + resil, (r["name"], lv, st.hp_max)
            names = {sp.name for sp in eng.get_agent_spells(bm, i)}
            missing = set(r["spell_indices"]) - names
            assert not missing, f"{r['name']} L{lv}: spells not loaded {missing}"
            want = _expected_ac(r, G.resolved_build(key, role), st)
            if want is not None:
                assert eng.calculate_ac(bm, i) == want, (r["name"], lv, eng.calculate_ac(bm, i), want)
            caster = G.data().t["classes"][r["agent_class"]].get("caster")
            if G.subclasses()[key].get("third_caster"):
                caster = "third"
            top = G.max_spell_level(caster, lv)
            if top and lv >= 5:
                assert st.spell_slots_max[top - 1] > 0, f"{r['name']} L{lv}: no level-{top} slot"
                assert all(st.spell_slots_max[k] == 0 for k in range(top, 9)) or caster == "pact", r["name"]
            for n in r["spell_indices"]:
                lvl = G.data().spells[n]["level"]
                assert lvl <= max(top, 0), f"{r['name']} L{lv}: {n} above level {top}"
    print(f"✅ test_every_build_loads_at_each_tier passed ({len(G.builds())} builds × {len(LEVELS)})")


def test_signatures_are_prepared_first():
    light = G.build_pc("Cleric.LightDomain", "MT", 5)
    assert light["signature_spells"][:2] == ["Radiance of the Dawn", "Fireball"]
    assert "Fireball" in light["spell_indices"]
    low = G.build_pc("Cleric.LightDomain", "MT", 3)          # Fireball needs 3rd-level slots
    assert "Fireball" not in low["spell_indices"] and "Fireball" not in low["signature_spells"]
    abj = G.build_pc("Wizard.Abjurer", "DEF", 1)
    assert "Blade Ward" in abj["spell_indices"] and "Shield" in abj["spell_indices"]
    print("✅ test_signatures_are_prepared_first passed")


# ── Parties ──────────────────────────────────────────────────────────────────
def test_party_is_a_function_of_the_seed():
    a, ma = G.generate_party(7)
    b, mb = G.generate_party(7)
    assert a == b and ma == mb and len(a) == G.PARTY_SIZE
    assert len({p["pc_build"]["subclass"] for p in a}) == G.PARTY_SIZE
    assert len({p["agent_char_level"] for p in a}) == 1
    assert G.generate_party(8) != (a, ma)
    print("✅ test_party_is_a_function_of_the_seed passed")


def test_composition_proportions():
    n = 4000
    kinds, tiers, split = Counter(), Counter(), Counter()
    for seed in range(n):
        _, m = G.generate_party(seed)
        kinds[m["template"].split(":")[0]] += 1
        tiers[next(k for k, (lo, hi) in enumerate(G.TIERS) if lo <= m["level"] <= hi)] += 1
        for key, role in zip(m["builds"], m["roles"]):
            sc = G.subclasses()[key]
            split["primary" if sc["primary"] == role else "secondary"] += 1
    for kind, w in G.TEMPLATE_WEIGHTS:
        assert abs(kinds[kind] / n - w) < 0.03, (kind, kinds[kind] / n)
    for k in range(4):
        assert abs(tiers[k] / n - 0.25) < 0.03, (k, tiers[k] / n)
    share = split["primary"] / sum(split.values())
    # 3:1 per slot, shaped by how many subclasses list each role as primary vs secondary.
    assert 0.6 < share < 0.9, share
    print(f"✅ test_composition_proportions passed (primary share {share:.2f})")


def test_arena_draws_generated_parties_eighty_percent():
    rng = random.Random(3)
    pool = arena.default_party_sources()
    draws = Counter(arena.pick_party_source(rng, pool) for _ in range(10000))
    assert abs(draws[arena.GENERATED] / 10000 - arena.GENERATED_SHARE) < 0.02
    only = ["maps/TestDNDMap_agents.json"]
    assert arena.pick_party_source(random.Random(1), only) == only[0]
    print("✅ test_arena_draws_generated_parties_eighty_percent passed")


def _generated_scenario_with_signatures():
    for k in range(200):
        sc = arena.scenario_for_split(11, k, "any")
        if sc.meta.get("generated_party") and any(a.get("signature_spells") for a in sc.agents):
            return sc
    raise AssertionError("no generated scenario with signature spells in 200 draws")


def test_signature_pcs_cast_signatures_first():
    sc = _generated_scenario_with_signatures()
    out = arena.run_episode(sc, 5, "level4", "Heuristic")
    assert out["pc_policy"] == "level4+signatures"
    bm = arena.arena().app.bm
    for i, a in enumerate(sc.agents):
        if int(a.get("faction", 0)) != arena.PC_FACTION:
            continue
        want = arena.PC_POLICY_LEVEL if a.get("signature_spells") else arena.PC_HEURISTIC_LEVEL
        assert bm.get_agent_npc_automation_difficulty(i) == want, a["name"]

    # The same policy, watched: whenever a legal candidate casts a signature spell (and the
    # caster isn't already concentrating on a concentration one), the pick is a signature.
    seen = {"sig": 0, "missed": 0}

    def factory(eng, bm_, seed):
        sigs = {i: a["signature_spells"] for i, a in enumerate(sc.agents)
                if int(a.get("faction", 0)) == arena.PC_FACTION and a.get("signature_spells")}
        inner = arena.signature_policy(eng, bm_, sigs)

        def rank(idx, archetype, actions):
            out_ = inner(idx, archetype, actions)
            names = set(sigs.get(idx, []))
            me = bm_.placed_agents[idx]
            sp = me.spells
            castable = [i for i, a in enumerate(actions)
                        if a.legal and 0 <= a.spell_idx < len(sp) and sp[a.spell_idx].name in names
                        and a.kind != rpg.NpcMacroKind.Heal
                        and not (me.conditions.concentrating and sp[a.spell_idx].requires_concentration)]
            if castable:
                picked = out_ and 0 <= actions[out_[0]].spell_idx < len(sp) and \
                    sp[actions[out_[0]].spell_idx].name in names
                seen["sig" if picked else "missed"] += 1
            return out_
        return rank
    for seed in range(6):
        arena.run_episode(sc, seed, "level4", "SelfPlay", pc_policy_factory=factory)
    assert seen["sig"] > 0 and seen["missed"] == 0, seen
    print(f"✅ test_signature_pcs_cast_signatures_first passed ({seen['sig']} signature casts)")


if __name__ == "__main__":
    try:
        test_role_table_and_catalog_names_resolve()
        test_ability_scores_hp_and_asis()
        test_every_build_loads_at_each_tier()
        test_signatures_are_prepared_first()
        test_party_is_a_function_of_the_seed()
        test_composition_proportions()
        test_arena_draws_generated_parties_eighty_percent()
        test_signature_pcs_cast_signatures_first()
    finally:
        arena.arena().close()
    print("\nAll party generator tests passed! 🎉")
