#!/bin/bash
# distill_cron.sh — daily distill trigger for AIM Hive Queen.
#
# Place in ~/hive_queen/scripts/, then add to crontab on server:
#   crontab -e
#   17 4 * * * /home/jaba/hive_queen/scripts/distill_cron.sh

set -euo pipefail
ENV_FILE="$HOME/hive_queen/.env"
[[ -f "$ENV_FILE" ]] || { echo "no $ENV_FILE"; exit 1; }
# shellcheck disable=SC1090
source "$ENV_FILE"

curl -sX POST \
  -H "Authorization: Bearer ${AIM_HIVE_ADMIN_TOKEN}" \
  -H "Content-Type: application/json" \
  https://hive.longevity.ge/v1/hive/distill 2>&1 | tee -a "$HOME/hive_queen/distill.log"
