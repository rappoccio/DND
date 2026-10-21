#!/usr/bin/env python3
"""The token look and `GET /sprite?name=<basename>` (MULTIPLAYER_PLAN.md M4b.5, B-8).

The route serves token art to a viewer only for a basename some agent in **that viewer's**
view carries. Anything else is a 404, so the route cannot list the bestiary and cannot
hand a player the art of a creature still in the fog.

  · the lookup follows the view's gates, and never builds a path from the URL
                                                         (test_lookup_follows_the_view)
  · an unseated principal is refused outright           (test_lookup_refuses_the_unseated)
  · the route: 401 unauthenticated, the art for a carried name, 404 for the fogged one
    and for a file no agent wears, the DM served all   (test_the_route_serves_only_the_view)
  · If-None-Match on the served ETag is a 304           (test_conditional_request_is_304)
  · the copied colours are constants.py's               (test_constants_match_the_dm_screen)
  · the client draws `_draw_one_agent`'s token          (test_the_token_in_the_client)

Mutant owed by B-10, killed by the third check: `/sprite` serving a basename outside the
viewer's view.
"""

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.join(_ROOT, "tests"))

import ast
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

import rpg_battle_map as rpg

from main import App
from net import view as net_view
from net.roster import DM_PRINCIPAL_ID, PC_FACTION, Role
from net.server import PlayerServer

from test_gameview import EXPLORED, FOE_FACTION, MAP_PATH, SEED, _idx
from test_mapserver import _free_port

_APP_JS = os.path.join(_ROOT, "gui", "net", "static", "app.js")
_CONSTANTS = os.path.join(_ROOT, "gui", "constants.py")
_CHECKS = os.path.join(_ROOT, "tests", "token_checks.js")

# Three art files and one nobody wears. The bytes differ so a mix-up shows.
_ART = {"aria.png": b"\x89PNG aria", "gnasher.png": b"\x89PNG gnasher",
        "skarn.png": b"\x89PNG skarn", "bestiary.png": b"\x89PNG bestiary"}


def _scene(tmp):
    """Aria (party, seen, Kira's), Gnasher (foe, seen) and Skarn (foe, in the fog)."""
    for name, data in _ART.items():
        with open(os.path.join(tmp, name), "wb") as fh:
            fh.write(data)
    app = App(MAP_PATH, seed=SEED)
    app._set_encounter_base(os.path.join(tmp, "sprites_test_agents.json"))
    for name, col, row in (("Aria", 2, 3), ("Gnasher", 5, 3), ("Skarn", 9, 9)):
        cfg = rpg.AgentConfig()
        cfg.name = name
        cfg.start_col = col
        cfg.start_row = row
        cfg.size = 1
        cfg.sprite_path = os.path.join(tmp, f"{name.lower()}.png")
        app.combat.add_agent_config(app.bm, cfg)
        app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    app.bm.set_agent_faction(_idx(app, "Aria"), PC_FACTION)
    for name in ("Gnasher", "Skarn"):
        app.bm.set_agent_faction(_idx(app, name), FOE_FACTION)
    kira = app.roster.add_principal("Kira", role=Role.PLAYER)
    app.bm.set_agent_controller(_idx(app, "Aria"), kira.id)
    app._sync_roster_tokens()
    app._set_fog(True)
    app.bm.set_explored_cells([rpg.Cell(c, r) for c, r in EXPLORED])
    return app, kira


