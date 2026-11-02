import argparse
import math
import time

from horizon_client import Horizon

REACH = 4.4
FLOOR_Y = 150


class Juggler:
    def __init__(self, duration, break_delay):
        self.horizon = Horizon()
        self.duration = duration
        self.break_delay = break_delay
        self.blocks = {}
        self.current_item = None
        self.aimed = None
        self.max_height = 0.0
        self.crystals = 0
        self.obsidian = 0
        self.pillar_tops = []
        self.previous = None

    def call(self, *words):
        return self.horizon(*words)

    def refresh_blocks(self, center):
        low = (math.floor(center[0]) - 2, FLOOR_Y, math.floor(center[2]) - 2)
        high = (math.floor(center[0]) + 2, math.floor(center[1]) + 3, math.floor(center[2]) + 2)
        self.blocks = {(b[0], b[1], b[2]): b[3].split("[")[0] for b in self.call("blocks", *low, *high).get("blocks", [])}

    def block(self, x, y, z):
        return self.blocks.get((x, y, z), "minecraft:air")

    def target(self):
        found = self.call("entities", 24, "zombie").get("entities", [])
        return found[0] if found else None

    def select(self, item, hotbar_name):
        if self.current_item != item:
            self.call("select", hotbar_name)
            self.current_item = item
            self.aimed = None

    def plan(self, predicted, eye):
        base_y = max(FLOOR_Y - 1, math.floor(predicted[1]) - 1)
        options = []
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                x = math.floor(predicted[0]) + dx
                z = math.floor(predicted[2]) + dz
                center_x, center_z = x + 0.5, z + 0.5
                if abs(center_x - predicted[0]) < 0.75 and abs(center_z - predicted[2]) < 0.75 and dx == 0 and dz == 0:
                    continue
                aim = (center_x, base_y + 1.0, center_z)
                if math.dist(aim, eye) > REACH:
                    continue
                missing = [y for y in range(FLOOR_Y, base_y + 1) if self.block(x, y, z) == "minecraft:air"]
                if self.block(x, base_y + 1, z) != "minecraft:air" or self.block(x, base_y + 2, z) != "minecraft:air":
                    continue
                if base_y >= FLOOR_Y and self.block(x, base_y, z) not in ("minecraft:obsidian", "minecraft:air"):
                    continue
                cost = len(missing) + 0.3 * math.hypot(center_x - predicted[0], center_z - predicted[2])
                options.append((cost, (x, base_y, z), missing))
        options.sort()
        return options[0] if options else None

    def run(self):
        started = time.time()
        while time.time() - started < self.duration:
            zombie = self.target()
            if not zombie:
                print("zombie gone")
                break
            now = time.time()
            position = zombie["pos"]
            height = position[1] - FLOOR_Y
            self.max_height = max(self.max_height, height)
            velocity = (0.0, 0.0, 0.0)
            if self.previous and now - self.previous[0] < 0.5:
                elapsed = max(0.02, now - self.previous[0])
                velocity = tuple((position[i] - self.previous[1][i]) / elapsed for i in range(3))
            self.previous = (now, position)
            predicted = (position[0] + velocity[0] * 0.15, position[1] + max(-3.0, velocity[1]) * 0.15,
                         position[2] + velocity[2] * 0.15)
            player = self.call("state").get("player") or {}
            eye = player.get("eye")
            if not eye:
                continue
            horizontal = math.hypot(position[0] - eye[0], position[2] - eye[2])
            if horizontal > 3.6 and height < 1.0:
                self.call("look-at", "entity", zombie["id"])
                self.call("move", "forward", 0.15, "--sprint")
                self.aimed = None
                continue
            self.refresh_blocks(predicted)
            plan = self.plan(predicted, eye)
            if not plan:
                self.call("look-at", "entity", zombie["id"])
                self.call("move", "forward" if horizontal > 2.5 else "back", 0.1)
                self.aimed = None
                continue
            _, spot, missing = plan
            if missing:
                self.select("obsidian", "obsidian")
                for y in missing:
                    reply = self.call("place", spot[0], y, spot[2], "--item", "obsidian")
                    if not reply.get("ok"):
                        break
                    self.obsidian += 1
                    self.blocks[(spot[0], y, spot[2])] = "minecraft:obsidian"
                if spot[1] - FLOOR_Y + 1 > 1:
                    self.pillar_tops.append(spot[1] - FLOOR_Y + 1)
            self.select("crystal", "end_crystal")
            if self.aimed != spot:
                self.call("look-at", spot[0] + 0.5, spot[1] + 1.0, spot[2] + 0.5)
                self.aimed = spot
            self.call("mouse", "right", "click")
            time.sleep(self.break_delay)
            self.call("mouse", "left", "click")
            self.crystals += 1
        elapsed = time.time() - started
        print(f"result: {self.crystals} crystals in {elapsed:.1f}s ({self.crystals / elapsed:.1f}/s), "
              f"obsidian placed {self.obsidian}, highest zombie height {self.max_height:.1f} blocks above the floor, "
              f"tallest pillar {max(self.pillar_tops, default=1)} blocks")


def main():
    parser = argparse.ArgumentParser(description="Crystal juggling experiment: launch an immortal zombie as high as possible")
    parser.add_argument("--time", type=float, default=30.0)
    parser.add_argument("--break-delay", type=float, default=0.05)
    arguments = parser.parse_args()
    Juggler(arguments.time, arguments.break_delay).run()


if __name__ == "__main__":
    main()
