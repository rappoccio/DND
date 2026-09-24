#!/usr/bin/env python3
"""`gui/menus/` — the relocated prompt builders (MULTIPLAYER_PLAN_OWED.md item 7).

This file exists because of a bug the relocation shipped: `show_agents_menu` listed its
Create PC row as `app._show_pc_class_menu`, a bound-method REFERENCE rather than a call,
so the mechanical rewrite of the call sites never touched it and clicking Agents raised
`AttributeError` while the menu was being built. All three of the relocation's oracles
were green — the panel golden, the prompt bus and the action menu — because none of them
builds a top-bar DM menu or a per-feature menu at all. A DM found it in one click.

Two checks, and between them they cover the whole class:

  · **static** — every `app._name` a `menus` module mentions must still exist on `App`.
    That catches a reference the rewrite missed, and it catches the mirror error too: a
    builder left behind calling a method that has since moved out from under it.
  · **runtime** — every builder that needs nothing but the app gets called on a real
    `App`, and its prompt must come up with every row carrying a callable. A reference
    to a missing attribute cannot survive being built.

The builders that need a resolved attack (the riders, the defender reactions) are not
callable from here; they are `test_prompts.py`'s, which drives two of them end to end.
"""

import ast
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import rpg_battle_map as rpg

from main import App
from menus import dm, features, reactions, riders

MAP_PATH = os.path.join(_ROOT, "maps", "TestGrid12x12.png")
SEED = 20260924
MODULES = {"riders": riders, "reactions": reactions, "dm": dm, "features": features}


def _app():
    app = App(MAP_PATH, seed=SEED)
    cfg = rpg.AgentConfig()
    cfg.name, cfg.start_col, cfg.start_row, cfg.size, cfg.sprite_path = "Menu Probe", 5, 5, 1, ""
    app.combat.add_agent_config(app.bm, cfg)
    app.pending_configs.append(cfg)
    app.combat.apply_agent_configs(app.bm)
    app._sync_roster_tokens()
    return app


def _module_path(mod):
    return os.path.join(_ROOT, "gui", "menus", os.path.basename(mod.__file__))


def test_every_app_attribute_a_menu_names_exists():
    """The static half. `app._foo` in a menus module must name something on `App` —
    whether it is called, passed as a callback, or read as a value."""
    probe = _app()                     # an instance: `App` the class has no `bm`, `combat`, …
    missing = []
    for name, mod in MODULES.items():
        tree = ast.parse(open(_module_path(mod)).read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                    and node.value.id == "app" and not hasattr(probe, node.attr)):
                missing.append(f"{name}.py:{node.lineno}  app.{node.attr}")
    assert not missing, (
        "a menus module names an App attribute that does not exist "
        "(a reference the relocation did not rewrite, or a method that moved out from "
        "under it):\n  " + "\n  ".join(sorted(set(missing))))
    print(f"✅ test_every_app_attribute_a_menu_names_exists passed "
          f"({len(MODULES)} modules)")


def _solo_builders(mod):
    """The builders whose only required argument is `app`."""
    tree = ast.parse(open(_module_path(mod)).read())
    out = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
            required = len(n.args.args) - len(n.args.defaults)
            if required == 1 and n.args.args[0].arg == "app":
                out.append(getattr(mod, n.name))
    return out


def test_every_solo_builder_builds_its_prompt():
    """The runtime half, and the one that fails on the Agents bug.

    A builder may legitimately decline to open anything — Wild Shape with no uses left
    logs and returns — so an empty result is allowed. What is NOT allowed is raising, or
    opening a prompt whose rows are not callable.
    """
    built, declined = 0, 0
    for name, mod in MODULES.items():
        for fn in _solo_builders(mod):
            app = _app()
            fn(app)                       # must not raise
            p = app.prompts.live
            if p is None:
                declined += 1             # declined, with a log line — legitimate
                continue
            assert p.options, f"{name}.{fn.__name__} opened an empty prompt"
            for opt in p.options:
                assert isinstance(opt.label, str) and opt.label, \
                    f"{name}.{fn.__name__} has a row with no label"
                assert opt.on_choose is None or callable(opt.on_choose), \
                    f"{name}.{fn.__name__}: row {opt.label!r} is not callable"
            built += 1
    assert built >= 5, f"only {built} builders opened a prompt — the sweep is too thin"
    print(f"✅ test_every_solo_builder_builds_its_prompt passed "
          f"({built} prompts built, {declined} declined)")


def test_the_seam_did_not_move():
    """`_ask_actor` and `_ask_dm` stay on `App`: they hold the owner defaulting and the
    anchor, which is where authorization lives. Every relocated builder reaches them
    through `app`, and none of them re-implements one."""
    for meth in ("_ask_actor", "_ask_dm"):
        assert callable(getattr(App, meth, None)), f"App.{meth} has moved"
    for name, mod in MODULES.items():
        src = open(_module_path(mod)).read()
        tree = ast.parse(src)
        for n in ast.walk(tree):
            assert not (isinstance(n, ast.FunctionDef) and n.name in ("ask_actor", "ask_dm")), \
                f"{name}.py defines its own {n.name} — the seam must stay in main.py"
        assert "prompts.ask(" not in src, \
            f"{name}.py calls the bus directly instead of going through the seam"
    print("✅ test_the_seam_did_not_move passed")


def main():
    tests = [test_every_app_attribute_a_menu_names_exists,
             test_every_solo_builder_builds_its_prompt,
             test_the_seam_did_not_move]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"❌ {t.__name__}: {e}")
    if failed:
        print(f"\n❌ test_menus: {failed}/{len(tests)} failed")
        return 1
    print(f"\n✅ test_menus: {len(tests)}/{len(tests)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
