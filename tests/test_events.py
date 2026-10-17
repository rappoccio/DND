#!/usr/bin/env python3
"""``EventStream`` — the per-viewer event projection (MULTIPLAYER_PLAN.md M4b.1, seam S3).

The same discipline as ``test_gameview.py``: the headline checks serialize what a player
would be sent and search the bytes, because a client that cheats reads its own traffic.

Two halves:
  · the stream and the filter with a hand-built ``Sight`` — no ``App``, no extension use,
    so each B-4 rule is pinned in isolation;
  · the same scene ``test_gameview.py`` uses, where ``net.view.sight`` must agree with
    ``build_view`` and the App's two sources (the NPC drain and ``_spawn_flash``) append
    exactly once.

The B-10 mutants this slice owns, and the check that kills each:
  · a global index leaking into ``seq``          test_seq_is_gapless_per_principal
  · a hidden agent's ``move`` / ``announce`` sent  test_hidden_agent_events_absent_from_bytes,
                                                  test_announce_needs_actor_and_target
  · a path left uncut through unexplored cells    test_move_path_cut_to_explored_suffix
  · an enemy's ``hp_after`` sent as an integer    test_enemy_hp_after_is_a_band
  · a flash appended twice for an NPC outcome     test_npc_outcome_flash_is_not_appended_again
  · a gap after a dropped send (the cursor half)  test_unacked_send_is_resent
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import json
import shutil
import tempfile
from types import SimpleNamespace

import rpg_battle_map as rpg

from net import events as ev
from net.events import EventStream, Resync, Sight
from net.roster import DM_PRINCIPAL_ID
from net.view import build_view, sight

import test_gameview as gv
from test_helpers import create_melee_weapon

KIRA = "p_kira"


def _move(agent, *cells):
    return {"kind": ev.MOVE, "agent": agent, "path": list(cells)}


def _announce(agent, target, text="X attacks Y!"):
    return {"kind": ev.ANNOUNCE, "agent": agent, "target": target, "text": text}


def _seqs(frame):
    return [e["seq"] for e in frame["events"]]


# ─────────────────────────────────────────────────────────────────────────────
#  The stream and the projection
# ─────────────────────────────────────────────────────────────────────────────

def test_seq_is_gapless_per_principal():
    """Dropped events leave no hole, and the global position never reaches the wire.

    The stream is primed and trimmed first, so global positions are well past the
    projection's own numbering: a mutant that numbers by global position sends 4, 6, 8.
    """
    s = EventStream()
    for _ in range(3):
        s.append(_move(1, (0, 0)))           # nobody projects these: trimmed away
    assert len(s) == 0, "a stream nobody projects must hold nothing"

    dm, kira = s.projection("dm"), s.projection(KIRA)
    for i in range(6):
        s.append(_move(1 if i % 2 else 2, (i, 0)))   # agent 2 is hidden from Kira
    s.project("dm", Sight(shown=frozenset({1, 2})))
    s.project(KIRA, Sight(shown=frozenset({1})))

    assert dm.seq == 6 and kira.seq == 3
    assert _seqs(dm.frame(0)) == [1, 2, 3, 4, 5, 6]
    kf = kira.frame(0)
    assert _seqs(kf) == [1, 2, 3], f"Kira's seq has holes: {_seqs(kf)}"
    assert kf["since"] == 0 and kf["seq"] == 3
    assert kf["v"] == 1 and kf["t"] == "events"
    assert len(s) == 0, "every projection has filtered everything: the global list is empty"
    print("✅ test_seq_is_gapless_per_principal")


def test_new_principal_starts_at_the_head():
    """A principal opened late starts from a view, so the past is not replayed to it."""
    s = EventStream()
    s.projection("dm")
    s.append(_move(1, (0, 0)))
    late = s.project(KIRA, Sight(shown=frozenset({1})))
    assert late.seq == 0 and late.frame(0) is None
    s.append(_move(1, (1, 0)))
    s.project(KIRA, Sight(shown=frozenset({1})))
    assert _seqs(late.frame(0)) == [1]
    print("✅ test_new_principal_starts_at_the_head")


def test_sight_is_built_only_when_needed():
    s = EventStream()
    calls = []

    def build():
        calls.append(1)
        return Sight(shown=frozenset({1}))
    s.project(KIRA, build)
    assert calls == [], "nothing new: no board walk"
    s.append(_move(1, (0, 0)))
    s.project(KIRA, build)
    s.project(KIRA, build)
    assert calls == [1]
    print("✅ test_sight_is_built_only_when_needed")


def test_ring_and_since():
    """512 events per principal; anything older, or ahead, is a resync."""
    s = EventStream()
    p = s.projection(KIRA)
    for i in range(600):
        s.append(_move(1, (i, 0)))
    s.project(KIRA, Sight(shown=frozenset({1})))
    assert p.seq == 600
    assert len(p.since(600 - ev.RING_SIZE)) == ev.RING_SIZE
    assert p.since(600) == []
    assert _seqs({"events": p.since(590)}) == list(range(591, 601))
    for bad in (600 - ev.RING_SIZE - 1, 0, 601, -1):
        try:
            p.since(bad)
        except Resync:
            continue
        raise AssertionError(f"since={bad} should be a resync")
    assert p.frame(600) is None
    print("✅ test_ring_and_since")


def test_unacked_send_is_resent():
    """B-3's cursor half: only an ack advances a socket, so a dropped send costs nothing."""
    s = EventStream()
    p = s.projection(KIRA)
    s.append(_move(1, (0, 0)))
    s.project(KIRA, Sight(shown=frozenset({1})))
    assert p.attach("sock-a") == 1, "a new socket starts at the cursor its view carries"
    assert p.socket_frame("sock-a") is None

    s.append(_move(1, (1, 0)))
    s.project(KIRA, Sight(shown=frozenset({1})))
    first = p.socket_frame("sock-a")
    assert first["since"] == 1 and _seqs(first) == [2]
    # The send is dropped (no ack). More happens; the next frame still starts at 1.
    s.append(_move(1, (2, 0)))
    s.project(KIRA, Sight(shown=frozenset({1})))
    again = p.socket_frame("sock-a")
    assert again["since"] == 1 and _seqs(again) == [2, 3], "a dropped send left a gap"

    p.ack("sock-a", 3)
    assert p.sent("sock-a") == 3 and p.socket_frame("sock-a") is None
    p.ack("sock-a", 1)
    assert p.sent("sock-a") == 3, "a cursor never moves backwards"
    p.ack("sock-a", 99)
    assert p.sent("sock-a") == 3, "nor past the stream"

    p.attach("sock-b")                    # a second socket, same principal
    assert p.sent("sock-b") == 3
    p.detach("sock-a")
    assert p.sent("sock-a") is None and p.socket_frame("sock-a") is None
    p.ack("sock-a", 3)
    assert p.sent("sock-a") is None, "ack does not re-attach"
    print("✅ test_unacked_send_is_resent")


