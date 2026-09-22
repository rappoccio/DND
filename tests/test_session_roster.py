#!/usr/bin/env python3
"""Session roster + token ownership (MULTIPLAYER_PLAN.md M0).

M0 is the phase that cannot be retrofitted cheaply: it lands ownership in a persisted
file format, and every later phase's authorization check reads what it writes. These
tests are the acceptance criteria named in the plan's M0 section.

Two halves, because M0 has two halves:

  · the roster itself — principals, credentials, `authorize()` — which is pure Python
    and needs neither pygame nor the C++ extension;
  · the ownership round-trip through a real `App`, which is what proves `controller`
    survives a save that renumbers the agent list.

Covered here:
  · a session file round-trips, and credentials/seat lists are NEVER on disk
                                                  (test_session_file_round_trip)
  · autosave_slots is clamped to NN7's 1–5 range  (test_autosave_slots_clamped)
  · credentials verify, expire, and die with the signing key
                                                  (test_credential_lifecycle)
  · a revoked credential is refused               (test_revoked_credential_refused)
  · the policy table, row by row                  (test_authorize_policy_table)
  · a principal with no seat is denied everything (test_unseated_principal_denied)
  · ownership is derived from `controller`, never stored twice
                                                  (test_ownership_is_derived)
  · a controller naming an unknown principal loads as DM-controlled
                                                  (test_unknown_controller_loads_as_dm)
  · `controller` round-trips present and absent through the encounter save
                                                  (test_controller_round_trip)
  · ownership survives a save that compacts indices
                                                  (test_ownership_survives_compaction)
  · a summon inherits its summoner's controller   (test_summon_inherits_controller)
"""

import os
import sys

# Headless SDL: set before pygame is imported anywhere (main.py imports it at module
# scope), same pair as test_combat_panel.py.
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import json
import shutil
import tempfile

import rpg_battle_map as rpg

from net.roster import (SessionRoster, Principal, Role, AuthBlock, Action,
                        TokenTarget, PromptTarget, TokenInfo,
                        DM_PRINCIPAL_ID, PC_FACTION, DEFAULT_AUTOSAVE_SLOTS)
from main import App

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20260921
FOE_FACTION = 1


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _seat(roster, name):
    return roster.add_principal(name, role=Role.PLAYER)


def _tokens(*specs):
    """specs: (agent_idx, controller, faction) triples."""
    return [TokenInfo(agent_idx=i, controller=c, faction=f) for i, c, f in specs]


def _place(app, name, col, row):
    cfg = rpg.AgentConfig()
    cfg.name = name
    cfg.start_col = col
    cfg.start_row = row
    cfg.size = 1
    cfg.sprite_path = ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)


def _idx(app, name):
    for i, pt in enumerate(app.bm.placed_agents):
        if pt.name == name:
            return i
    raise KeyError(name)


def _app_in(tmpdir, names=("Aria", "Brannor", "Skarn")):
    """An App on the test map with its encounter base re-pointed into `tmpdir`, so the
    save/load tests never write next to the real maps."""
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmpdir, "roster_test_agents.json"))
    for i, nm in enumerate(names):
        _place(app, nm, 2 + i * 2, 3)
    app.combat.apply_agent_configs(app.bm)
    app._sync_roster_tokens()
    return app


# ─────────────────────────────────────────────────────────────────────────────
#  The roster, standalone
# ─────────────────────────────────────────────────────────────────────────────

