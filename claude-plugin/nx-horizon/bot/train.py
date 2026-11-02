import argparse
import random
import threading
import time

from crystal_fighter import CrystalFighter
from horizon_client import Horizon

ARMOR_PIECES = {"head": "helmet", "chest": "chestplate", "legs": "leggings", "feet": "boots"}


def target_equipment():
    pieces = [f'{slot}:{{id:"minecraft:netherite_{name}",count:1,components:{{"minecraft:enchantments":{{"minecraft:protection":4}}}}}}'
              for slot, name in ARMOR_PIECES.items()]
    return ",".join(pieces)


def reset_round(horizon, center, moving):
    x, y, z = center
    commands = [
        "time set day", "gamemode survival", "difficulty normal", "kill @e[type=!player]",
        f"fill {x - 10} {y} {z - 10} {x + 10} {y + 8} {z + 10} minecraft:air",
        "clear @s", "effect clear @s", "effect give @s minecraft:instant_health 1 5", "effect give @s minecraft:saturation 1 20 true",
        "item replace entity @s armor.head with netherite_helmet[enchantments={protection:4}]",
        "item replace entity @s armor.chest with netherite_chestplate[enchantments={blast_protection:4}]",
        "item replace entity @s armor.legs with netherite_leggings[enchantments={blast_protection:4}]",
        "item replace entity @s armor.feet with netherite_boots[enchantments={protection:4}]",
        "item replace entity @s weapon.offhand with totem_of_undying",
        "give @s netherite_sword", "give @s obsidian 64", "give @s end_crystal 64", "give @s golden_apple 16",
        "give @s totem_of_undying 6",
        f"tp @s {x - 6 + 0.5} {y} {z + 0.5} -90 10",
        f"summon minecraft:zombie {x + 4 + 0.5} {y} {z + random.choice([-2, 0, 2]) + 0.5} "
        f"{{PersistenceRequired:1b,{'' if moving else 'NoAI:1b,'}equipment:{{{target_equipment()}}}}}",
    ]
    for command in commands:
        reply = horizon("command", command)
        if reply.get("error"):
            print(f"setup error: {command[:50]}: {reply['error']}")
    time.sleep(0.6)


def pressure(stop, damage, interval, damage_type):
    connection = Horizon()
    while not stop.wait(interval * random.uniform(0.7, 1.3)):
        connection("command", f"damage @s {damage * random.uniform(0.6, 1.4):.1f} minecraft:{damage_type}")


def main():
    parser = argparse.ArgumentParser(description="Train the NX Horizon crystal fighter over several rounds")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--time", type=float, default=60.0)
    parser.add_argument("--center", type=int, nargs=3, default=(1000, 150, 1000))
    parser.add_argument("--still", action="store_true", help="target does not move")
    parser.add_argument("--pressure", type=float, default=0.0, help="simulated enemy crystal damage per hit (0 = off)")
    parser.add_argument("--pressure-interval", type=float, default=2.5)
    parser.add_argument("--pressure-type", default="explosion", help="damage type, e.g. explosion or generic")
    arguments = parser.parse_args()
    horizon = Horizon()
    for round_number in range(1, arguments.rounds + 1):
        print(f"\n=== round {round_number}/{arguments.rounds} ===")
        reset_round(horizon, arguments.center, not arguments.still)
        stop = threading.Event()
        worker = None
        if arguments.pressure > 0:
            worker = threading.Thread(target=pressure, args=(stop, arguments.pressure, arguments.pressure_interval,
                                                         arguments.pressure_type), daemon=True)
            worker.start()
        try:
            center = (arguments.center[0] + 0.5, arguments.center[2] + 0.5)
            CrystalFighter("zombie", arguments.time, center).run()
        finally:
            stop.set()
        time.sleep(1.0)


if __name__ == "__main__":
    main()
