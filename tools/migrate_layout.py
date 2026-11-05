#!/usr/bin/env python3
"""Move the three campaigns to the new save layout (plans/SAVE_LAYOUT_PLAN.md, step 4).

One recipe per campaign, because the choices are per campaign (which roster is the live
run, which terrain is the map, which images are originals and which are a dungeon's
rescaled copies). Each recipe builds a plan: files to write, files to copy, and the old
files to archive. Nothing is deleted. On ``--apply`` the new layout is written beside the
old files, then every file and folder that was in the campaign folder before is moved to
``<campaign>/_archive/``, along with any outside source file the recipe used.

Without ``--apply`` it only prints the plan, plus a check per map: the run's terrain,
rebuilt from the new map.json + dungeon.json + run.json, against the old terrain file.

    python3 tools/migrate_layout.py                  # dry run, all three
    python3 tools/migrate_layout.py sithicus         # dry run, one
    python3 tools/migrate_layout.py sithicus --apply

Quit the game first: it saves on quit and on a floor switch.
"""

import argparse
import copy
import json
import os
import re
import shutil
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "gui"))

import run_state as rs  # noqa: E402
import save_layout as sl  # noqa: E402
from dungeon import Dungeon  # noqa: E402

ENCOUNTERS = os.path.join(_ROOT, "encounters")
ARCHIVE = "_archive"
# Top-level keys of an agents file that are creatures, not encounter metadata.
_CREATURE_KEYS = ("agents", "map_items", "active_conditions")
# Keys an agent record picks up from where it was saved, not who it is.
_PLACEMENT_KEYS = ("encounter", "page", "z")


def _read(path):
    with open(path) as f:
        return json.load(f)


def _mtime(path):
    return os.path.getmtime(path)


