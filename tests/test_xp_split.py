"""Encounter XP is divided equally among the party's characters.

Covered: compute_encounter_xp's per-member share (rounded down, party size of at least 1);
award_encounter_xp counts only PC-faction characters (not PC-faction summons) as the party,
adds each member's share to the tracker, logs the split, and awards each corpse once.
"""

import os
import sys
import types

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gui"))

import app_initiative
from constants import PC_FACTION
from xp import compute_encounter_xp

failures = 0


def check(cond, msg):
    global failures
    if not cond:
        failures += 1
        print("FAIL:", msg)


# ── compute_encounter_xp ──────────────────────────────────────────────────
r = compute_encounter_xp(["1/4"] * 4, party_size=4)
check(r["total_xp"] == 200 and r["per_member_xp"] == 50, f"4 goblins / 4 PCs: {r}")
r = compute_encounter_xp(["2"], party_size=4)            # 450 / 4 = 112.5
check(r["per_member_xp"] == 112, f"floor of 450/4: {r}")
r = compute_encounter_xp(["5", "1"], party_size=3)       # 2000 / 3
check(r["total_xp"] == 2000 and r["per_member_xp"] == 666, f"2000/3: {r}")
r = compute_encounter_xp(["1"], party_size=0)
check(r["party_size"] == 1 and r["per_member_xp"] == 200, f"party of 0 → 1: {r}")
r = compute_encounter_xp(["1"])
check(r["per_member_xp"] == 200, f"default party size 1: {r}")


# ── award_encounter_xp on a fake app ──────────────────────────────────────
ENEMY = PC_FACTION + 1


def _agent(name, faction, hp, level=1, npc=False, dead=False):
    pt = types.SimpleNamespace(name=name, faction=faction,
                               conditions=types.SimpleNamespace(dead=dead))
    st = types.SimpleNamespace(hp_cur=hp, char_level=level, is_npc=npc)
    return pt, st


def _fake_app(agents):
    log, modals = [], []
    stats = [st for _pt, st in agents]
    app = types.SimpleNamespace(
        bm=types.SimpleNamespace(placed_agents=[pt for pt, _st in agents]),
        combat=types.SimpleNamespace(get_agent_stats=lambda _bm, i: stats[i]),
        _cr_by_name={"Goblin": "1/4", "Bugbear": "1"},
        _xp_awarded_agents=set(),
        party_xp_baseline=None,
        party_xp_earned=0,
        _combat_log_add=log.append,
        _modal_message=modals.append,
    )
    return app, log, modals


app, log, modals = _fake_app([
    _agent("Fighter", PC_FACTION, 20, level=1),
    _agent("Wizard", PC_FACTION, 8, level=1),
    _agent("Cleric", PC_FACTION, 0, level=1, dead=True),     # dead PC still a member
    _agent("Rogue", PC_FACTION, 10, level=1),
    _agent("Wolf", PC_FACTION, 11, npc=True),                # summon: not a member
    _agent("Goblin", ENEMY, 0),
    _agent("Goblin 2", ENEMY, 0, dead=True),
    _agent("Bugbear", ENEMY, 0),
    _agent("Goblin 3", ENEMY, 7),                            # still up: no XP
])
check(app_initiative.party_member_indices(app) == [0, 1, 2, 3], "party is the 4 PCs")
app_initiative.award_encounter_xp(app)
# 50 + 50 + 200 = 300 total, /4 = 75 each.
check(app.party_xp_earned == 75, f"earned per PC = {app.party_xp_earned}")
check(app_initiative.party_xp_total(app) == 75, "total = baseline 0 + 75")
check(log and "300" in log[0] and "÷ 4 PCs = 75 each" in log[0], f"log line: {log}")
check(not modals, "75 XP at level 1 is no level-up")

# Re-running the tally does not award the same corpses again.
app_initiative.award_encounter_xp(app)
check(app.party_xp_earned == 75, "corpses award once")

# Level-up fires off the per-PC share, not the encounter total.
app, log, modals = _fake_app([
    _agent("Fighter", PC_FACTION, 20, level=1),
    _agent("Wizard", PC_FACTION, 8, level=1),
    _agent("Bugbear", ENEMY, 0),
    _agent("Bugbear 2", ENEMY, 0),
    _agent("Goblin", ENEMY, 0),
])
app_initiative.award_encounter_xp(app)                      # 450 / 2 = 225 < 300
check(app.party_xp_earned == 225 and not modals, f"225 each, no level: {app.party_xp_earned}")
app.bm.placed_agents.append(_agent("Bugbear 3", ENEMY, 0)[0])
app.combat = types.SimpleNamespace(get_agent_stats=lambda _bm, i: (
    [types.SimpleNamespace(hp_cur=20, char_level=1, is_npc=False)] * 2
    + [types.SimpleNamespace(hp_cur=0, char_level=1, is_npc=False)] * 4)[i])
app_initiative.award_encounter_xp(app)                      # +200 / 2 = 100 → 325
check(app.party_xp_earned == 325, f"325 each: {app.party_xp_earned}")
check(len(modals) == 1, "crossing 300 per PC announces level 2")

if failures:
    print(f"test_xp_split: {failures} failure(s)")
    sys.exit(1)
print("test_xp_split: all passed")
