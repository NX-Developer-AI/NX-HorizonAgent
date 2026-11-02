import argparse
import math
import time

from crystal_memory import CrystalMemory
from horizon_client import Horizon

REACH = 4.3
CYCLE_SECONDS = 0.5
EAT_SECONDS = 1.65
PREFERRED_RANGE = (1.3, 4.0)
LEAD_SECONDS = 0.2
LEARNED_WEIGHT = 0.8


class CrystalFighter:
    def __init__(self, target_type, time_limit, arena_center):
        self.horizon = Horizon()
        self.memory = CrystalMemory()
        self.parameters = self.memory.choose_parameters()
        self.target_type = target_type
        self.time_limit = time_limit
        self.arena_center = arena_center
        self.known_blocks = {}
        self.prefetched_area = None
        self.failed_spots = {}
        self.log = []
        self.started = time.time()
        self.current_item = None
        self.aimed_spot = None
        self.previous_sample = None
        self.pending_crystal = None
        self.damage_dealt = 0.0
        self.damage_taken = 0.0
        self.totems_popped = 0
        self.last_eat = 0.0
        self.crystals = 0

    def note(self, text):
        self.log.append(f"t={time.time() - self.started:5.1f}s {text}")

    def call(self, *words):
        return self.horizon(*words)

    def prefetch_blocks(self, center):
        low = (math.floor(center[0]) - 3, math.floor(center[1]) - 1, math.floor(center[2]) - 3)
        high = (math.floor(center[0]) + 3, math.floor(center[1]) + 3, math.floor(center[2]) + 3)
        self.known_blocks.clear()
        for entry in self.call("blocks", *low, *high).get("blocks", []):
            self.known_blocks[(entry[0], entry[1], entry[2])] = entry[3].split("[")[0]
        self.prefetched_area = (low, high)

    def block_at(self, x, y, z):
        key = (x, y, z)
        if key in self.known_blocks:
            return self.known_blocks[key]
        area = self.prefetched_area
        if area and all(area[0][i] <= key[i] <= area[1][i] for i in range(3)):
            return "minecraft:air"
        self.known_blocks[key] = self.call("block", x, y, z).get("block", "unknown")
        return self.known_blocks[key]

    @staticmethod
    def segment_hits_box(start, end, box_min, box_max):
        entry, exit_ = 0.0, 1.0
        for axis in range(3):
            delta = end[axis] - start[axis]
            if abs(delta) < 1e-9:
                if start[axis] < box_min[axis] or start[axis] > box_max[axis]:
                    return False
                continue
            first = (box_min[axis] - start[axis]) / delta
            second = (box_max[axis] - start[axis]) / delta
            entry = max(entry, min(first, second))
            exit_ = min(exit_, max(first, second))
            if entry > exit_:
                return False
        return True

    @staticmethod
    def target_box(position, margin=0.1):
        return ((position[0] - 0.3 - margin, position[1] - margin, position[2] - 0.3 - margin),
                (position[0] + 0.3 + margin, position[1] + 1.95 + margin, position[2] + 0.3 + margin))

    @staticmethod
    def side_of(spot_center, target_position, eye):
        to_target = (target_position[0] - eye[0], target_position[2] - eye[2])
        to_spot = (spot_center[0] - target_position[0], spot_center[2] - target_position[2])
        length = math.hypot(*to_target) * math.hypot(*to_spot)
        if length < 1e-6:
            return "side"
        cosine = (to_target[0] * to_spot[0] + to_target[1] * to_spot[1]) / length
        if cosine > 0.4:
            return "behind"
        if cosine < -0.4:
            return "front"
        return "side"

    def candidate_spots(self, target_position, eye, target_moving):
        base_y = math.floor(target_position[1]) - 1
        candidates = []
        margin = self.parameters["safety_margin"]
        for offset_x in range(-2, 3):
            for offset_z in range(-2, 3):
                for offset_y in (0, 1):
                    spot = (math.floor(target_position[0]) + offset_x, base_y + offset_y,
                            math.floor(target_position[2]) + offset_z)
                    if self.failed_spots.get(spot, 0) >= 2:
                        continue
                    crystal_box = ((spot[0], spot[1] + 1, spot[2]), (spot[0] + 1, spot[1] + 3, spot[2] + 1))
                    low, high = self.target_box(target_position, margin)
                    if all(crystal_box[0][i] < high[i] and low[i] < crystal_box[1][i] for i in range(3)):
                        continue
                    aim = (spot[0] + 0.5, spot[1] + 1.0, spot[2] + 0.5)
                    if math.dist(aim, eye) > REACH:
                        continue
                    if self.segment_hits_box(eye, aim, *self.target_box(target_position)):
                        continue
                    crystal_center = (spot[0] + 0.5, spot[1] + 1.5, spot[2] + 0.5)
                    to_target = math.dist(crystal_center, (target_position[0], target_position[1] + 0.9,
                                                           target_position[2]))
                    if to_target > 2.8 or to_target < 1.2:
                        continue
                    side = self.side_of(crystal_center, target_position, eye)
                    bucket = self.memory.placement_bucket(to_target, side, target_moving)
                    learned = self.memory.expected_damage(bucket)
                    to_me = math.dist(crystal_center, eye)
                    score = to_target - 0.25 * to_me - LEARNED_WEIGHT * learned - (0.3 if offset_y == 0 else 0.0)
                    candidates.append((score, spot, bucket))
        candidates.sort()
        return [(spot, bucket) for _, spot, bucket in candidates]

    def usable(self, spot):
        if self.block_at(spot[0], spot[1] + 1, spot[2]) != "minecraft:air":
            return None
        if self.block_at(spot[0], spot[1] + 2, spot[2]) != "minecraft:air":
            return None
        base = self.block_at(*spot)
        if base in ("minecraft:obsidian", "minecraft:bedrock"):
            return "ready"
        if base == "minecraft:air":
            return "needs_obsidian"
        return None

    def nearest_target(self):
        targets = self.call("entities", 16, self.target_type).get("entities", [])
        return targets[0] if targets else None

    def inventory(self):
        inventory = self.call("inventory")
        return inventory.get("counts", {}), (inventory.get("offhand") or {}).get("item")

    def ensure_offhand_totem(self):
        counts, offhand = self.inventory()
        if offhand == "minecraft:totem_of_undying" or counts.get("minecraft:totem_of_undying", 0) == 0:
            return False
        started = time.time()
        self.call("select", "totem_of_undying")
        self.call("key", "f", "tap")
        offhand_after = None
        for _ in range(6):
            time.sleep(0.05)
            _, offhand_after = self.inventory()
            if offhand_after == "minecraft:totem_of_undying":
                break
        milliseconds = int((time.time() - started) * 1000)
        if offhand_after == "minecraft:totem_of_undying":
            self.totems_popped += 1
            self.memory.record_totem(milliseconds)
            self.note(f"totem popped: new totem in offhand after {milliseconds} ms")
        self.current_item = None
        self.aimed_spot = None
        return True

    def escape_toward_center(self, threat_position, seconds):
        player = self.call("state").get("player") or {}
        position = player.get("position", [self.arena_center[0], 0, self.arena_center[1]])
        away = (position[0] - threat_position[0], position[2] - threat_position[2])
        center = (self.arena_center[0] - position[0], self.arena_center[1] - position[2])
        away_length = math.hypot(*away) or 1.0
        center_length = math.hypot(*center) or 1.0
        direction = (away[0] / away_length + 0.9 * center[0] / center_length,
                     away[1] / away_length + 0.9 * center[1] / center_length)
        self.call("look-at", position[0] + direction[0] * 5, position[1] + 1.6, position[2] + direction[1] * 5)
        self.call("move", "forward", seconds, "--sprint")
        self.aimed_spot = None

    def eat_golden_apple(self, threat_position):
        if threat_position:
            self.escape_toward_center(threat_position, 0.6)
        counts, _ = self.inventory()
        for item in ("enchanted_golden_apple", "golden_apple"):
            if counts.get(f"minecraft:{item}", 0) > 0:
                self.call("select", item)
                reply = self.call("use-item", "--hold", EAT_SECONDS)
                self.note(f"ate {item}: {reply.get('inventory_change')}")
                self.current_item = None
                self.aimed_spot = None
                return True
        return False

    def settle_pending(self, target):
        if not self.pending_crystal:
            return
        bucket, spot, health_before, target_id = self.pending_crystal
        self.pending_crystal = None
        health_now = target.get("health", 0.0) if target and target["id"] == target_id else 0.0
        damage = max(0.0, (health_before or 0.0) - (health_now or 0.0))
        self.memory.record_placement(bucket, damage)
        self.damage_dealt += damage
        self.failed_spots[spot] = 0 if damage > 0.05 else self.failed_spots.get(spot, 0) + 1

    def run(self):
        self.note(f"parameters this fight: {self.parameters}")
        cycle = 0
        last_health = None
        won = died = False
        while time.time() - self.started < self.time_limit:
            cycle_start = time.time()
            cycle += 1
            state = self.call("state")
            player = state.get("player") or {}
            health = player.get("health", 0.0) + player.get("absorption", 0.0)
            if last_health is not None and health < last_health:
                self.damage_taken += last_health - health
            last_health = health
            if player.get("health", 0) <= 0 or state.get("screen") == "death":
                died = True
                self.note("I died")
                break
            self.ensure_offhand_totem()
            target = self.nearest_target()
            self.settle_pending(target)
            if not target:
                won = True
                self.note("target dead")
                break
            if health <= self.parameters["eat_health"] and time.time() - self.last_eat > 3:
                if self.eat_golden_apple(target["pos"]):
                    self.last_eat = time.time()
                    last_health = None
                    continue
            eye = player["eye"]
            horizontal = math.dist((eye[0], eye[2]), (target["pos"][0], target["pos"][2]))
            if horizontal > PREFERRED_RANGE[1]:
                self.call("look-at", "entity", target["id"])
                self.call("move", "forward", 0.25, "--sprint")
                self.aimed_spot = None
                continue
            if horizontal < PREFERRED_RANGE[0]:
                self.escape_toward_center(target["pos"], 0.3)
                continue
            now = time.time()
            predicted = list(target["pos"])
            moving = False
            if self.previous_sample and self.previous_sample[0] == target["id"] and now - self.previous_sample[1] < 1.5:
                elapsed = max(0.05, now - self.previous_sample[1])
                velocity = [(target["pos"][axis] - self.previous_sample[2][axis]) / elapsed for axis in range(3)]
                moving = math.hypot(velocity[0], velocity[2]) > 0.5
                for axis in (0, 2):
                    predicted[axis] += velocity[axis] * LEAD_SECONDS
            self.previous_sample = (target["id"], now, target["pos"])
            self.prefetch_blocks(predicted)
            chosen = None
            for spot, bucket in self.candidate_spots(predicted, eye, moving):
                status = self.usable(spot)
                if status:
                    chosen = (spot, bucket, status)
                    break
            if not chosen:
                self.call("look-at", "entity", target["id"])
                self.call("move", "left" if cycle % 2 else "right", 0.25)
                self.aimed_spot = None
                continue
            spot, bucket, status = chosen
            if status == "needs_obsidian":
                reply = self.call("place", *spot, "--item", "obsidian")
                self.current_item = "obsidian"
                self.aimed_spot = None
                if not reply.get("ok"):
                    self.failed_spots[spot] = 2
                    continue
            if self.current_item != "end_crystal":
                self.call("select", "end_crystal")
                self.current_item = "end_crystal"
            if self.aimed_spot != spot:
                self.call("look-at", spot[0] + 0.5, spot[1] + 1.0, spot[2] + 0.5)
                self.aimed_spot = spot
            self.call("mouse", "right", "click")
            time.sleep(self.parameters["place_to_break_delay"])
            self.call("mouse", "left", "click")
            self.crystals += 1
            self.pending_crystal = (bucket, spot, target.get("health"), target["id"])
            self.note(f"crystal {self.crystals} {bucket}: target {target.get('health', 0):.1f} | me {health:.1f}")
            time.sleep(max(0.0, CYCLE_SECONDS - (time.time() - cycle_start)))
        if not won and not died and not self.nearest_target():
            won = True
        seconds = time.time() - self.started
        score = self.memory.record_fight(self.parameters, self.damage_dealt, self.damage_taken, seconds, won,
                                         died, self.totems_popped)
        self.memory.save()
        events = [line for line in self.log if " crystal " not in line]
        print("\n".join(events + [line for line in self.log if " crystal " in line][-4:]))
        print(f"result: {'WIN' if won else 'DIED' if died else 'TIMEOUT'} crystals={self.crystals} "
              f"dealt={self.damage_dealt:.1f} taken={self.damage_taken:.1f} totems={self.totems_popped} "
              f"time={seconds:.1f}s score={score:.1f}")
        print("memory:\n" + self.memory.summary())


def main():
    parser = argparse.ArgumentParser(description="Crystal PvP fighter for NX Horizon that learns from every fight")
    parser.add_argument("--target", default="zombie")
    parser.add_argument("--time", type=float, default=75.0)
    parser.add_argument("--arena-center", type=float, nargs=2, default=(1000.5, 1000.5))
    arguments = parser.parse_args()
    CrystalFighter(arguments.target, arguments.time, tuple(arguments.arena_center)).run()


if __name__ == "__main__":
    main()