def test_forget_releases_the_global_list():
    s = EventStream()
    s.projection("dm")
    s.projection(KIRA)
    s.append(_move(1, (0, 0)))
    s.project("dm", Sight(shown=frozenset({1})))
    assert len(s) == 1, "Kira has not filtered it yet"
    s.forget(KIRA)
    assert len(s) == 0
    print("✅ test_forget_releases_the_global_list")


def test_unknown_kinds_are_refused():
    s = EventStream()
    for bad in ({"kind": "log", "text": "x"}, {"kind": 0}):
        try:
            s.append(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} was accepted")
    try:
        ev.from_npc(SimpleNamespace(kind=3))
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown C++ kind was guessed at")
    print("✅ test_unknown_kinds_are_refused")


# ─────────────────────────────────────────────────────────────────────────────
#  The filter (B-4)
# ─────────────────────────────────────────────────────────────────────────────

# Agent 9 is an enemy of size 1, agent 3 a party token, agent 7 an enemy of size 2.
# Explored: the columns 0..4 of row 0, and (6, 1).
_EXPLORED = frozenset({(c, 0) for c in range(5)} | {(6, 1)})
_FOG = Sight(shown=frozenset({3, 7, 9}), hide_map=True, explored=_EXPLORED,
             party=frozenset({3}), sizes={3: 1, 7: 2, 9: 1},
             vitals=frozenset({3}), hp_max={7: 40, 9: 20})


