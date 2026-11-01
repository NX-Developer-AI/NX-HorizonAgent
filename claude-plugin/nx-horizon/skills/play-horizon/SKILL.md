---
name: play-horizon
description: Play and control NX Horizon (Minecraft Java 26.3 in Rust, Android) through the horizon MCP server. Use when the user asks Claude to play, move, mine, build, fight, open menus, press keys or test something in their running NX Horizon game.
---

# Playing NX Horizon

The `horizon` MCP server (tools named `mcp__plugin_nx-horizon_horizon__*`) drives the user's running NX Horizon game over a localhost TCP endpoint. The game must be open with **Horizon Settings > AI Agent > Agent Control: On**.

## Loop

1. **Observe first:** `state` (player, world, screen, crosshair target). Use `screenshot` when the scene matters; it returns the frame as an image.
2. **Act in small steps:** one action, then check its result with `state`, `events --since SEQ`, or a screenshot.
3. **Wait instead of guessing:** take `events` `last` before an action and use `wait_for` with `--since` afterwards.

## Useful tools

| Goal | Tools |
| --- | --- |
| Where am I, what do I see | `state`, `looking_at`, `entities`, `find_block`, `blocks`, `screenshot` |
| Move and look | `move`, `goto`, `jump`, `look`, `turn`, `look_at`, `look_at_block`, `look_at_entity` |
| Interact | `break`, `place`, `interact`, `use_item`, `attack`, `select`, `drop` |
| Raw input | `key` (any key, held or tapped), `mouse`, `click_at`, `drag_at`, `scroll_at`, `pad` |
| Menus and screens | `ui`, `click`, `set`, `type`, `screen`, `inventory`, `click_slot`, `pause`, `resume` |
| Chat and commands | `messages`, `chat`, `command` (only when the user asks) |

## Rules

- `world_delete`, `fill` and `setblock` destroy things: ask the user first and pass `confirm` only after they agree.
- `chat`, `command`, `connect`, `lan`, `friends` reach other players or servers: only when the user asks.
- If a tool answers with `kind: connection`, the game is closed or Agent Control is off: tell the user to open NX Horizon and turn it on.
- Reply to the user in the language they use.
