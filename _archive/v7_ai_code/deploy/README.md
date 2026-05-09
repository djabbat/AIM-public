# AIM deployment

## systemd

```sh
sudo cp deploy/systemd/aim-*.service /etc/systemd/system/
sudo cp deploy/systemd/aim.target /etc/systemd/system/
sudo systemctl daemon-reload

# Enable on boot
sudo systemctl enable aim.target

# Start everything
sudo systemctl start aim.target

# Status of one service
sudo systemctl status aim-llm

# Tail logs
journalctl -fu aim-doctor
```

## Hardening notes
- All units use `NoNewPrivileges=true` + `ProtectSystem=strict` + `PrivateTmp=true`.
- `ReadWritePaths` scoped to AIM project dir; aim-generalist scoped further to Patients/.
- Set `AIM_REQUIRE_AUTH=1` on Phoenix in prod (already in `aim-phoenix.service`).
- Set `AIM_ENV=prod` on Rust services to flip CORS to strict mode.
- Provide `~/.aim_env` with API keys (chmod 600). EnvironmentFile is optional (`-` prefix) so missing file won't fail startup.

## Build for prod

```sh
cd rust-core && cargo build --release
cd ../phoenix-umbrella && MIX_ENV=prod mix release
```