def test_move_path_cut_to_explored_suffix():
    path = [(8, 0), (7, 0), (6, 0), (5, 0), (4, 0), (3, 0), (2, 0)]
    out = ev.visible(_move(9, *path), _FOG)
    assert out["path"] == [[4, 0], [3, 0], [2, 0]], out
    assert "[5, 0]" not in json.dumps(out), "the slide draws an unexplored corridor"

    # A hole in the middle: only the suffix after the last unexplored cell survives.
    holed = [(0, 0), (1, 0), (2, 1), (3, 0), (4, 0)]
    assert ev.visible(_move(9, *holed), _FOG)["path"] == [[3, 0], [4, 0]]

    # One seen cell left: a jump the client lands.
    assert ev.visible(_move(9, (6, 0), (5, 0), (4, 0)), _FOG)["path"] == [[4, 0]]

    # Destination unseen: dropped, even though the token is shown (a two-move turn).
    assert ev.visible(_move(9, (4, 0), (5, 0)), _FOG) is None

    # A party token is never cut; nor is anything when the map is not hidden.
    party = ev.visible(_move(3, (8, 0), (4, 0)), _FOG)
    assert party["path"] == [[8, 0], [4, 0]]
    dm = Sight(shown=frozenset({9}))
    assert ev.visible(_move(9, *path), dm)["path"] == [[c, r] for c, r in path]

    # Size 2: a footprint with any seen cell counts, as in `_agent_fogged`.
    big = ev.visible(_move(7, (8, 2), (7, 1), (5, 0)), _FOG)
    assert big["path"] == [[5, 0]], big                  # (7,1) covers (7..8, 1..2): unseen
    big2 = ev.visible(_move(7, (8, 2), (6, 0), (5, 0)), _FOG)
    assert big2["path"] == [[6, 0], [5, 0]], big2
    print("✅ test_move_path_cut_to_explored_suffix")


def test_announce_needs_actor_and_target():
    assert ev.visible(_announce(9, 3), _FOG)["target"] == 3
    assert ev.visible(_announce(9, None), _FOG)["target"] is None   # an area, or nobody
    assert ev.visible(_announce(4, 3), _FOG) is None, "a hidden actor announced"
    assert ev.visible(_announce(9, 4), _FOG) is None, "a hidden target announced"
    assert ev.visible(_move(4, (0, 0)), _FOG) is None, "a hidden agent's move sent"
    print("✅ test_announce_needs_actor_and_target")


def test_enemy_hp_after_is_a_band():
    hit = ev.outcome(9, "Hit (7)", good=True, hp_after=13, died=False)
    out = ev.visible(hit, _FOG)
    assert "hp_after" not in out and out["band"] == "Healthy", out
    assert "13" not in json.dumps(out), "an enemy's HP reached the wire as a number"
    assert out["text"] == "Hit (7)", "flash text goes word for word"
    assert ev.visible(ev.outcome(9, "Hit (4)", good=True, hp_after=9), _FOG)["band"] == "Bloodied"
    died = ev.visible(ev.outcome(9, "Hit (9)", good=True, hp_after=0, died=True), _FOG)
    assert died["band"] == "Down" and died["died"] is True

    mine = ev.visible(ev.outcome(3, "Hit (5)", good=False, hp_after=17), _FOG)
    assert mine["hp_after"] == 17 and "band" not in mine

    # A GUI flash (-1): no timed drop, so neither field, for anyone.
    for who in (3, 9):
        flash = ev.visible(ev.outcome(who, "Miss", good=False), _FOG)
        assert "hp_after" not in flash and "band" not in flash, flash

    crit = ev.visible(ev.outcome(9, "Hit (20)", good=True, crit=True), _FOG)
    assert crit["crit"] is True
    assert "crit" not in ev.visible(ev.outcome(9, "Miss", good=False), _FOG)
    assert ev.visible(ev.outcome(4, "Hit (3)", good=True, hp_after=1), _FOG) is None
    print("✅ test_enemy_hp_after_is_a_band")


def test_turn_names_only_a_shown_agent():
    assert ev.visible(ev.turn(4, 2, 9), _FOG)["agent"] == 9
    hidden = ev.visible(ev.turn(4, 3, 4), _FOG)
    assert hidden == {"kind": "turn", "round": 4, "turn_idx": 3, "agent": None}
    assert ev.visible(ev.turn(0, 0, None), _FOG)["agent"] is None
    print("✅ test_turn_names_only_a_shown_agent")


