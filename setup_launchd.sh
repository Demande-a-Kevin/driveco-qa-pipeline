#!/usr/bin/env bash
set -euo pipefail

PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_DIR="${LAUNCHD_RUNTIME_DIR:-$HOME/Library/Application Support/driveco-qa-pipeline/runtime}"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$RUNTIME_DIR/qa-driveco-data/logs"
SYNC_SCRIPT="$PIPELINE_DIR/sync_launchd_runtime.sh"
RUNNER="$RUNTIME_DIR/run_from_cron.sh"
WATCHDOG="$RUNTIME_DIR/run_daily_watchdog.sh"

BENCH_LABEL="com.kev1n.driveco.qa.benchmark"
DAILY_LABEL="com.kev1n.driveco.qa.daily"
WATCHDOG_LABEL="com.kev1n.driveco.qa.daily-watchdog"
WEEKLY_LABEL="com.kev1n.driveco.qa.weekly"
RELIABILITY_LABEL="com.kev1n.driveco.qa.reliability"
KB_CLUSTER_LABEL="com.kev1n.driveco.qa.kb-cluster"
KB_ARTICLES_INDEX_LABEL="com.kev1n.driveco.qa.kb-articles-index"
KB_ARTICLE_GAP_LABEL="com.kev1n.driveco.qa.kb-article-gap"
CSAT_INSIGHT_LABEL="com.kev1n.driveco.csat-insight"

BENCH_PLIST="$LAUNCH_AGENTS_DIR/${BENCH_LABEL}.plist"
DAILY_PLIST="$LAUNCH_AGENTS_DIR/${DAILY_LABEL}.plist"
WATCHDOG_PLIST="$LAUNCH_AGENTS_DIR/${WATCHDOG_LABEL}.plist"
WEEKLY_PLIST="$LAUNCH_AGENTS_DIR/${WEEKLY_LABEL}.plist"
RELIABILITY_PLIST="$LAUNCH_AGENTS_DIR/${RELIABILITY_LABEL}.plist"
KB_CLUSTER_PLIST="$LAUNCH_AGENTS_DIR/${KB_CLUSTER_LABEL}.plist"
KB_ARTICLES_INDEX_PLIST="$LAUNCH_AGENTS_DIR/${KB_ARTICLES_INDEX_LABEL}.plist"
KB_ARTICLE_GAP_PLIST="$LAUNCH_AGENTS_DIR/${KB_ARTICLE_GAP_LABEL}.plist"
CSAT_INSIGHT_PLIST="$LAUNCH_AGENTS_DIR/${CSAT_INSIGHT_LABEL}.plist"

PYTHON_BIN="$RUNTIME_DIR/.venv/bin/python"

BENCH_HOUR="${BENCH_HOUR:-1}"
BENCH_MINUTE="${BENCH_MINUTE:-30}"
DAILY_HOUR="${DAILY_HOUR:-1}"
DAILY_MINUTE="${DAILY_MINUTE:-0}"
WATCHDOG_HOUR="${WATCHDOG_HOUR:-6}"
WATCHDOG_MINUTE="${WATCHDOG_MINUTE:-45}"
WEEKLY_HOUR="${WEEKLY_HOUR:-7}"
WEEKLY_MINUTE="${WEEKLY_MINUTE:-15}"
WEEKLY_WEEKDAY="${WEEKLY_WEEKDAY:-1}"
RELIABILITY_HOUR="${RELIABILITY_HOUR:-4}"
RELIABILITY_MINUTE="${RELIABILITY_MINUTE:-0}"
RELIABILITY_WEEKDAY="${RELIABILITY_WEEKDAY:-1}"
KB_CLUSTER_HOUR="${KB_CLUSTER_HOUR:-3}"
KB_CLUSTER_MINUTE="${KB_CLUSTER_MINUTE:-30}"
KB_ARTICLES_INDEX_HOUR="${KB_ARTICLES_INDEX_HOUR:-4}"
KB_ARTICLES_INDEX_MINUTE="${KB_ARTICLES_INDEX_MINUTE:-0}"
KB_ARTICLE_GAP_HOUR="${KB_ARTICLE_GAP_HOUR:-4}"
KB_ARTICLE_GAP_MINUTE="${KB_ARTICLE_GAP_MINUTE:-15}"

mkdir -p "$LAUNCH_AGENTS_DIR" "$LOG_DIR"
chmod +x "$SYNC_SCRIPT"
"$SYNC_SCRIPT"
chmod +x "$RUNNER" "$WATCHDOG"