class Plan:
    """What one campaign's migration writes, copies and archives."""

    def __init__(self, key, src_dir, name, rename_to=None):
        self.key = key
        self.src_dir = src_dir                 # the campaign folder as it is now
        self.name = name                       # campaign.json "name"
        self.rename_to = rename_to             # new folder name, or None
        self.writes = []                       # (rel, doc, note)
        self.copies = []                       # (src, rel, note)
        self.external = []                     # outside files archived after use
        self.notes = []
        self.checks = []                       # (label, ok, detail)

    def write(self, rel, doc, note=""):
        self.writes.append((rel, doc, note))

    def copy(self, src, rel, note=""):
        if not os.path.isfile(src):
            raise FileNotFoundError(src)
        self.copies.append((src, rel, note))

    # ── Output ────────────────────────────────────────────────────────────
    def report(self):
        dest = self.rename_to or os.path.basename(self.src_dir)
        print(f"\n=== {self.key}: {os.path.basename(self.src_dir)} → {dest}"
              f"  (campaign \"{self.name}\")")
        rows = ([(rel, f"copy ← {os.path.relpath(src, ENCOUNTERS)}", note)
                 for src, rel, note in self.copies]
                + [(rel, "write", note) for rel, _, note in self.writes])
        for rel, how, note in sorted(rows):
            print(f"  {rel:<70} {how}" + (f"   [{note}]" if note else ""))
        pre = sorted(os.listdir(self.src_dir))
        print(f"  archive: {len(pre)} entries of {os.path.basename(self.src_dir)}/ "
              f"→ {dest}/{ARCHIVE}/")
        for p in self.external:
            print(f"  archive: {os.path.relpath(p, ENCOUNTERS)} → {dest}/{ARCHIVE}/")
        for label, ok, detail in self.checks:
            print(f"  check {'ok  ' if ok else 'DIFF'} {label}" + (f": {detail}" if detail else ""))
        for n in self.notes:
            print(f"  note: {n}")

    def apply(self):
        new_top = {rel.split("/")[0] for rel, _, _ in self.writes}
        new_top |= {rel.split("/")[0] for _, rel, _ in self.copies}
        pre = sorted(os.listdir(self.src_dir))
        clash = (new_top | {ARCHIVE}) & set(pre)
        if clash:
            raise SystemExit(f"{self.key}: already present, refusing: {sorted(clash)}")
        if self.rename_to and os.path.exists(os.path.join(ENCOUNTERS, self.rename_to)):
            raise SystemExit(f"{self.key}: {self.rename_to} already exists")
        for src, rel, _ in self.copies:
            dst = os.path.join(self.src_dir, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        for rel, doc, _ in self.writes:
            sl.atomic_write_json(os.path.join(self.src_dir, rel), doc)
        arch = os.path.join(self.src_dir, ARCHIVE)
        os.makedirs(arch)
        for entry in pre:
            shutil.move(os.path.join(self.src_dir, entry), os.path.join(arch, entry))
        for p in self.external:
            shutil.move(p, os.path.join(arch, os.path.basename(p)))
        final = self.src_dir
        if self.rename_to:
            final = os.path.join(ENCOUNTERS, self.rename_to)
            os.rename(self.src_dir, final)
        print(f"  applied → {os.path.relpath(final, _ROOT)}")


# ── Shared pieces ────────────────────────────────────────────────────────────
def _split(terrain_path):
    return rs.split_terrain(_read(terrain_path))


def _norm_terrain(t):
    """A terrain doc with door defaults filled, for comparing old against rebuilt."""
    m, x, s = rs.split_terrain(t)
    out = rs.merge_terrain(m, x, s)
    for k in ("ladders", "staging_cells"):
        if not out.get(k):
            out.pop(k, None)
    return out


def check_rebuild(plan, label, old_terrain_path, map_doc, extras, state):
    """Does the new layout rebuild the old terrain exactly? Records the keys that differ."""
    old = _norm_terrain(_read(old_terrain_path))
    new = _norm_terrain(rs.merge_terrain(map_doc, extras, state))
    diff = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
    plan.checks.append((label, not diff, ", ".join(diff)))


def compare_map_facts(plan, label, chosen, others):
    """Note which candidate terrains disagree with the chosen one on map facts."""
    def facts(path):
        m, _, _ = _split(path)
        m["doors"] = sorted(rs.door_key(d) for d in m.get("doors", []))   # where, not open/shut
        return m
    base = facts(chosen)
    for p in others:
        m = facts(p)
        diff = sorted(k for k in set(base) | set(m) if base.get(k) != m.get(k))
        if diff:
            plan.notes.append(f"{label}: {os.path.basename(p)} differs from "
                              f"{os.path.basename(chosen)} in {', '.join(diff)}")


def pc_records(paths, pc_names):
    """{name: agent record}, each from the newest file that has that PC (first match
    within a file)."""
    found = {}
    for p in sorted(paths, key=_mtime, reverse=True):
        for a in _read(p).get("agents", []) or []:
            n = a.get("name")
            if n in pc_names and n not in found:
                rec = copy.deepcopy(a)
                for k in _PLACEMENT_KEYS:
                    rec.pop(k, None)
                found[n] = (rec, p)
    return found


def add_pcs(plan, paths, pc_names):
    found = pc_records(paths, pc_names)
    for n in pc_names:
        if n not in found:
            plan.notes.append(f"PC {n!r} not found in any roster")
            continue
        rec, src = found[n]
        plan.write(f"{sl.PCS_DIR}/{sl.slugify(n)}.json", rec,
                   f"from {os.path.basename(src)}")


def encounter_doc(agents_doc, pc_names):
    """An encounter definition from a roster: its non-PC creatures and its generator
    metadata. Map items and conditions are play state; they stay in the run."""
    doc = {k: copy.deepcopy(v) for k, v in agents_doc.items() if k not in _CREATURE_KEYS}
    doc["agents"] = [copy.deepcopy(a) for a in agents_doc.get("agents", []) or []
                     if a.get("name") not in pc_names]
    doc["map_items"], doc["active_conditions"] = [], []
    return doc


def run_section_from(run, map_name, agents_doc, state, pc_names, encounter=None):
    """A run's section for a map from an old roster + terrain state. Non-PC creatures
    are tagged with ``encounter`` when the map got one from this roster."""
    doc = {k: copy.deepcopy(agents_doc.get(k, []) or []) for k in _CREATURE_KEYS}
    if encounter:
        for a in doc["agents"]:
            if a.get("name") not in pc_names:
                a["encounter"] = encounter
    rs.set_creatures(run, map_name, doc)
    rs.map_section(run, map_name)["state"] = state


def merged_session(paths):
    """One campaign session from every old per-encounter one (D9): the newest file's join
    code and settings, and every principal any of them seated (by id, newest first), so
    the creatures' controllers all still name a seat."""
    paths = sorted((p for p in paths if os.path.isfile(p)), key=_mtime, reverse=True)
    doc = copy.deepcopy(_read(paths[0]))
    seen, principals, revoked = set(), [], []
    for p in paths:
        d = _read(p)
        for pr in d.get("principals", []) or []:
            if pr.get("id") not in seen:
                seen.add(pr.get("id"))
                principals.append(pr)
        revoked += [r for r in d.get("revoked", []) or [] if r not in revoked]
    doc["principals"], doc["revoked"] = principals, revoked
    return doc


def add_session(plan, paths):
    paths = [p for p in paths if p.endswith("_session.json")]
    doc = merged_session(paths)
    names = [pr.get("display_name") for pr in doc["principals"]]
    plan.write(sl.SESSION_FILE, doc, f"union of {len(paths)}: join code {doc.get('join_code')}, "
                                     f"seats {', '.join(map(str, names))}")


def campaign_doc(name):
    return {"version": sl.LAYOUT_VERSION, "name": name}


def newest(paths):
    paths = [p for p in paths if os.path.isfile(p)]
    return max(paths, key=_mtime) if paths else None


def ext_of(path):
    return os.path.splitext(path)[1].lower()


# ── Sithicus ─────────────────────────────────────────────────────────────────
def plan_sithicus():
    src = os.path.join(ENCOUNTERS, "Sithicus")
    base = os.path.join(src, "map-16-02.nedragaard-keep-player")
    pcs = ["Sabalath", "Java of the Indies"]
    m = "nedragaard-keep"
    plan = Plan("sithicus", src, "Sithicus")
    plan.write(sl.CAMPAIGN_FILE, campaign_doc("Sithicus"))
    plan.copy(base + ".jpg", f"{sl.MAPS_DIR}/{m}/{m}.jpg", "library art")

    run_ter = base + "_pc_dungeon_terrain.json"
    terrains = sorted(p for p in (os.path.join(src, f) for f in os.listdir(src))
                      if p.endswith("_terrain.json"))
    map_ter = newest(terrains)
    map_doc, _, _ = _split(map_ter)
    _, extras, state = _split(run_ter)
    compare_map_facts(plan, m, map_ter, [t for t in terrains if t != map_ter])
    plan.write(f"{sl.MAPS_DIR}/{m}/{sl.MAP_FILE}", map_doc,
               f"from the newest terrain, {os.path.basename(map_ter)}")

    dung = Dungeon.single_map(m)
    page = dung.pages[0]
    page.ladders, page.door_links = extras["ladders"], extras["door_links"]
    page.staging_cells = extras["staging_cells"]
    plan.write(f"{m}/{sl.DUNGEON_FILE}", dung.to_dict(), "one map")
    plan.notes.append(f"{m}: cols/rows are 0 until the app first opens the map")

    for i, suffix in enumerate(("_dungeon", "_dungeon_dungeon", "_dungeon_dungeon_dungeon"), 1):
        doc = encounter_doc(_read(base + suffix + "_agents.json"), pcs)
        plan.write(f"{m}/{sl.MAPS_DIR}/{m}/{sl.ENCOUNTERS_DIR}/generated-{i}.json", doc,
                   f"{len(doc['agents'])} creatures from …{suffix}_agents.json")

    run = rs.new_run(m)
    run_agents = _read(base + "_pc_dungeon_agents.json")
    run_section_from(run, m, run_agents, state, pcs)
    plan.write(f"{m}/{sl.RUNS_DIR}/{sl.DEFAULT_RUN}/{sl.RUN_FILE}", run,
               f"{len(run_agents['agents'])} creatures from …_pc_dungeon_agents.json")
    check_rebuild(plan, f"{m} run", run_ter, map_doc, extras, state)

    add_pcs(plan, [p for p in (os.path.join(src, f) for f in os.listdir(src))
                   if p.endswith(("_agents.json", "_pcagents.json"))], pcs)
    add_session(plan, [os.path.join(src, f) for f in os.listdir(src)])
    return plan


# ── Descent Into Avernus ─────────────────────────────────────────────────────
def avernus_slug(fn):
    """``map-2.6-boneyard-player.jpg`` → ``boneyard``."""
    stem = os.path.splitext(fn)[0]
    stem = re.sub(r"^map-[\d.]+-", "", stem)
    stem = re.sub(r"-player$", "", stem)
    return sl.slugify(stem)


def plan_avernus():
    src = os.path.join(ENCOUNTERS, "Descent Into Avernus")
    pcs = ["Fergus", "Tiza"]
    plan = Plan("avernus", src, "Descent Into Avernus")
    plan.write(sl.CAMPAIGN_FILE, campaign_doc("Descent Into Avernus"))
    images = sorted(f for f in os.listdir(src) if ext_of(f) in sl.IMAGE_EXTS)
    slugs = {}
    for f in images:
        s = avernus_slug(f)
        if s in slugs.values():
            raise SystemExit(f"avernus: two images slug to {s}")
        slugs[f] = s
        plan.copy(os.path.join(src, f), f"{sl.MAPS_DIR}/{s}/{s}{ext_of(f)}", "library art")

    elf = os.path.join(src, "map-1.2-elfsong_terrain.json")
    plan.write(f"{sl.MAPS_DIR}/elfsong/{sl.MAP_FILE}", _split(elf)[0],
               "from map-1.2-elfsong_terrain.json")

    b = os.path.join(src, "map-2.6-boneyard-player")
    m = "boneyard"
    map_doc, extras, state = _split(b + "_terrain.json")
    plan.write(f"{sl.MAPS_DIR}/{m}/{sl.MAP_FILE}", map_doc, "from …boneyard-player_terrain.json")
    dung = Dungeon.single_map(m)
    page = dung.pages[0]
    page.ladders, page.door_links = extras["ladders"], extras["door_links"]
    page.staging_cells = extras["staging_cells"]
    plan.write(f"{m}/{sl.DUNGEON_FILE}", dung.to_dict(), "one map")
    agents = _read(b + "_agents.json")
    enc = encounter_doc(agents, pcs)
    plan.write(f"{m}/{sl.MAPS_DIR}/{m}/{sl.ENCOUNTERS_DIR}/{m}.json", enc,
               f"{len(enc['agents'])} creatures")
    run = rs.new_run(m)
    run_section_from(run, m, agents, state, pcs, encounter=m)
    plan.write(f"{m}/{sl.RUNS_DIR}/{sl.DEFAULT_RUN}/{sl.RUN_FILE}", run,
               f"{len(agents['agents'])} creatures")
    check_rebuild(plan, f"{m} run", b + "_terrain.json", map_doc, extras, state)
    plan.notes.append(f"{m}: old autosave slots are archived, not converted")
    add_pcs(plan, [b + "_agents.json"], pcs)
    add_session(plan, [b + "_session.json"])
    return plan


# ── Curse of Strahd ──────────────────────────────────────────────────────────
def strahd_slug(name):
    """``main_floor_ravenloft`` / ``…_frame.png`` → ``main-floor``."""
    stem = os.path.splitext(os.path.basename(name))[0]
    stem = re.sub(r"_frame$", "", stem)
    if not stem.endswith("_of_ravenloft"):            # spires_of_ravenloft keeps its name
        stem = re.sub(r"_ravenloft$", "", stem)
    return sl.slugify(stem)


STRAHD_EXTRA_ART = ("area_k73_ravenloft.png", "high_tower_peak_map10_ravenloft.png",
                    "north_tower_peak_map9_ravenloft.png", "spires_of_ravenloft.png",
                    "walls_of_ravenloft.png")


def plan_strahd():
    src = os.path.join(ENCOUNTERS, "Castle Ravenloft")
    pcs = ["Aodhan", "Hilaria", "Keef Girgo", "Seungho", "The Menacing Shadow"]
    plan = Plan("strahd", src, "Curse of Strahd", rename_to="Curse of Strahd")
    plan.write(sl.CAMPAIGN_FILE, campaign_doc("Curse of Strahd"))

    old = Dungeon.load(os.path.join(src, "main_floor_ravenloft.dungeon.json"))
    ids = {p.id: strahd_slug(p.id) for p in old.pages}
    D = "castle-ravenloft"
    new = copy.deepcopy(old)
    new.version = 2
    new.entry_page_id = ids[old.entry_page_id]
    for st in new.staircases:
        for e in st.ends:
            e.page = ids[e.page]
    run = rs.new_run(None)
    rosters = []
    pc_count = {}
    for page, npage in zip(old.pages, new.pages):
        m = ids[page.id]
        npage.id, npage.png, npage.encounter_base = m, "", ""
        orig = os.path.join(src, page.png.replace("_frame.png", ".png"))
        if os.path.isfile(orig):
            plan.copy(orig, f"{sl.MAPS_DIR}/{m}/{m}{ext_of(orig)}", "library art")
        else:
            plan.notes.append(f"{m}: no original art; the dungeon copy is the only image")
        plan.copy(os.path.join(src, page.png), f"{D}/{sl.MAPS_DIR}/{m}/{m}.png",
                  "dungeon copy (framed)")
        base = os.path.join(src, page.encounter_base[:-len("_agents.json")])
        map_doc, extras, state = _split(base + "_terrain.json")
        plan.write(f"{D}/{sl.MAPS_DIR}/{m}/{sl.MAP_FILE}", map_doc,
                   "with the dungeon copy's grid")
        npage.ladders, npage.door_links = extras["ladders"], extras["door_links"]
        npage.staging_cells = extras["staging_cells"]
        agents = _read(base + "_agents.json")
        rosters.append(base + "_agents.json")
        enc = encounter_doc(agents, pcs)
        if enc["agents"]:
            plan.write(f"{D}/{sl.MAPS_DIR}/{m}/{sl.ENCOUNTERS_DIR}/migrated.json", enc,
                       f"{len(enc['agents'])} creatures")
        run_section_from(run, m, agents, state, pcs,
                         encounter="migrated" if enc["agents"] else None)
        pc_count[m] = sum(a.get("name") in pcs for a in agents.get("agents", []))
        check_rebuild(plan, f"{m} run", base + "_terrain.json", map_doc, extras, state)
    run["current_map"] = max(pc_count, key=pc_count.get) if any(pc_count.values()) \
        else new.entry_page_id
    plan.write(f"{D}/{sl.DUNGEON_FILE}", new.to_dict(), f"{len(new.pages)} maps")
    plan.write(f"{D}/{sl.RUNS_DIR}/{sl.DEFAULT_RUN}/{sl.RUN_FILE}", run,
               f"current map {run['current_map']} (where the PCs are)")
    for f in STRAHD_EXTRA_ART:
        s = strahd_slug(f)
        plan.copy(os.path.join(src, f), f"{sl.MAPS_DIR}/{s}/{s}{ext_of(f)}", "library art")

    # Church of St. Andral: a one-map dungeon; phase 2 of the Feast is its encounter.
    C = "church-of-st-andral"
    church = os.path.join(ENCOUNTERS, "ChurchOfStAndral")
    feast2 = os.path.join(ENCOUNTERS, "simplemap_strahd_feastofstandral_phase2")
    plan.copy(church + ".png", f"{sl.MAPS_DIR}/{C}/{C}.png", "library art")
    map_doc, extras, fstate = _split(feast2 + "_terrain.json")
    plan.write(f"{sl.MAPS_DIR}/{C}/{sl.MAP_FILE}", map_doc,
               "from the Feast phase 2 terrain (the map's own is nearly empty)")
    compare_map_facts(plan, C, feast2 + "_terrain.json", [church + "_terrain.json"])
    plan.copy(feast2 + "_lighting.json", f"{sl.MAPS_DIR}/{C}/{sl.LIGHTING_FILE}",
              "the Feast's lighting (the map's own is empty)")
    dung = Dungeon.single_map(C)
    dung.pages[0].staging_cells = extras["staging_cells"]
    plan.write(f"{C}/{sl.DUNGEON_FILE}", dung.to_dict(), "one map")
    agents = _read(feast2 + "_agents.json")
    rosters.append(feast2 + "_agents.json")
    enc = encounter_doc(agents, pcs)
    plan.write(f"{C}/{sl.MAPS_DIR}/{C}/{sl.ENCOUNTERS_DIR}/feast-phase-2.json", enc,
               f"{len(enc['agents'])} creatures")
    crun = rs.new_run(C)
    run_section_from(crun, C, agents, fstate, pcs, encounter="feast-phase-2")
    check_rebuild(plan, f"{C} run", feast2 + "_terrain.json", map_doc, extras, fstate)
    plan.write(f"{C}/{sl.RUNS_DIR}/{sl.DEFAULT_RUN}/{sl.RUN_FILE}", crun,
               f"{len(agents['agents'])} creatures")
    plan.external += [p for p in (os.path.join(ENCOUNTERS, f) for f in os.listdir(ENCOUNTERS))
                      if os.path.basename(p).startswith(
                          ("ChurchOfStAndral", "simplemap_strahd_feastofstandral"))]
    plan.notes.append("Feast phase 1 is archived, not converted")

    add_pcs(plan, rosters, pcs)
    add_session(plan, [os.path.join(src, f) for f in os.listdir(src)])
    return plan


def check_controllers(plan):
    """Every run creature's controller is a seat in the campaign session (or the DM)."""
    seats = {pr.get("id") for rel, doc, _ in plan.writes if rel == sl.SESSION_FILE
             for pr in doc.get("principals", [])}
    for rel, doc, _ in plan.writes:
        if not rel.endswith("/" + sl.RUN_FILE):
            continue
        orphans = sorted({a["controller"] for sec in doc["maps"].values()
                          for a in sec["agents"]
                          if a.get("controller") not in seats | {None, "dm"}})
        plan.checks.append((f"{rel} controllers seated", not orphans, ", ".join(orphans)))


RECIPES = {"sithicus": plan_sithicus, "avernus": plan_avernus, "strahd": plan_strahd}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("campaigns", nargs="*", metavar="CAMPAIGN",
                    help=f"which to migrate: {', '.join(RECIPES)} (default: all)")
    ap.add_argument("--apply", action="store_true", help="write, then archive the old files")
    args = ap.parse_args(argv)
    keys = args.campaigns or list(RECIPES)
    unknown = [k for k in keys if k not in RECIPES]
    if unknown:
        ap.error(f"unknown campaign(s) {unknown}; choose from {list(RECIPES)}")
    plans = [RECIPES[k]() for k in keys]
    for p in plans:
        check_controllers(p)
        p.report()
    if args.apply:
        for p in plans:
            p.apply()
    else:
        print("\n(dry run: nothing written; --apply to migrate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