def _run(fn):
    tmp = tempfile.mkdtemp()
    try:
        fn(tmp, *_scene(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ─────────────────────────────────────────────────────────────────────────────
#  The lookup, on the frame tick
# ─────────────────────────────────────────────────────────────────────────────

def test_lookup_follows_the_view():
    def check(tmp, app, kira):
        dm = app.roster.get(DM_PRINCIPAL_ID)
        carried = {a["sprite"] for a in net_view.build_view(app, kira)["agents"]}
        assert carried == {"aria.png", "gnasher.png"}, carried

        for name in ("aria.png", "gnasher.png"):
            assert net_view.sprite_file(app, kira, name) == os.path.join(tmp, name)
        assert net_view.sprite_file(app, kira, "skarn.png") is None, \
            "a player was handed the art of a creature in the fog"
        assert net_view.sprite_file(app, dm, "skarn.png") == os.path.join(tmp, "skarn.png")
        for name in ("bestiary.png", "", "../aria.png", "ARIA.png"):
            assert net_view.sprite_file(app, kira, name) is None, name
            assert net_view.sprite_file(app, dm, name) is None, name
    _run(check)
    print("✅ test_lookup_follows_the_view")


def test_lookup_refuses_the_unseated():
    def check(tmp, app, kira):
        app.roster.remove_principal(kira.id)
        try:
            net_view.sprite_file(app, kira, "aria.png")
        except PermissionError:
            return
        raise AssertionError("an unseated principal was answered")
    _run(check)
    print("✅ test_lookup_refuses_the_unseated")


# ─────────────────────────────────────────────────────────────────────────────
#  The route, over a real socket
# ─────────────────────────────────────────────────────────────────────────────

class _server:
    """The scene, a server on loopback with `sprite_for` wired as `net.link` wires it, and
    a stand-in frame tick, because the lookup is a command only the pygame thread answers."""

    def __enter__(self):
        self.tmp = tempfile.mkdtemp()
        self.app, kira = _scene(self.tmp)
        self.srv = PlayerServer(self.app.roster, self.app.map_images,
                                self.app._net_commands, net_view.build_view,
                                sprite_for=net_view.sprite_file,
                                host="127.0.0.1", port=_free_port())
        self.srv.start()
        self.base = f"http://127.0.0.1:{self.srv.port}"
        self.player = self.app.roster.mint_credential(kira.id)
        self.dm = self.app.roster.mint_credential(DM_PRINCIPAL_ID)
        self._pumping = True
        self._ticker = threading.Thread(target=self._tick, daemon=True)
        self._ticker.start()
        return self

    def _tick(self):
        while self._pumping:
            self.app._net_commands.pump(self.app)
            time.sleep(0.002)

    def __exit__(self, *exc):
        self._pumping = False
        self._ticker.join(2.0)
        self.srv.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)
        return False

    def get(self, name, credential=None, inm=None):
        req = urllib.request.Request(f"{self.base}/sprite?name={name}")
        if credential is not None:
            req.add_header("Authorization", f"Bearer {credential}")
        if inm is not None:
            req.add_header("If-None-Match", inm)
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


def test_the_route_serves_only_the_view():
    with _server() as s:
        status, _, _ = s.get("aria.png")
        assert status == 401, status

        status, headers, body = s.get("aria.png", s.player)
        assert status == 200, status
        assert body == _ART["aria.png"]
        assert headers["Content-Type"] == "image/png"
        assert headers.get("ETag"), "no ETag on the art"

        status, _, body = s.get("gnasher.png", s.player)
        assert (status, body) == (200, _ART["gnasher.png"])

        for name in ("skarn.png", "bestiary.png", "nothing.png", "..%2Faria.png", "", "%2Ftmp%2Faria.png"):
            status, _, body = s.get(name, s.player)
            assert status == 404, f"{name}: {status}"
            assert body not in _ART.values(), name

        status, _, body = s.get("skarn.png", s.dm)
        assert (status, body) == (200, _ART["skarn.png"]), "the DM sees the whole board"
        status, _, _ = s.get("bestiary.png", s.dm)
        assert status == 404, "the DM was served a file no agent wears"
    print("✅ test_the_route_serves_only_the_view")


def test_conditional_request_is_304():
    with _server() as s:
        _, headers, _ = s.get("aria.png", s.player)
        etag = headers["ETag"]
        status, again, body = s.get("aria.png", s.player, inm=etag)
        assert (status, body) == (304, b""), status
        assert again["ETag"] == etag
        status, _, body = s.get("aria.png", s.player, inm='"stale"')
        assert (status, body) == (200, _ART["aria.png"])
        _, other, _ = s.get("gnasher.png", s.player)
        assert other["ETag"] != etag, "two pieces of art share a key"
    print("✅ test_conditional_request_is_304")


# ─────────────────────────────────────────────────────────────────────────────
#  The client
# ─────────────────────────────────────────────────────────────────────────────

def _python_constants() -> dict:
    tree = ast.parse(open(_CONSTANTS, encoding="utf-8").read())
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def _js_constant(js: str, name: str) -> str:
    m = re.search(rf"^const {name} = (.+?);", js, re.M)
    assert m, f"app.js has no top-level const {name}"
    return m.group(1).strip()


def _rgb_list(value) -> str:
    return "[" + ", ".join(str(int(c)) for c in value) + "]"


def test_constants_match_the_dm_screen():
    py = _python_constants()
    src = open(_CONSTANTS, encoding="utf-8").read()
    js = open(_APP_JS, encoding="utf-8").read()

    want = "{ " + ", ".join(f"{k}: {_rgb_list(v)}"
                            for k, v in sorted(py["FACTION_COLORS"].items())) + " }"
    assert _js_constant(js, "FACTION_COLORS") == want, \
        f"FACTION_COLORS in app.js is not constants.py's {py['FACTION_COLORS']}"
    fallback = re.search(r"FACTION_COLORS\.get\(int\(fid\), (\(.+?\))\)", src)
    assert fallback, "faction_color's fallback moved"
    assert _js_constant(js, "FACTION_DEFAULT") == _rgb_list(ast.literal_eval(fallback.group(1)))
    for name in ("COL_HP_HIGH", "COL_HP_MID", "COL_HP_LOW"):
        assert _js_constant(js, name) == _rgb_list(py[name]), name
    assert int(_js_constant(js, "FONT_SM")) == py["FONT_SM"]
    print("✅ test_constants_match_the_dm_screen")


def test_the_token_in_the_client():
    """`token_checks.js`, run against the real `app.js`; skipped without node, as
    `test_playback.py` is."""
    node = shutil.which("node") or shutil.which("nodejs")
    if node is None:
        print("⚠️  test_the_token_in_the_client SKIPPED — no node in this image")
        return
    done = subprocess.run([node, _CHECKS], capture_output=True, text=True, timeout=60)
    for line in done.stdout.strip().splitlines():
        print(f"   {line}")
    assert done.returncode == 0, \
        f"the token checks failed:\n{(done.stdout + done.stderr).strip()[-800:]}"
    print("✅ test_the_token_in_the_client")


if __name__ == "__main__":
    test_lookup_follows_the_view()
    test_lookup_refuses_the_unseated()
    test_the_route_serves_only_the_view()
    test_conditional_request_is_304()
    test_constants_match_the_dm_screen()
    test_the_token_in_the_client()
    sys.exit(0)
