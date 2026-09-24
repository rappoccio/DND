"""The prompt builders `main.py` owes to `gui/menus/` (MULTIPLAYER_PLAN.md M1 Step 3).

M1 Step 3 put 79 prompt sites on the bus and expected `main.py` to shrink by the 86
option lists it moved. It grew by 83 instead: the conversion replaced a two-line tail
per site with a one-to-three-line call, and the option builders — the feature methods
that decide WHICH rows a popup has and what each one does when chosen — never moved at
all. This package is where they go, a module per feature area.

What moves and what does not:

  · **The builders move.** They become plain functions taking the live `App` as their
    first argument, in the shape `actions.py` already established for the panel's
    legality (`ActionMenu.build(app, idx)`). A builder reads the app and the engine and
    ends in one `_ask_actor` / `_ask_dm` call; nothing about it needs to be a method.
  · **`_ask_actor` and `_ask_dm` stay in `main.py`.** They are the seam: they hold the
    owner defaulting (`roster.controller_of`, `DM_PRINCIPAL_ID`) and the anchor, which
    is where authorization and the F11-class mistakes live. A relocation that moved the
    seam would be a relocation nobody could review.

Three oracles make this provable rather than brave, and all three stay green across
every slice: `test_combat_panel.py`'s structural golden (the panel is byte-identical),
`test_prompts.py` (the bus drives a real reaction with no pygame events) and
`test_action_menu.py`'s checks.
"""
