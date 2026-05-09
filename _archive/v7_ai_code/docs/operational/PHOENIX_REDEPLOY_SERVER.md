# Phoenix redeploy on server — manual steps required

**Status:** 2026-05-07 — admin link added in local UI + synced to server
clone, но prod release **not rebuilt** (server Elixir 1.14 < required 1.15).

## Что готово (sync done)

Server clone `/home/jaba/web/aim/AIM` имеет свежие файлы:
- `phoenix-umbrella/apps/aim_web/lib/aim_web_web/live/admin_live.ex`
- `phoenix-umbrella/apps/aim_web/lib/aim_web_web/router.ex` (+`/admin` route)
- `phoenix-umbrella/apps/aim_web/lib/aim_web_web/components/layouts/app.html.heex` (+ Admin nav link)
- `phoenix-umbrella/apps/aim_web/lib/aim_web_web/live/home_live.ex` (+ Admin nav link)

Active prod release `/opt/aim/phoenix/` всё ещё содержит **старый** код
(без /admin). aim-phoenix.service running, serves `https://aim.longevity.ge`.

## Blocker

Server Elixir 1.14.0 / OTP 25. Phoenix 1.8.5 requires Elixir ≥ 1.15.
Existing release was compiled на dev машине с newer toolchain и shipped.

## Что нужно сделать (manual)

### Option A — Bump server Elixir to 1.17

```bash
# On server (jaba@server):
# 1. Install asdf if missing
git clone https://github.com/asdf-vm/asdf.git ~/.asdf
echo '. ~/.asdf/asdf.sh' >> ~/.zshrc && exec zsh

# 2. Install Erlang 27 + Elixir 1.17
asdf plugin add erlang
asdf plugin add elixir
asdf install erlang 27.1
asdf install elixir 1.17.3-otp-27
asdf global erlang 27.1
asdf global elixir 1.17.3-otp-27
elixir --version

# 3. Rebuild + redeploy
cd /home/jaba/web/aim/AIM/phoenix-umbrella
MIX_ENV=prod mix deps.get --only prod
MIX_ENV=prod mix release aim_web --overwrite

# 4. Replace /opt/aim/phoenix with new release
sudo systemctl stop aim-phoenix
sudo /usr/bin/cp -a _build/prod/rel/aim_web/. /opt/aim/phoenix/
sudo /usr/bin/chown -R jaba:jaba /opt/aim/phoenix
sudo systemctl start aim-phoenix
sudo systemctl status aim-phoenix

# 5. Smoke
curl -sS https://aim.longevity.ge/admin -o /dev/null -w "%{http_code}\n"
# Expected: 200
```

### Option B — Build release on dev x86_64 + repackage erts for aarch64

Сложнее (cross-compile erts). Не рекомендуется.

### Option C — Запустить /admin через docker container с правильным Elixir

Нарушает rule «no Docker» (`STACK.md`). Не делать.

## After redeploy

- `https://aim.longevity.ge/admin` → AdminLive control panel
- Mutating actions disabled by default. To enable:
 ```bash
 echo 'AIM_ADMIN_ENABLE=1' | sudo tee -a /etc/aim/aim_phoenix.env
 sudo systemctl restart aim-phoenix
 ```
 (или addr через .env, который EnvironmentFile грузит в unit)

## Rollback (if /admin breaks production)

```bash
sudo systemctl stop aim-phoenix
sudo /usr/bin/cp -a /opt/aim/phoenix.backup-2026-05-07/. /opt/aim/phoenix/
sudo systemctl start aim-phoenix
```

(Pre-redeploy: `sudo /usr/bin/cp -a /opt/aim/phoenix /opt/aim/phoenix.backup-$(date +%F)`)