def test_from_npc_field_for_field():
    cell = lambda c, r: SimpleNamespace(col=c, row=r)
    K = rpg.NpcVisualEvent.Kind
    kind = lambda n: int(getattr(K, n))
    mv = ev.from_npc(SimpleNamespace(kind=kind("Move"), agent_idx=2, target_idx=-1,
                                     path=[cell(1, 1), cell(2, 1)], text="", good=False,
                                     hp_after=-1, died=False))
    assert mv == {"kind": "move", "agent": 2, "path": [(1, 1), (2, 1)]}
    an = ev.from_npc(SimpleNamespace(kind=kind("Announce"), agent_idx=2, target_idx=-1,
                                     path=[], text="Fireball!", good=False, hp_after=-1,
                                     died=False))
    assert an == {"kind": "announce", "agent": 2, "target": None, "text": "Fireball!"}
    oc = ev.from_npc(SimpleNamespace(kind=kind("Outcome"), agent_idx=5, target_idx=-1,
                                     path=[], text="Hit (7)", good=True, hp_after=4,
                                     died=False))
    assert oc == {"kind": "outcome", "agent": 5, "text": "Hit (7)", "good": True,
                  "hp_after": 4, "died": False}
    # The table `from_npc` reads, pinned against the binding's enum: the whole enum, so a
    # member added in C++ fails here rather than as "unknown kind" in a live session.
    table = {int(v): k.lower() for k, v in K.__members__.items()}
    assert table == ev._NPC_KINDS, (table, ev._NPC_KINDS)
    print("✅ test_from_npc_field_for_field")


# ─────────────────────────────────────────────────────────────────────────────
#  Against a live App (the test_gameview scene)
# ─────────────────────────────────────────────────────────────────────────────

def test_sight_agrees_with_build_view():
    """``sight`` and ``build_view`` share their gates: same agents, same HP tiers, under
    fog, under concealment and for the DM."""
    def check(app, kira, _spectator):
        dm = app.roster.get(DM_PRINCIPAL_ID)

        def agree():
            for who in (kira, dm):
                view, s = build_view(app, who), sight(app, who)
                shown = {a["agent"] for a in view["agents"]}
                assert s.shown == shown, (who.id, s.shown, shown)
                assert s.vitals == {a["agent"] for a in view["agents"] if "cur" in a["hp"]}
        agree()
        assert gv._idx(app, "Skarn") not in sight(app, kira).shown
        assert sight(app, kira).hide_map and not sight(app, dm).hide_map

        g = gv._idx(app, "Gnasher")
        app.bm.set_agent_npc_automated(g, True)
        cond = app.combat.get_agent_conditions(app.bm, g)
        cond.hidden = True
        app.combat.set_agent_conditions(app.bm, g, cond)
        agree()
        assert g not in sight(app, kira).shown, "a concealed ambusher in the filter's sight"
    gv._run(check)
    print("✅ test_sight_agrees_with_build_view")


def test_hidden_agent_events_absent_from_bytes():
    """The headline check: a turn by the creature in the fog crosses as nothing at all.

    Skarn walks, announces, and is struck, all in unexplored space. Kira's projection of it
    is empty, and its bytes carry neither the name nor a cell. The DM gets every event.
    """
    def check(app, kira, _spectator):
        s = app.events
        skarn, aria = gv._idx(app, "Skarn"), gv._idx(app, "Aria")
        s.projection(kira.id)
        s.projection(DM_PRINCIPAL_ID)
        s.append(_move(skarn, (10, 9), (9, 9)))
        s.append(_announce(skarn, None, "Skarn breathes fire!"))
        s.append(ev.outcome(skarn, "Hit (11)", good=True, hp_after=4271, died=False))
        s.append(_announce(aria, skarn, "Aria attacks Skarn!"))
        s.append(ev.outcome(aria, "Hit (3)", good=False, hp_after=12, died=False))

        mine = s.project(kira.id, lambda: sight(app, kira))
        blob = json.dumps(mine.since(0))
        assert "Skarn" not in blob and "[9, 9]" not in blob and "4271" not in blob, blob
        assert _seqs({"events": mine.since(0)}) == [1], "only Aria's own outcome survives"
        assert mine.since(0)[0]["hp_after"] == 12, "a party token's HP is table information"

        dms = s.project(DM_PRINCIPAL_ID, lambda: sight(app, app.roster.get(DM_PRINCIPAL_ID)))
        assert dms.seq == 5
        assert "4271" in json.dumps(dms.since(0)), "the DM reads numbers"
    gv._run(check)
    print("✅ test_hidden_agent_events_absent_from_bytes")


