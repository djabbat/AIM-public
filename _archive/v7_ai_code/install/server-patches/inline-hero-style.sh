#!/usr/bin/env bash
# Bake inline indigo gradient + white text into the home <section class="hero">
# tag so the GLA banner stays branded in BOTH light and dark themes,
# regardless of any CSS cascade. Runs idempotently — safe to re-run.
#
# Why inline: the dark-mode CSS overrides on *.longevity.ge (via
# eco-inject.js) sometimes won the cascade against `.hero { color: white }`
# even with `!important`. Inline `style="..."` on the element wins
# unconditionally.
#
# Usage on the server:
#   sudo /home/jaba/web/aim/AIM/install/server-patches/inline-hero-style.sh

set -e

INLINE_STYLE='style="background:linear-gradient(135deg,#1e1b4b 0%,#312e81 35%,#4338ca 75%,#6366f1 100%);color:#fff;"'
TARGETS=(
    /home/jaba/web/ngo/index.html
    /home/jaba/web/ngo/about/index.html
    /home/jaba/web/ngo/team/index.html
    /home/jaba/web/ngo/research/index.html
    /home/jaba/web/ngo/publications/index.html
    /home/jaba/web/ngo/grants/index.html
    /home/jaba/web/ngo/contact/index.html
)

for f in "${TARGETS[@]}"; do
    [[ -f "$f" ]] || continue
    if grep -q '<section class="hero">' "$f"; then
        sed -i "s|<section class=\"hero\">|<section class=\"hero\" $INLINE_STYLE>|g" "$f"
        echo "  patched: $f"
    elif grep -q '<section class="hero" style=' "$f"; then
        echo "  already patched: $f"
    fi
done
