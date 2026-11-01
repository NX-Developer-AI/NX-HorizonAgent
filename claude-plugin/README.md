# NX Horizon — Claude Code plugin

## Türkçe

NX Horizon (Horizon Android fork'u) oyununu Claude Code'dan yönetmeyi sağlar. Oyun, Agent Control açıldığında
`127.0.0.1` üzerinde token korumalı bir TCP portu açar ve bağlantı bilgisini
`/storage/emulated/0/Android/obb/dev.horizon.android.nx/horizon-control.json` dosyasına yazar. Bu klasör Termux
tarafından okunabildiği için eklentideki `horizon-ctl mcp` oyuna bağlanabilir.

### Kurulum

1. Actions'tan `NX-Horizon-arm64-v8a.apk` dosyasını indir ve kur (resmi Horizon'un yanına ayrı uygulama olarak kurulur).
2. NX Horizon'u aç → Horizon Settings → AI Agent → **Agent Control: On**.
3. Claude Code'da:
   ```
   /plugin marketplace add /root/NX-HorizonAgent/claude-plugin
   /plugin install nx-horizon@nx-team
   ```
4. Claude Code'u yeniden başlat. `horizon-ctl` ilk çalıştırmada `gh` ile indirilir.

Ortam değişkenleri: `NX_HORIZON_ENDPOINT`, `NX_HORIZON_PACKAGE`, `NX_HORIZON_CTL`, `NX_HORIZON_HOME`.

## English

Drives NX Horizon (a Horizon Android fork) from Claude Code. With Agent Control on, the game listens on a
token-protected TCP port on `127.0.0.1` and writes the endpoint to
`/storage/emulated/0/Android/obb/dev.horizon.android.nx/horizon-control.json`. Termux can read that folder, so the
plugin's `horizon-ctl mcp` reaches the game.

### Setup

1. Download `NX-Horizon-arm64-v8a.apk` from Actions and install it (it installs next to the official Horizon).
2. Open NX Horizon → Horizon Settings → AI Agent → **Agent Control: On**.
3. In Claude Code:
   ```
   /plugin marketplace add /root/NX-HorizonAgent/claude-plugin
   /plugin install nx-horizon@nx-team
   ```
4. Restart Claude Code. `horizon-ctl` is downloaded with `gh` on first run.

Environment variables: `NX_HORIZON_ENDPOINT`, `NX_HORIZON_PACKAGE`, `NX_HORIZON_CTL`, `NX_HORIZON_HOME`.
