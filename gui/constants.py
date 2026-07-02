# ─────────────────────────────────────────────────────────────────────────────
#  constants.py  –  Global color and layout constants
# ─────────────────────────────────────────────────────────────────────────────

# ── Factions / teams ────────────────────────────────────────────────────────────
# Encounter-side team ids (PlacedAgent.faction). 0 = neutral (its own faction,
# hostile to everyone); 1+ = playable teams. Keep red/blue as the first two.
FACTION_NAMES  = {0: "neutral", 1: "red", 2: "blue"}
FACTION_COLORS = {
    0: (160, 160, 160),   # grey – neutral / unassigned
    1: (210,  70,  70),   # red team
    2: ( 80, 120, 220),   # blue team
}
# Team ids offered in the GUI picker (neutral + the playable teams).
FACTION_CHOICES = [0, 1, 2]
# Team the party is dropped onto (encounter mobs are the "red" team, so PCs go "blue").
PC_FACTION = 2

def faction_name(fid: int) -> str:
    return FACTION_NAMES.get(int(fid), f"faction {fid}")

def faction_color(fid: int):
    return FACTION_COLORS.get(int(fid), (200, 200, 60))

# ── UI colors ──────────────────────────────────────────────────────────────────
COL_BG          = (30,  30,  30)
COL_PANEL_BG    = (45,  45,  55)
COL_PANEL_BORDER= (80,  80, 100)
COL_GRID        = (255, 255, 255, 60)     # semi-transparent
COL_WALL        = (200,  60,  60, 220)
COL_BLOCKED     = (0,    0,   0, 100)
COL_AGENT_FILL  = (100, 149, 237, 210)    # cornflower blue placeholder
COL_AGENT_BORDER= (255, 255, 255, 255)
COL_TEXT        = (220, 220, 220)
COL_LABEL       = (170, 170, 200)
COL_BTN         = (70,  90, 130)
COL_BTN_HOVER   = (90, 115, 165)
COL_BTN_DANGER  = (130,  50,  50)
COL_INPUT_BG    = (35,  35,  45)
COL_INPUT_ACTIVE= (55,  55,  75)

# ── Combat panel colours ──────────────────────────────────────────────────────
COL_INITIATIVE_CUR  = (255, 210,  50)   # gold — current combatant row
COL_HP_HIGH         = ( 60, 200,  80)   # green  – > 66 % HP
COL_HP_MID          = (230, 180,  40)   # amber  – 33–66 % HP
COL_HP_LOW          = (220,  60,  60)   # red    – < 33 % HP
COL_BTN_COMBAT      = (140,  75,  15)   # orange-brown "Begin Combat"
COL_BTN_COMBAT_HOV  = (180, 100,  25)
COL_BTN_ATK         = ( 55, 140,  60)   # green attack button
COL_BTN_ATK_HOV     = ( 80, 170,  85)
COL_BTN_PASS        = ( 65,  65,  88)   # grey-blue pass button
COL_BTN_PASS_HOV    = ( 88,  88, 115)
COL_BTN_ENDTURN     = ( 45,  95, 150)   # blue end-turn
COL_BTN_ENDTURN_HOV = ( 65, 120, 185)
COL_BTN_DASH        = ( 50,  95, 160)   # blue – dash
COL_BTN_DASH_HOV    = ( 75, 120, 195)
COL_BTN_DODGE       = ( 35, 115, 105)   # teal – dodge
COL_BTN_DODGE_HOV   = ( 55, 145, 135)
COL_BTN_DISENG      = (130,  90,  20)   # amber – disengage
COL_BTN_DISENG_HOV  = (165, 120,  35)
COL_BTN_SPELL       = ( 90,  50, 145)   # purple – cast spell
COL_BTN_SPELL_HOV   = (120,  75, 180)

# ── Layout ────────────────────────────────────────────────────────────────────
PANEL_W   = 340       # right-side config panel width
MAP_MARGIN = 0        # pixel margin around map inside left area
FONT_SM   = 14
FONT_MD   = 16
FONT_LG   = 20

# ── File extensions ───────────────────────────────────────────────────────────
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp', '.tga'}
JSON_EXTS  = {'.json'}
