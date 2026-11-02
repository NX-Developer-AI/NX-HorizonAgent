import json
import math
import os
import random
import time

MEMORY_PATH = os.path.expanduser(os.environ.get("NX_HORIZON_MEMORY", "~/.local/share/nx-horizon/crystal_memory.json"))

PARAMETER_OPTIONS = {
    "safety_margin": [0.3, 0.45, 0.6],
    "place_to_break_delay": [0.1, 0.15, 0.2],
    "eat_health": [8.0, 10.0, 12.0],
    "melee_trigger": [2.2, 2.8, 3.2],
    "knockback_lead": [0.2, 0.35, 0.5],
}
DEFAULT_PARAMETERS = {"safety_margin": 0.45, "place_to_break_delay": 0.15, "eat_health": 10.0,
                      "melee_trigger": 2.8, "knockback_lead": 0.35}
EXPLORATION_RATE = 0.25
PRIOR_DAMAGE = 1.0
PRIOR_WEIGHT = 2.0


class CrystalMemory:
    def __init__(self, path=MEMORY_PATH):
        self.path = path
        self.data = {"placement": {}, "parameters": {}, "totem": {"pops": 0, "swap_milliseconds": []}, "fights": []}
        if os.path.exists(path):
            with open(path) as file:
                self.data.update(json.load(file))

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        temporary = self.path + ".partial"
        with open(temporary, "w") as file:
            json.dump(self.data, file, indent=1)
        os.replace(temporary, self.path)

    @staticmethod
    def placement_bucket(distance_to_target, side, target_moving):
        distance_bucket = min(4, int(distance_to_target / 0.5))
        return f"{distance_bucket}|{side}|{'moving' if target_moving else 'still'}"

    def expected_damage(self, bucket):
        entry = self.data["placement"].get(bucket)
        if not entry:
            return PRIOR_DAMAGE
        return (entry["damage"] + PRIOR_DAMAGE * PRIOR_WEIGHT) / (entry["tries"] + PRIOR_WEIGHT)

    def record_placement(self, bucket, damage):
        entry = self.data["placement"].setdefault(bucket, {"tries": 0, "hits": 0, "damage": 0.0})
        entry["tries"] += 1
        entry["damage"] += max(0.0, damage)
        if damage > 0.05:
            entry["hits"] += 1

    def choose_parameters(self):
        chosen = {}
        for name, options in PARAMETER_OPTIONS.items():
            arms = self.data["parameters"].setdefault(name, {})
            if random.random() < EXPLORATION_RATE or not arms:
                chosen[name] = random.choice(options)
                continue
            best = max(options, key=lambda option: self._arm_average(arms, option))
            chosen[name] = best
        return chosen

    @staticmethod
    def _arm_average(arms, option):
        entry = arms.get(str(option))
        if not entry or entry["fights"] == 0:
            return math.inf
        return entry["score"] / entry["fights"]

    def record_fight(self, parameters, damage_dealt, damage_taken, seconds, won, died, totems_popped):
        score = damage_dealt / max(seconds, 1.0) * 10.0 - damage_taken * 0.5 + (20.0 if won else 0.0) - (30.0 if died else 0.0)
        for name, value in parameters.items():
            entry = self.data["parameters"].setdefault(name, {}).setdefault(str(value), {"fights": 0, "score": 0.0})
            entry["fights"] += 1
            entry["score"] += score
        self.data["fights"].append({
            "time": int(time.time()), "parameters": parameters, "damage_dealt": round(damage_dealt, 2),
            "damage_taken": round(damage_taken, 2), "seconds": round(seconds, 1), "won": won, "died": died,
            "totems_popped": totems_popped, "score": round(score, 2)})
        self.data["fights"] = self.data["fights"][-200:]
        return score

    def record_totem(self, swap_milliseconds):
        self.data["totem"]["pops"] += 1
        self.data["totem"]["swap_milliseconds"] = (self.data["totem"]["swap_milliseconds"] + [swap_milliseconds])[-50:]

    def summary(self):
        lines = []
        placements = sorted(self.data["placement"].items(), key=lambda item: -self.expected_damage(item[0]))
        for bucket, entry in placements[:6]:
            lines.append(f"  {bucket:22} tries {entry['tries']:3} hit {entry['hits'] / max(1, entry['tries']):4.0%} "
                         f"avg dmg {self.expected_damage(bucket):.2f}")
        for name, arms in self.data["parameters"].items():
            averages = {option: round(entry["score"] / entry["fights"], 1) for option, entry in arms.items() if entry["fights"]}
            lines.append(f"  {name}: {averages}")
        totem = self.data["totem"]
        if totem["swap_milliseconds"]:
            lines.append(f"  totem pops {totem['pops']}, avg re-equip {sum(totem['swap_milliseconds']) / len(totem['swap_milliseconds']):.0f} ms")
        lines.append(f"  fights recorded: {len(self.data['fights'])}")
        return "\n".join(lines)