cat > "$BENCH_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${BENCH_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>benchmark</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${BENCH_HOUR}</integer>
    <key>Minute</key>
    <integer>${BENCH_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_benchmark.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_benchmark.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$DAILY_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${DAILY_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>daily</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${DAILY_HOUR}</integer>
    <key>Minute</key>
    <integer>${DAILY_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_daily.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_daily.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$WATCHDOG_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${WATCHDOG_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${WATCHDOG}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${WATCHDOG_HOUR}</integer>
    <key>Minute</key>
    <integer>${WATCHDOG_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_daily_watchdog.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_daily_watchdog.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$WEEKLY_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${WEEKLY_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>weekly</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>${WEEKLY_WEEKDAY}</integer>
    <key>Hour</key>
    <integer>${WEEKLY_HOUR}</integer>
    <key>Minute</key>
    <integer>${WEEKLY_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_weekly.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_weekly.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$RELIABILITY_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${RELIABILITY_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>reliability</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>${RELIABILITY_WEEKDAY}</integer>
    <key>Hour</key>
    <integer>${RELIABILITY_HOUR}</integer>
    <key>Minute</key>
    <integer>${RELIABILITY_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_reliability.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_reliability.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$KB_CLUSTER_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${KB_CLUSTER_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>kb_cluster</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${KB_CLUSTER_HOUR}</integer>
    <key>Minute</key>
    <integer>${KB_CLUSTER_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_kb_cluster.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_kb_cluster.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$KB_ARTICLES_INDEX_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${KB_ARTICLES_INDEX_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>kb_articles_index</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${KB_ARTICLES_INDEX_HOUR}</integer>
    <key>Minute</key>
    <integer>${KB_ARTICLES_INDEX_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_kb_articles_index.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_kb_articles_index.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$KB_ARTICLE_GAP_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${KB_ARTICLE_GAP_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${RUNNER}</string>
    <string>kb_article_gap</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>${KB_ARTICLE_GAP_HOUR}</integer>
    <key>Minute</key>
    <integer>${KB_ARTICLE_GAP_MINUTE}</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/launchd_kb_article_gap.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/launchd_kb_article_gap.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

cat > "$CSAT_INSIGHT_PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${CSAT_INSIGHT_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PYTHON_BIN}</string>
    <string>${RUNTIME_DIR}/csat_insight.py</string>
  </array>
  <key>WorkingDirectory</key>
  <string>${RUNTIME_DIR}</string>
  <key>StartInterval</key>
  <integer>180</integer>
  <key>StandardOutPath</key>
  <string>${LOG_DIR}/csat-insight.log</string>
  <key>StandardErrorPath</key>
  <string>${LOG_DIR}/csat-insight.err.log</string>
  <key>RunAtLoad</key>
  <false/>
  <key>AbandonProcessGroup</key>
  <true/>
</dict>
</plist>
EOF

for label in "$BENCH_LABEL" "$DAILY_LABEL" "$WATCHDOG_LABEL" "$WEEKLY_LABEL" "$RELIABILITY_LABEL" "$KB_CLUSTER_LABEL" "$KB_ARTICLES_INDEX_LABEL" "$KB_ARTICLE_GAP_LABEL" "$CSAT_INSIGHT_LABEL"; do
  launchctl bootout "gui/$(id -u)/$label" >/dev/null 2>&1 || true
done

launchctl bootstrap "gui/$(id -u)" "$BENCH_PLIST"
launchctl bootstrap "gui/$(id -u)" "$DAILY_PLIST"
launchctl bootstrap "gui/$(id -u)" "$WATCHDOG_PLIST"
launchctl bootstrap "gui/$(id -u)" "$WEEKLY_PLIST"
launchctl bootstrap "gui/$(id -u)" "$RELIABILITY_PLIST"
launchctl bootstrap "gui/$(id -u)" "$KB_CLUSTER_PLIST"
launchctl bootstrap "gui/$(id -u)" "$KB_ARTICLES_INDEX_PLIST"
launchctl bootstrap "gui/$(id -u)" "$KB_ARTICLE_GAP_PLIST"
launchctl bootstrap "gui/$(id -u)" "$CSAT_INSIGHT_PLIST"

echo "LaunchAgents installés :"
echo "  $BENCH_PLIST"
echo "  $DAILY_PLIST"
echo "  $WATCHDOG_PLIST"
echo "  $WEEKLY_PLIST"
echo "  $RELIABILITY_PLIST"
echo "  $KB_CLUSTER_PLIST"
echo "  $KB_ARTICLES_INDEX_PLIST"
echo "  $KB_ARTICLE_GAP_PLIST"
echo "  $CSAT_INSIGHT_PLIST"
echo "Runtime launchd :"
echo "  $RUNTIME_DIR"
echo ""
echo "Horaires :"
echo "  benchmark : ${BENCH_HOUR}:$(printf '%02d' "$BENCH_MINUTE")"
echo "  daily     : ${DAILY_HOUR}:$(printf '%02d' "$DAILY_MINUTE")"
echo "  watchdog  : ${WATCHDOG_HOUR}:$(printf '%02d' "$WATCHDOG_MINUTE")"
echo "  weekly    : weekday ${WEEKLY_WEEKDAY} ${WEEKLY_HOUR}:$(printf '%02d' "$WEEKLY_MINUTE")"
echo "  reliability : weekday ${RELIABILITY_WEEKDAY} ${RELIABILITY_HOUR}:$(printf '%02d' "$RELIABILITY_MINUTE")"
echo "  kb_cluster : ${KB_CLUSTER_HOUR}:$(printf '%02d' "$KB_CLUSTER_MINUTE")"
echo "  kb_articles_index : ${KB_ARTICLES_INDEX_HOUR}:$(printf '%02d' "$KB_ARTICLES_INDEX_MINUTE")"
echo "  kb_article_gap    : ${KB_ARTICLE_GAP_HOUR}:$(printf '%02d' "$KB_ARTICLE_GAP_MINUTE")"
echo "  csat-insight : toutes les 180s (StartInterval)"
