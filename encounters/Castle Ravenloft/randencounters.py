#!/usr/bin/env python3
"""Castle Ravenloft random encounters (Curse of Strahd, chapter 4).

Usage:
    python3 randencounters.py            # one encounter
    python3 randencounters.py 5          # five encounters
    python3 randencounters.py 3 --seed 7 # reproducible draws
"""

import argparse
import random
import re


class RavenloftEncounters:
    """Draws from the Castle Ravenloft random-encounter table (d20)."""

    def __init__(self, seed=None):
        self.rng = random.Random(seed)

        self.encounters = {
            1: "Empty",
            2: "Ezmerelda d'Avenir (see appendix D)",
            3: "Rahadin (see appendix D)",
            4: "1 black cat",
            5: "1 broom of animated attack (see appendix D)",
            6: "1d4 + 1 flying swords",
            7: "Blinsky toy",
            8: "Unseen servant",
            9: "1d4 Barovian commoners",
            10: "2d6 crawling claws",
            11: "1d6 shadows",
            12: "1d6 swarms of bats",
            13: "1 crawling Strahd zombie (see appendix D)",
            14: "1d4 + 1 Vistani thugs",
            15: "1d4 wights",
            16: "Trinket",
            17: "Giant spider cocoon",
            18: "1 Barovian witch (see appendix D)",
            19: "1d4 + 1 vampire spawn",
            20: "Strahd von Zarovich (see appendix D)",
        }

        self.cocoon_contents = {
            1: "A wooden mannequin wearing a gown.",
            2: "A Barovian witch (see appendix D). She screams like a wild "
               "animal and begins casting spells.",
            3: "A Strahd zombie (see appendix D). It fights until killed.",
            4: "A Barovian lunatic (CN male commoner). If freed, he cackles "
               "until silenced or until a calm emotions spell is cast on him. "
               "A lesser restoration spell cures his madness, at which point "
               "he tries to flee the castle.",
            5: "A dead Barovian that serves as host to a swarm of insects "
               "(spiders). The baby giant spiders (each one the size of a "
               "tarantula) crawl out of the Barovian's gaping mouth or burst "
               "forth from its distended belly.",
            6: "A Vistana bandit (CN male or female). The Vistana knows the "
               "castle's layout and helps the characters until Strahd or more "
               "Vistani appear, at which point the treacherous Vistana turns "
               "on the characters.",
        }

        self.rahadin_destinations = {
            1: "Chapel (area K15)",
            2: "Audience hall (area K25)",
            3: "Study (area K37)",
            4: "Tower roof (area K57)",
            5: "Wine cellar (area K63)",
            6: "Torture chamber (area K76)",
        }

        self.unseen_servant_items = {
            1: "A tarnished silver platter with a lid (worth 25 gp). If a "
               "character comes within 5 feet of the servant, it lifts the "
               "lid, revealing a bunch of moldy scones. The first character "
               "to eat a scone gains inspiration. On later occurrences of "
               "this encounter, the platter holds a crawling claw that "
               "attacks the nearest character.",
            2: "A silver goblet (worth 50 gp) filled to the brim with wine. A "
               "character who drinks the wine must make a DC 15 Constitution "
               "saving throw, taking 44 (8d10) poison damage on a failed "
               "save, or half as much damage on a successful one. On future "
               "occurrences of this encounter, the wine acts as a potion of "
               "healing.",
            3: "A gold candelabrum (worth 150 gp) with three branches, each "
               "one holding an unlit candle.",
            4: "A purple silk handkerchief with white ruffled edges (worth "
               "1 gp). On future occurrences of this encounter, the "
               "handkerchief is smeared with fresh blood.",
            5: "A crystal dinner bell (worth 25 gp). The unseen servant rings "
               "the bell if the characters come within 10 feet of it. The "
               "sound attracts 1d4 hungry vampire spawn, which arrive in "
               "1d4 + 1 rounds.",
            6: "A wizard's spellbook with a black velvet dust jacket over its "
               "stitched leather cover. The book contains all the spells "
               "Strahd has prepared (see appendix D). On subsequent "
               "occurrences of this encounter, the tome is a nonmagical "
               "leather-bound storybook worth 25 gp.",
        }

    def roll(self, expr):
        """Roll a dice expression like '2d6', '1d4 + 1' or 'd20'."""
        m = re.fullmatch(r"\s*(\d*)d(\d+)\s*(?:([+-])\s*(\d+))?\s*", expr)
        if not m:
            raise ValueError(f"bad dice expression: {expr!r}")
        n = int(m.group(1) or 1)
        sides = int(m.group(2))
        total = sum(self.rng.randint(1, sides) for _ in range(n))
        if m.group(3):
            mod = int(m.group(4))
            total += mod if m.group(3) == "+" else -mod
        return total

    def draw(self):
        """Draw one random encounter, with any follow-up table rolls.

        Returns a dict: d20 roll, encounter text, rolled creature count
        (if the entry has dice), and a follow-up roll/text where it applies.
        """
        d20 = self.rng.randint(1, 20)
        text = self.encounters[d20]
        result = {"roll": d20, "encounter": text}

        dice = re.match(r"(\d+d\d+(?:\s*[+-]\s*\d+)?)\s", text)
        if dice:
            result["count"] = self.roll(dice.group(1))

        followup = {
            3: ("Rahadin sends the party to", self.rahadin_destinations),
            8: ("The unseen servant carries", self.unseen_servant_items),
            17: ("The cocoon holds", self.cocoon_contents),
        }.get(d20)
        if followup:
            label, table = followup
            d6 = self.rng.randint(1, 6)
            result["followup"] = {"label": label, "roll": d6, "text": table[d6]}

        # The dinner bell summons its own vampire spawn.
        if d20 == 8 and result["followup"]["roll"] == 5:
            result["followup"]["spawn"] = self.roll("1d4")
            result["followup"]["rounds"] = self.roll("1d4 + 1")

        return result

    @staticmethod
    def describe(result):
        """Format a draw() result as readable text."""
        lines = [f"d20 = {result['roll']}: {result['encounter']}"]
        if "count" in result:
            lines.append(f"  Number appearing: {result['count']}")
        f = result.get("followup")
        if f:
            lines.append(f"  {f['label']} (d6 = {f['roll']}): {f['text']}")
            if "spawn" in f:
                lines.append(f"  If rung: {f['spawn']} vampire spawn "
                             f"arrive in {f['rounds']} rounds.")
        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("n", nargs="?", type=int, default=1,
                        help="number of encounters to draw")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    table = RavenloftEncounters(seed=args.seed)
    for i in range(args.n):
        if i:
            print()
        print(table.describe(table.draw()))


if __name__ == "__main__":
    main()
