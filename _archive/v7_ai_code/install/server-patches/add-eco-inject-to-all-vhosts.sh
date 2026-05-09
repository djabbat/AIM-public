#!/usr/bin/env bash
# Add eco-inject + hive-button include to vhosts that don't have it.
# Inserted right before the closing `}` of the `location /` block.
set -e

INCLUDES='        include /etc/nginx/snippets/eco-inject.conf;
        include /etc/nginx/snippets/hive-button.conf;'

patch_vhost() {
    local file="$1"
    if grep -q 'include.*eco-inject' "$file"; then
        echo "  ✓ already has eco-inject: $(basename "$file")"
        return
    fi
    if ! grep -q 'location / {' "$file"; then
        echo "  ⚠ no 'location / {' block: $(basename "$file")"
        return
    fi

    # Insert includes before the closing brace of the FIRST `location / {` block.
    # awk: track when we see "location / {", count braces, insert before matching `}`.
    awk -v inc="$INCLUDES" '
    BEGIN { in_root=0; depth=0; inserted=0 }
    /location \/ \{/ && !inserted { in_root=1; depth=1; print; next }
    in_root {
        depth += gsub(/\{/, "&", $0)
        depth -= gsub(/\}/, "&", $0)
        if (depth == 0) {
            print inc
            in_root=0
            inserted=1
        }
        print
        next
    }
    { print }
    ' "$file" > "$file.new" && mv "$file.new" "$file"
    echo "  ✓ patched: $(basename "$file")"
}

for f in /etc/nginx/sites-enabled/cdata.longevity.ge.conf \
         /etc/nginx/sites-enabled/mcoa.longevity.ge.conf \
         /etc/nginx/sites-enabled/hive.longevity.ge \
         /etc/nginx/sites-enabled/app.longevity.ge.conf \
         /etc/nginx/sites-enabled/aim.longevity.ge; do
    [[ -f "$f" ]] && patch_vhost "$f"
done

nginx -t && systemctl reload nginx && echo "OK"
