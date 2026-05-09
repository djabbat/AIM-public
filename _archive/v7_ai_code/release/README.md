# release/ — AIM distribution packaging

Two packaging tracks:

1. **Source-tarball** (`build_packages.sh`) — sources only, recipient
 rebuilds via cargo + mix. Used for sharing development snapshots.
2. **Pre-built portable** (`bundle_prebuilt.sh` + GitHub Actions
 `aim-release.yml`) — Rust binaries + Phoenix release with bundled
 ERTS. Recipient downloads, extracts, runs `install.sh` /
 `install.cmd`. **This is the "download-click-installed" path for
 end users.**

## Pre-built (recommended for distribution)

Triggered by pushing a tag `aim-v*`. The workflow runs `cargo build
--release` + `mix release` on three OS-runners (ubuntu / macos /
windows), then `bundle_prebuilt.sh <platform>` packs the artefacts
plus a per-OS setup script:

- `aim-<VERSION>-x86_64-linux.tar.gz` → `./install.sh` → systemd user units
- `aim-<VERSION>-x86_64-macos.tar.gz` → `./install.sh` → launchd LaunchAgents
- `aim-<VERSION>-x86_64-windows.zip` → double-click `install.cmd` → Scheduled Tasks

Artefacts are uploaded to the GitHub Release for the tag. Users grab
them from the Releases page — no toolchain needed at install time.

## Source-tarball (legacy / dev share)

Builds three platform-specific archives:
- `aim-<VERSION>-linux.tar.gz`
- `aim-<VERSION>-macos.tar.gz`
- `aim-<VERSION>-windows.zip`

Each archive contains a self-contained AIM source tree (no venv, no
build artefacts, no patient data, no DBs) plus a platform-specific
`README-INSTALL.txt` with the right install command.

## Build

```bash
./release/build_packages.sh # → release/dist/ (full source, internal docs included)
./release/build_packages.sh --public # → release/dist-public/ (CONCEPT/CLAUDE/TODO/PARAMETERS removed)
```

`release/dist/` and `release/dist-public/` are gitignored — binaries
are distributed via **GitHub Releases**, not committed to history.

## Publish

```bash
# Private (full) — to djabbat/AIM
gh release create v$(cat release/VERSION) \
 --repo djabbat/AIM \
 --title "AIM v$(cat release/VERSION)" \
 --notes-file release/RELEASE_NOTES.md \
 release/dist/aim-*

# Public (sanitised) — to djabbat/AIM-public
gh release create v$(cat release/VERSION) \
 --repo djabbat/AIM-public \
 --title "AIM v$(cat release/VERSION)" \
 --notes-file release/RELEASE_NOTES.md \
 release/dist-public/aim-*
```

After release, the OS-detection block on hive.longevity.ge points
users to `https://github.com/djabbat/LongevityCommon-public` for
source clone or to the GitHub Releases page for direct download.

## Versioning

`release/VERSION` is the canonical version string. Bump it before
each release. Format: `MAJOR.MINOR.PATCH`.