def test_session_file_round_trip():
    tmp = tempfile.mkdtemp()
    try:
        path = os.path.join(tmp, "table_session.json")
        r = SessionRoster()
        kira = _seat(r, "Kira")
        cred = r.mint_credential(kira.id)
        r.save(path)

        raw = json.load(open(path))
        assert raw["protocol_version"] == 1, raw
        # A1: ownership is NOT stored here. A3/A5: neither is any credential material.
        assert "seats" not in raw, "session file must not carry a seat list (A1)"
        assert "signing_key" not in raw, "the signing key is never persisted (A5)"
        blob = json.dumps(raw)
        assert cred not in blob and cred.split(".")[-1] not in blob, \
            "a credential must never reach disk (A3)"

        back = SessionRoster.load(path)
        assert [p.id for p in back.principals] == [p.id for p in r.principals]
        seated = back.get(kira.id)
        assert seated is not None and seated.display_name == "Kira"
        assert seated.role is Role.PLAYER
        # A4: the auth block exists from day one, with v1's only method.
        assert seated.auth.method == "join_code" and seated.auth.subject is None
        assert back.join_code == r.join_code
        # A3: credentials are session-scoped — a new process cannot verify the old one.
        assert back.verify_credential(cred) is None, \
            "a credential must not survive the process that minted it"
        print("✅ test_session_file_round_trip passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_autosave_slots_clamped():
    # NN7: the ring is 1–5 slots, default 3.
    assert SessionRoster().autosave_slots == DEFAULT_AUTOSAVE_SLOTS
    assert SessionRoster(autosave_slots=0).autosave_slots == 1
    assert SessionRoster(autosave_slots=99).autosave_slots == 5
    assert SessionRoster.from_dict({"autosave_slots": 4}).autosave_slots == 4
    print("✅ test_autosave_slots_clamped passed")


def test_credential_lifecycle():
    r = SessionRoster()
    kira = _seat(r, "Kira")
    cred = r.mint_credential(kira.id)
    assert r.verify_credential(cred) == kira

    # Tampering with any field breaks the signature.
    kid, pid, exp, sig = cred.split(".")
    forged = f"{kid}.{DM_PRINCIPAL_ID}.{exp}.{sig}"
    assert r.verify_credential(forged) is None, "a re-pointed credential must not verify"
    assert r.verify_credential(f"{kid}.{pid}.{exp}.{sig}x") is None
    assert r.verify_credential("") is None and r.verify_credential("garbage") is None

    # exp is honored even though the lifetime is session-scoped (A4 keeps the field real).
    short = r.mint_credential(kira.id, ttl_seconds=1)
    assert r.verify_credential(short, now=0) is not None
    assert r.verify_credential(short, now=2**40) is None, "an expired credential must fail"

    # A credential for an unseated principal cannot even be minted.
    assert r.mint_credential("p_nobody") is None

    # A5's panic button: a new signing key invalidates everything outstanding.
    r.revoke_all()
    assert r.verify_credential(cred) is None
    print("✅ test_credential_lifecycle passed")


def test_revoked_credential_refused():
    r = SessionRoster()
    kira = _seat(r, "Kira")
    cred = r.mint_credential(kira.id)
    other = r.mint_credential(kira.id)
    assert r.verify_credential(cred) == kira

    r.revoke_credential(cred)
    assert r.verify_credential(cred) is None, "a revoked credential must be refused"
    # Revocation is per-kid, so the same principal's other credential still works —
    # that is the whole reason a credential carries a key id.
    assert r.verify_credential(other) == kira

    # Unseating the principal refuses every credential they hold, signature or not.
    r.remove_principal(kira.id)
    assert r.verify_credential(other) is None
    print("✅ test_revoked_credential_refused passed")


def test_authorize_policy_table():
    r = SessionRoster()
    dm = r.get(DM_PRINCIPAL_ID)
    kira = _seat(r, "Kira")
    thom = _seat(r, "Thom")
    # 0: Kira's PC. 1: Thom's PC. 2: an unowned PC. 3: a monster.
    r.sync_tokens(_tokens((0, kira.id, PC_FACTION),
                          (1, thom.id, PC_FACTION),
                          (2, DM_PRINCIPAL_ID, PC_FACTION),
                          (3, DM_PRINCIPAL_ID, FOE_FACTION)))

    A = Action
    # VIEW_SESSION: anyone seated, spectators included.
    assert r.authorize(dm, A.VIEW_SESSION)
    assert r.authorize(kira, A.VIEW_SESSION)
    assert not r.authorize(None, A.VIEW_SESSION), "the unauthenticated caller is denied"

    # VIEW_TOKEN_VITALS: owned, or any PC-faction token; never a monster.
    assert r.authorize(kira, A.VIEW_TOKEN_VITALS, TokenTarget(0))
    assert r.authorize(kira, A.VIEW_TOKEN_VITALS, TokenTarget(1)), "party vitals are table info"
    assert r.authorize(kira, A.VIEW_TOKEN_VITALS, TokenTarget(2))
    assert not r.authorize(kira, A.VIEW_TOKEN_VITALS, TokenTarget(3))
    assert r.authorize(dm, A.VIEW_TOKEN_VITALS, TokenTarget(3))

    # VIEW_TOKEN_SHEET: owned only.
    assert r.authorize(kira, A.VIEW_TOKEN_SHEET, TokenTarget(0))
    assert not r.authorize(kira, A.VIEW_TOKEN_SHEET, TokenTarget(1))
    assert not r.authorize(kira, A.VIEW_TOKEN_SHEET, TokenTarget(3))
    assert r.authorize(dm, A.VIEW_TOKEN_SHEET, TokenTarget(3))

    # DM-only rows.
    assert r.authorize(dm, A.VIEW_DM_CHANNEL) and r.authorize(dm, A.DM_COMMAND)
    assert not r.authorize(kira, A.VIEW_DM_CHANNEL)
    assert not r.authorize(kira, A.DM_COMMAND)

    # CONTROL_TOKEN: owned for a player; ALWAYS for the DM (NN4 — no handoff step).
    assert r.authorize(kira, A.CONTROL_TOKEN, TokenTarget(0))
    assert not r.authorize(kira, A.CONTROL_TOKEN, TokenTarget(1))
    assert r.authorize(dm, A.CONTROL_TOKEN, TokenTarget(0)), "NN4: the DM acts for any token"

    # A missing or wrong-typed target denies rather than falling through permissively.
    assert not r.authorize(kira, A.CONTROL_TOKEN, None)
    assert not r.authorize(kira, A.VIEW_TOKEN_SHEET, PromptTarget("pr_1"))

    # ANSWER_PROMPT: the bus (M1) answers owner + liveness through the lookup hook.
    live = {"pr_kira": (kira.id, True), "pr_stale": (kira.id, False)}
    assert not r.authorize(kira, A.ANSWER_PROMPT, PromptTarget("pr_kira")), \
        "with no prompt bus installed, a player has no live prompt to answer"
    assert r.authorize(dm, A.ANSWER_PROMPT, PromptTarget("pr_kira")), "NN4 holds regardless"
    r.prompt_lookup = lambda pid: live.get(pid, (None, False))
    assert r.authorize(kira, A.ANSWER_PROMPT, PromptTarget("pr_kira"))
    assert not r.authorize(kira, A.ANSWER_PROMPT, PromptTarget("pr_stale")), \
        "a prompt that is no longer live is refused (NN4's liveness check)"
    assert not r.authorize(thom, A.ANSWER_PROMPT, PromptTarget("pr_kira")), \
        "a player may not answer another player's prompt"
    print("✅ test_authorize_policy_table passed")


def test_unseated_principal_denied():
    r = SessionRoster()
    kira = _seat(r, "Kira")
    r.sync_tokens(_tokens((0, kira.id, PC_FACTION)))
    assert r.authorize(kira, Action.CONTROL_TOKEN, TokenTarget(0))

    # A principal who holds no seat at this table is denied every action, including the
    # bare "may I connect at all" read.
    ghost = Principal(id="p_ghost", display_name="Ghost", role=Role.PLAYER, auth=AuthBlock())
    for action, target in ((Action.VIEW_SESSION, None),
                           (Action.VIEW_TOKEN_VITALS, TokenTarget(0)),
                           (Action.VIEW_TOKEN_SHEET, TokenTarget(0)),
                           (Action.VIEW_DM_CHANNEL, None),
                           (Action.CONTROL_TOKEN, TokenTarget(0)),
                           (Action.ANSWER_PROMPT, PromptTarget("pr_1")),
                           (Action.DM_COMMAND, None)):
        assert not r.authorize(ghost, action, target), f"{action} must be denied off-roster"

    # A forged record claiming DM is not a DM: the roster's own copy is the truth (A8).
    fake_dm = Principal(id=kira.id, display_name="Kira", role=Role.DM, auth=AuthBlock())
    assert not r.authorize(fake_dm, Action.DM_COMMAND), \
        "role must come from the roster, never from the caller's record"

    # Unseating mid-session revokes the seat's authority immediately.
    r.remove_principal(kira.id)
    assert not r.authorize(kira, Action.CONTROL_TOKEN, TokenTarget(0))
    print("✅ test_unseated_principal_denied passed")


def test_ownership_is_derived():
    r = SessionRoster()
    kira = _seat(r, "Kira")
    thom = _seat(r, "Thom")
    r.sync_tokens(_tokens((0, kira.id, PC_FACTION),
                          (1, kira.id, PC_FACTION),
                          (2, thom.id, PC_FACTION),
                          (3, DM_PRINCIPAL_ID, FOE_FACTION)))
    assert r.controlled_by(kira.id) == [0, 1]
    assert r.controlled_by(thom.id) == [2]
    assert r.controlled_by(DM_PRINCIPAL_ID) == [3]
    # A player owning zero tokens is a spectator, not an error.
    spec = _seat(r, "Spectator")
    assert r.controlled_by(spec.id) == []
    assert r.authorize(spec, Action.VIEW_SESSION)

    # The cache is a cache: re-syncing with new records is the only way it changes, and
    # it never writes ownership back anywhere.
    r.sync_tokens(_tokens((0, thom.id, PC_FACTION)))
    assert r.controlled_by(kira.id) == [] and r.controlled_by(thom.id) == [0]
    assert "seats" not in r.to_dict()
    print("✅ test_ownership_is_derived passed")


def test_unknown_controller_loads_as_dm():
    # A1: a controller naming a principal with no seat loads as DM-controlled — harmless
    # — rather than silently handing a real person the wrong creature.
    r = SessionRoster()
    kira = _seat(r, "Kira")
    r.sync_tokens(_tokens((0, "p_whoever", PC_FACTION),
                          (1, kira.id, PC_FACTION)))
    assert r.controller_of(0) == DM_PRINCIPAL_ID
    assert r.controlled_by(DM_PRINCIPAL_ID) == [0]
    assert not r.authorize(kira, Action.CONTROL_TOKEN, TokenTarget(0))
    assert r.authorize(r.get(DM_PRINCIPAL_ID), Action.CONTROL_TOKEN, TokenTarget(0))

    # And the id is kept, not erased: re-seating that principal restores the link, which
    # is what makes "the DM restarted the app" a seat claim rather than a re-invite.
    restored = Principal(id="p_whoever", display_name="Wanderer",
                         role=Role.PLAYER, auth=AuthBlock())
    r._principals[restored.id] = restored
    r.sync_tokens(_tokens((0, "p_whoever", PC_FACTION),
                          (1, kira.id, PC_FACTION)))
    assert r.controller_of(0) == "p_whoever"
    print("✅ test_unknown_controller_loads_as_dm passed")


# ─────────────────────────────────────────────────────────────────────────────
#  The ownership round-trip through a real encounter save
# ─────────────────────────────────────────────────────────────────────────────

def test_controller_round_trip():
    tmp = tempfile.mkdtemp()
    try:
        app = _app_in(tmp)
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)
        app.bm.set_agent_controller(_idx(app, "Aria"), kira.id)
        # Brannor is left at the default, which is the DM.
        assert app.bm.placed_agents[_idx(app, "Brannor")].controller == DM_PRINCIPAL_ID
        app._save_agents()

        doc = json.load(open(app._save_path))
        by_name = {a["name"]: a for a in doc["agents"]}
        assert by_name["Aria"]["controller"] == kira.id
        assert by_name["Brannor"]["controller"] == DM_PRINCIPAL_ID
        # The principal is in the session file, not the encounter file (A1's split).
        assert os.path.exists(app._session_path)
        assert "principals" not in doc

        # A save predating multiplayer has no `controller` key at all: it must load as
        # DM-controlled rather than raising or leaving the field unset.
        del by_name["Brannor"]["controller"]
        with open(app._save_path, "w") as f:
            json.dump(doc, f)

        app2 = App(MAP_PATH, seed=SEED)
        app2._set_encounter_base(app._save_path)
        app2._load_agents()
        assert app2.bm.placed_agents[_idx(app2, "Aria")].controller == kira.id
        assert app2.bm.placed_agents[_idx(app2, "Brannor")].controller == DM_PRINCIPAL_ID
        # The roster came back with Kira's seat, so the reloaded link is live.
        assert app2.roster.get(kira.id) is not None
        assert app2.roster.controlled_by(kira.id) == [_idx(app2, "Aria")]
        print("✅ test_controller_round_trip passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_ownership_survives_compaction():
    """`_save_agents` drops summons and removed agents and renumbers what is left, so a
    save can shift every index. Ownership must land on the same CREATURES afterwards —
    the whole reason A1 keeps `controller` on the agent record instead of a seat list."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app_in(tmp)
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)
        thom = app.roster.add_principal("Thom", role=Role.PLAYER)
        aria, brannor, skarn = (_idx(app, n) for n in ("Aria", "Brannor", "Skarn"))
        app.bm.set_agent_controller(aria, kira.id)
        app.bm.set_agent_controller(skarn, thom.id)

        # Tombstone the agent sitting BETWEEN them: the save drops it, so everything
        # after it is renumbered on reload.
        app.bm.set_agent_removed_from_play(brannor, True)
        app._save_agents()

        app2 = App(MAP_PATH, seed=SEED)
        app2._set_encounter_base(app._save_path)
        app2._load_agents()
        names = [pt.name for pt in app2.bm.placed_agents]
        assert names == ["Aria", "Skarn"], f"expected the compacted pair, got {names}"
        assert app2.bm.placed_agents[_idx(app2, "Aria")].controller == kira.id
        assert app2.bm.placed_agents[_idx(app2, "Skarn")].controller == thom.id
        # Skarn's index moved from 2 to 1, and the derived cache followed it.
        assert skarn == 2 and _idx(app2, "Skarn") == 1
        assert app2.roster.controlled_by(thom.id) == [1]
        print("✅ test_ownership_survives_compaction passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_summon_inherits_controller():
    """A1: a summon inherits its summoner's controller at creation. Tagging the summon
    (`set_agent_summoner_idx`) is the one funnel every summon path goes through, so the
    inheritance cannot be forgotten at a call site."""
    tmp = tempfile.mkdtemp()
    try:
        app = _app_in(tmp)
        kira = app.roster.add_principal("Kira", role=Role.PLAYER)
        aria = _idx(app, "Aria")
        app.bm.set_agent_controller(aria, kira.id)

        cfg = rpg.AgentConfig()
        cfg.name, cfg.start_col, cfg.start_row, cfg.size = "Wolf", 6, 6, 1
        wolf = app.bm.spawn_agent(cfg)
        assert wolf >= 0, "spawn_agent refused the summon's cell"
        assert app.bm.placed_agents[wolf].controller == DM_PRINCIPAL_ID, \
            "a fresh token starts DM-controlled"
        app.bm.set_agent_summoner_idx(wolf, aria)
        assert app.bm.placed_agents[wolf].controller == kira.id, \
            "the summon must inherit its summoner's controller"

        app._sync_roster_tokens()
        assert app.roster.controlled_by(kira.id) == [aria, wolf]
        assert app.roster.authorize(app.roster.get(kira.id),
                                    Action.CONTROL_TOKEN, TokenTarget(wolf))

        # Summons are never persisted, so the inherited ownership is fight-scoped only.
        app._save_agents()
        doc = json.load(open(app._save_path))
        assert "Wolf" not in [a["name"] for a in doc["agents"]]
        print("✅ test_summon_inherits_controller passed")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    tests = [
        test_session_file_round_trip,
        test_autosave_slots_clamped,
        test_credential_lifecycle,
        test_revoked_credential_refused,
        test_authorize_policy_table,
        test_unseated_principal_denied,
        test_ownership_is_derived,
        test_unknown_controller_loads_as_dm,
        test_controller_round_trip,
        test_ownership_survives_compaction,
        test_summon_inherits_controller,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_session_roster: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_session_roster: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