def test_spawn_flash_appends_one_outcome():
    def check(app, kira, _spectator):
        from constants import FLASH_BAD, FLASH_CRIT, FLASH_GOOD
        g = gv._idx(app, "Gnasher")
        app.events.projection(kira.id)
        app._spawn_flash(g, "Hit (7)", FLASH_GOOD)
        app._spawn_flash(g, "Hit (19)", FLASH_CRIT)
        app._spawn_flash(g, "Miss", FLASH_BAD)
        app._spawn_flash(-1, "Miss", FLASH_BAD)          # no anchor: no flash, no event
        out = app.events.project(kira.id, lambda: sight(app, kira)).since(0)
        assert [(e["text"], e["good"], e.get("crit", False)) for e in out] == \
            [("Hit (7)", True, False), ("Hit (19)", True, True), ("Miss", False, False)], out
        assert all("hp_after" not in e and "band" not in e for e in out)
    gv._run(check)
    print("✅ test_spawn_flash_appends_one_outcome")


def test_npc_outcome_flash_is_not_appended_again():
    """Playback flashes an NPC outcome on the DM screen; the stream already has it."""
    def check(app, _kira, _spectator):
        g = gv._idx(app, "Gnasher")
        app.events.projection(DM_PRINCIPAL_ID)
        app._npc_anim = {"hp": {}}
        npc_ev = SimpleNamespace(agent_idx=g, text="Hit (7)", good=True, hp_after=4,
                                 died=False)
        app._npc_anim_apply_outcome(npc_ev)
        assert len(app.events) == 0, "an NPC outcome was appended a second time"
        assert app._floating_texts and app._floating_texts[-1]["text"] == "Hit (7)", \
            "the DM screen still flashes it"
        assert app._npc_anim["hp"][g] == 4
        app._npc_anim = None
    gv._run(check)
    print("✅ test_npc_outcome_flash_is_not_appended_again")


def test_npc_turn_reaches_the_stream():
    """``_drive_npc_turn_if_pending`` drains the engine buffer into the stream, in the
    order the DM screen plays it."""
    def check(app, _kira, _spectator):
        g, b = gv._idx(app, "Gnasher"), gv._idx(app, "Brannor")
        app._start_combat()
        app.combat.stop_recording()
        app.combat.set_agent_weapons(app.bm, g, [create_melee_weapon(), rpg.Weapon(),
                                                 rpg.Weapon()])
        app.bm.set_agent_npc_automated(g, True)
        app.combat.begin_turn(app.bm, g)
        app.events.projection(DM_PRINCIPAL_ID)
        app._npc_drive_idx = g
        app._drive_npc_turn_if_pending()

        assert app._npc_anim is not None, "the turn recorded nothing to play"
        played = app._npc_anim["events"]
        dm = app.roster.get(DM_PRINCIPAL_ID)
        got = app.events.project(DM_PRINCIPAL_ID, lambda: sight(app, dm)).since(0)
        assert [e["kind"] for e in got] == [ev.from_npc(e)["kind"] for e in played], got
        assert any(e["kind"] == "outcome" and e["agent"] == b for e in got), got

        app._npc_anim_fast_forward()            # plays the outcomes: no second copy
        assert len(app.events) == 0
        assert app.events.project(DM_PRINCIPAL_ID, lambda: sight(app, dm)).seq == len(got)
    gv._run(check)
    print("✅ test_npc_turn_reaches_the_stream")


if __name__ == "__main__":
    test_seq_is_gapless_per_principal()
    test_new_principal_starts_at_the_head()
    test_sight_is_built_only_when_needed()
    test_ring_and_since()
    test_unacked_send_is_resent()
    test_forget_releases_the_global_list()
    test_unknown_kinds_are_refused()
    test_move_path_cut_to_explored_suffix()
    test_announce_needs_actor_and_target()
    test_enemy_hp_after_is_a_band()
    test_turn_names_only_a_shown_agent()
    test_from_npc_field_for_field()
    test_sight_agrees_with_build_view()
    test_hidden_agent_events_absent_from_bytes()
    test_spawn_flash_appends_one_outcome()
    test_npc_outcome_flash_is_not_appended_again()
    test_npc_turn_reaches_the_stream()
    print("\nAll EventStream tests passed! 🎉")
