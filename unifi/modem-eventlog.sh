#!/bin/sh
# Snapshot the Virgin Media Fibre Hub's event log + PON state into an append-only
# JSONL, deduped by (time,message). The hub keeps only a 100-entry ring buffer
# (~3.5h when it is busy logging), so without this the evidence for an ISP fault
# report is gone before anyone looks. Paired with /data/modem-access.sh, which is
# what makes 192.168.100.1 reachable at all.
M=http://192.168.100.1/rest/v1
OUT=/data/modem-eventlog.jsonl
SEEN=/data/.modem-eventlog.seen
TS=$(date +%FT%T%z)

PON=$(curl -s -m 10 "$M/pon/state" 2>/dev/null)
[ -n "$PON" ] || exit 0
echo "{\"captured\":\"$TS\",\"kind\":\"pon_state\",\"data\":$PON}" >> "$OUT"

LOG=$(curl -s -m 10 "$M/pon/eventlog" 2>/dev/null)
[ -n "$LOG" ] || exit 0
# One event per line, then filter out any (time,message) pair already recorded.
echo "$LOG" \
  | sed 's/},{/}\n{/g; s/^{"eventlog":\[//; s/\],"NumberOfEntries":"[0-9]*"}$//' \
  | grep '"time"' \
  | while IFS= read -r line; do
      key=$(echo "$line" | md5sum | cut -d' ' -f1)
      grep -q "^$key$" "$SEEN" 2>/dev/null && continue
      echo "$key" >> "$SEEN"
      echo "{\"captured\":\"$TS\",\"kind\":\"event\",\"data\":$line}" >> "$OUT"
    done
# Keep the dedupe index bounded.
if [ "$(wc -l < "$SEEN" 2>/dev/null || echo 0)" -gt 5000 ]; then
  tail -2000 "$SEEN" > "$SEEN.tmp" && mv "$SEEN.tmp" "$SEEN"
fi
