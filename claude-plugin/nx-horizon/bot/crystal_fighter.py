import argparse
import math
import time

from crystal_memory import CrystalMemory
from horizon_client import Horizon

REACH = 4.3
CYCLE_SECONDS = 0.35
EAT_SECONDS = 1.65
PREFERRED_RANGE = (1.3, 4.0)
LEAD_SECONDS = 0.2
LEARNED_WEIGHT = 0.8
SWORD_COOLDOWN = 0.65
MAX_CRYSTAL_DAMAGE = 20.0
SAFE_EAT_DISTANCE = 6.0
ESCAPE_SECONDS = 2.5
DESPERATE_HEALTH = 5.0
EXISTING_OBSIDIAN_BONUS = 1.2


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
        self.last_hit = 0.0
        self.branch_time = {}
        self.target_killed = False
        self.last_damage_seen = 0.0
        self.melee_mode = False
        self.melee_hits = 0
        self.counts = {}
        self.own_obsidian = set()
        self.reused = 0
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
                    existing = self.block_at(*spot) in ("minecraft:obsidian", "minecraft:bedrock")
                    reuse_bonus = EXISTING_OBSIDIAN_BONUS if existing else 0.0
                    score = (to_target - 0.25 * to_me - LEARNED_WEIGHT * learned
                             - (0.3 if offset_y == 0 else 0.0) - reuse_bonus)
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
        if self.target_type != "player":
            targets = self.call("entities", 16, self.target_type).get("entities", [])
            return targets[0] if targets else None
        status = self.call("lan", "status")
        host = status.get("host")
        me = (self.call("state").get("player") or {}).get("position")
        players = []
        self.target_far = False
        for guest in status.get("guests", []):
            if guest.get("name") == host or not guest.get("loaded"):
                continue
            if guest.get("health", 0) <= 0 or guest.get("game_mode") not in (0, 2):
                continue
            distance = math.dist(me, guest["position"]) if me else 0.0
            if distance > 24:
                self.target_far = True
                continue
            players.append({"id": guest["name"], "pos": guest["position"], "distance": distance,
                            "health": guest.get("health", 0.0) + guest.get("absorption", 0.0),
                            "hurt_time": None, "kind": "player"})
        players.sort(key=lambda entry: entry["distance"])
        return players[0] if players else None

    def face(self, target):
        if target.get("kind") == "player":
            position = target["pos"]
            self.call("look-at", position[0], position[1] + 1.2, position[2])
        else:
            self.call("look-at", "entity", target["id"])

    def strike(self, target):
        if target.get("kind") != "player":
            return self.call("attack", target["id"])
        before = target.get("health")
        self.call("mouse", "left", "click")
        time.sleep(0.08)
        after_target = self.nearest_target()
        after = after_target.get("health") if after_target else 0.0
        return {"hit": after is not None and before is not None and after < before, "health_before": before,
                "health": after, "alive": bool(after_target) and (after or 0) > 0}

    def inventory(self):
        inventory = self.call("inventory")
        return inventory.get("counts", {}), (inventory.get("offhand") or {}).get("item")

    def ensure_offhand_totem(self):
        counts, offhand = self.inventory()
        self.counts = counts
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

    def distance_to(self, position):
        me = (self.call("state").get("player") or {}).get("position")
        return math.hypot(me[0] - position[0], me[2] - position[2]) if me else 0.0

    def eat_golden_apple(self, threat_position, health):
        if threat_position:
            escape_started = time.time()
            safe = False
            while time.time() - escape_started < ESCAPE_SECONDS:
                threat = self.nearest_target()
                if not threat:
                    safe = True
                    break
                if self.distance_to(threat["pos"]) >= SAFE_EAT_DISTANCE:
                    safe = True
                    break
                self.escape_toward_center(threat["pos"], 0.4)
            if not safe and health > DESPERATE_HEALTH:
                self.note("could not get away to eat: keep fighting")
                return False
            if not safe:
                self.note("cornered and low: eating anyway")
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

    def target_alive(self, target_id):
        target = self.nearest_target()
        return bool(target) and target["id"] == target_id and (target.get("health") or 0) > 0

    def place_and_pop(self, predicted, eye, target_id, bucket_side=None, moving=False):
        self.prefetch_blocks(predicted)
        for spot, bucket in self.candidate_spots(predicted, eye, moving):
            status = self.usable(spot)
            if not status:
                continue
            if status == "needs_obsidian":
                reply = self.call("place", *spot, "--item", "obsidian")
                self.current_item = "obsidian"
                self.aimed_spot = None
                if not reply.get("ok"):
                    self.failed_spots[spot] = 2
                    continue
                self.own_obsidian.add(spot)
            if self.current_item != "end_crystal":
                self.call("select", "end_crystal")
                self.current_item = "end_crystal"
            if self.aimed_spot != spot:
                self.call("look-at", spot[0] + 0.5, spot[1] + 1.0, spot[2] + 0.5)
                self.aimed_spot = spot
            if not self.target_alive(target_id):
                self.target_killed = True
                return None, None
            self.call("mouse", "right", "click")
            time.sleep(self.parameters["place_to_break_delay"])
            self.call("mouse", "left", "click")
            self.crystals += 1
            if bucket_side:
                distance_part = bucket.split("|")[0]
                bucket = f"{distance_part}|{bucket_side}|{'moving' if moving else 'still'}"
            return spot, bucket
        return None, None

    def knockback_combo(self, target):
        if self.current_item != "sword":
            self.call("select", "netherite_sword")
            self.current_item = "sword"
        self.face(target)
        self.call("move", "forward", 0.12, "--sprint")
        self.face(target)
        hit = self.strike(target)
        self.last_hit = time.time()
        self.aimed_spot = None
        health_after_hit = hit.get("health", target.get("health"))
        if hit.get("health_before") is not None and health_after_hit is not None:
            self.damage_dealt += max(0.0, hit["health_before"] - health_after_hit)
        if not hit.get("hit"):
            self.note("knockback swing missed")
            return
        if hit.get("alive") is False:
            self.target_killed = True
            self.note("target killed by the sword hit: no crystal needed")
            return
        first_position = target["pos"]
        time.sleep(0.12)
        flying = self.nearest_target()
        if not flying:
            return
        elapsed = max(0.05, time.time() - self.last_hit)
        velocity = [(flying["pos"][axis] - first_position[axis]) / elapsed for axis in range(3)]
        lead = self.parameters["knockback_lead"]
        predicted = [flying["pos"][0] + velocity[0] * lead, first_position[1], flying["pos"][2] + velocity[2] * lead]
        player = self.call("state").get("player") or {}
        spot, bucket = self.place_and_pop(predicted, player.get("eye", first_position), flying["id"], "knock", True)
        if spot:
            self.pending_crystal = (bucket, spot, flying.get("health"), flying["id"])
            self.note(f"knockback combo: hit {hit.get('health_before', 0):.1f}->{health_after_hit or 0:.1f}, "
                      f"flew {math.hypot(velocity[0], velocity[2]):.1f} b/s, crystal at {spot}")
        else:
            self.note("knockback combo: no crystal spot near landing point")

    def melee(self, target, horizontal, cycle):
        if self.current_item != "sword":
            self.call("select", "netherite_sword")
            self.current_item = "sword"
            self.aimed_spot = None
        self.face(target)
        if horizontal > 3.0:
            self.call("move", "forward", 0.2, "--sprint")
            return
        if target.get("hurt_time") is None:
            vulnerable = time.time() - self.last_damage_seen >= 0.5
        else:
            vulnerable = (target.get("hurt_time") or 0) <= 1
        if vulnerable and time.time() - self.last_hit >= SWORD_COOLDOWN:
            self.call("move", "forward", 0.08, "--sprint")
            self.face(target)
            hit = self.strike(target)
            self.last_hit = time.time()
            if hit.get("hit"):
                self.last_damage_seen = time.time()
                self.damage_dealt += max(0.0, (hit.get("health_before") or 0) - (hit.get("health") or 0))
                self.melee_hits += 1
            if hit.get("alive") is False:
                self.target_killed = True
            return
        self.call("move", "left" if cycle % 4 < 2 else "right", 0.15)

    def settle_pending(self, target):
        if not self.pending_crystal:
            return
        bucket, spot, health_before, target_id = self.pending_crystal
        self.pending_crystal = None
        health_now = target.get("health", 0.0) if target and target["id"] == target_id else 0.0
        damage = min(MAX_CRYSTAL_DAMAGE, max(0.0, (health_before or 0.0) - (health_now or 0.0)))
        self.memory.record_placement(bucket, damage)
        self.damage_dealt += damage
        if damage > 0.05:
            self.last_damage_seen = time.time()
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
                if getattr(self, "target_far", False):
                    self.note("target left the arena alive: stopping without a result")
                    break
                won = True
                self.note("target dead")
                break
            if health <= self.parameters["eat_health"] and time.time() - self.last_eat > 3:
                if self.eat_golden_apple(target["pos"], health):
                    self.last_eat = time.time()
                    last_health = None
                    continue
                self.last_eat = time.time() - 1.5
            eye = player["eye"]
            horizontal = math.dist((eye[0], eye[2]), (target["pos"][0], target["pos"][2]))
            if (self.counts.get("minecraft:end_crystal", 0) == 0
                    or (self.counts.get("minecraft:obsidian", 0) == 0 and not self.own_obsidian)):
                if not self.melee_mode:
                    self.melee_mode = True
                    self.note("out of crystals or obsidian: switching to the sword")
                self.melee(target, horizontal, cycle)
                continue
            if horizontal > PREFERRED_RANGE[1]:
                self.face(target)
                self.branch_time["approach"] = self.branch_time.get("approach", 0) + 1
                self.call("move", "forward", 0.25, "--sprint")
                self.aimed_spot = None
                continue
            if target.get("hurt_time") is None:
                target_vulnerable = time.time() - self.last_damage_seen >= 0.5
            else:
                target_vulnerable = (target.get("hurt_time") or 0) <= 1
            if (horizontal <= self.parameters["melee_trigger"] and target_vulnerable
                    and time.time() - self.last_hit >= SWORD_COOLDOWN):
                self.branch_time["combo"] = self.branch_time.get("combo", 0) + 1
                self.knockback_combo(target)
                if self.target_killed:
                    won = True
                    self.note("target dead")
                    break
                time.sleep(max(0.0, CYCLE_SECONDS - (time.time() - cycle_start)))
                continue
            if horizontal < PREFERRED_RANGE[0]:
                self.branch_time["escape"] = self.branch_time.get("escape", 0) + 1
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
                self.face(target)
                self.branch_time["no_spot"] = self.branch_time.get("no_spot", 0) + 1
                self.call("move", "left" if cycle % 2 else "right", 0.25)
                self.aimed_spot = None
                continue
            spot, bucket, status = chosen
            if status == "ready":
                self.reused += 1
            if not target_vulnerable:
                time.sleep(0.05 * max(0, (target.get("hurt_time") or 0) - 1))
            if status == "needs_obsidian":
                reply = self.call("place", *spot, "--item", "obsidian")
                self.current_item = "obsidian"
                self.aimed_spot = None
                if not reply.get("ok"):
                    self.failed_spots[spot] = 2
                    continue
                self.own_obsidian.add(spot)
            if self.current_item != "end_crystal":
                self.call("select", "end_crystal")
                self.current_item = "end_crystal"
            if self.aimed_spot != spot:
                self.call("look-at", spot[0] + 0.5, spot[1] + 1.0, spot[2] + 0.5)
                self.aimed_spot = spot
            if not self.target_alive(target["id"]):
                self.target_killed = True
                won = True
                self.note("target died before the crystal: skipped it")
                break
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
        print(f"melee hits: {self.melee_hits}")
        print(f"branches: {self.branch_time} obsidian placed {len(self.own_obsidian)}, reused {self.reused}")
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
