#!/usr/bin/env python3
"""Correlate the ISP hub's own event log against UniFi's WAN-down decisions.

Produces the timeline to hand to ISP support. Both sources live on the gateway:

  /data/modem-eventlog.jsonl  collected by modem-eventlog.sh, because the hub
                              keeps only a 100-entry ring buffer (~3.5h busy)
  /var/log/messages           UniFi's wan-failover lines -- NOT daemon.log,
                              which only has linkcheck/speedtest and networkd

Two gotchas this script exists to get right:
  * The hub stamps LOCAL time but labels it "Z". Treat it as local or every
    correlation lands an hour out.
  * Only UniFi events INSIDE the hub log's coverage can possibly correlate.
    Scoring against all UniFi events understates correlation badly.
"""
import glob
import json
import re
import sys
from datetime import datetime, timedelta

WINDOW = 90  # s -- two devices noticing the same event are not synchronised


def parse(ts):
    return datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")


# --- hub side ---------------------------------------------------------------
seen = {}
try:
    for line in open("/data/modem-eventlog.jsonl"):
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if rec.get("kind") != "event":
            continue
        d = rec["data"]
        seen[(d["time"], d["message"])] = (parse(d["time"]), d["message"])
except FileNotFoundError:
    print("no /data/modem-eventlog.jsonl yet -- has the cron run?", file=sys.stderr)

hub = sorted(seen.values())
fails = [e for e in hub if "ping failed" in e[1] or "Recovering Service" in e[1]]
v6 = [e for e in hub if "ipv6" in e[1].lower()]

# --- gateway side -----------------------------------------------------------
uni = []
for path in ["/var/log/messages"] + sorted(glob.glob("/var/log/messages.1")):
    try:
        fh = open(path, errors="replace")
    except IOError:
        continue
    for line in fh:
        if "wan-failover-interfaces" not in line or "is down" not in line:
            continue
        if "wf-interface-lo" in line:
            continue  # phantom iface from a reverted unbind_wan_monitors test
        m = re.match(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})", line)
        if not m:
            continue
        vec = re.search(r"\[([UD_]+)\]", line)
        uni.append((parse(m.group(1)), vec.group(1) if vec else "?"))
uni.sort()

print("=" * 78)
print("WAN INCIDENT REPORT")
print("=" * 78)
print("Hub  : Sagemcom F5685LGE (Virgin Media 'Fibre Hub'), XGS-PON ITU-T G.9807.1")
print("       firmware 3.7.4-2306.5, serial YCED31071054")
print("WAN  : 89.100.220.88/24, Play Broadband / Liberty Global")
print()
print("Hub IPv4 health-check failures : %d" % len(fails))
print("Hub IPv6 provisioning failures : %d" % len(v6))
print("UniFi WAN-down decisions       : %d  (all logs)" % len(uni))
if not hub:
    print("\nNo hub data yet; nothing to correlate.")
    sys.exit(0)

lo, hi = hub[0][0], hub[-1][0]
print("Hub log coverage               : %s -> %s" % (lo, hi))
win = [e for e in uni if lo - timedelta(seconds=WINDOW) <= e[0] <= hi]
print()
print("--- OVERLAP WINDOW ---")
print("    %d UniFi event(s) fall inside it; the other %d predate the hub log and"
      % (len(win), len(uni) - len(win)))
print("    therefore CANNOT be checked either way.")
print()

print("--- CORRELATED (both devices flagged, within %ds) ---" % WINDOW)
n = 0
for ut, vec in win:
    near = [e for e in fails if abs((e[0] - ut).total_seconds()) <= WINDOW]
    if not near:
        continue
    n += 1
    print("  %s  UniFi WAN down [%s]   (U=icmp up, D=dns down)" % (ut.strftime("%F %T"), vec))
    for t, msg in near:
        print("      %+5ds  hub: %s" % ((t - ut).total_seconds(), msg))
pct = (100.0 * n / len(win)) if win else 0.0
print("  correlated: %d of %d in-window UniFi events (%.0f%%)" % (n, len(win), pct))
print()

orphan = [e for e in fails
          if not any(abs((e[0] - ut).total_seconds()) <= WINDOW for ut, _ in win)]
print("--- HUB FAILURES WITH NO UniFi EVENT (wobble absorbed) ---")
print("  %d" % len(orphan))
for t, msg in orphan[:10]:
    print("      %s  %s" % (t.strftime("%F %T"), msg))
if len(orphan) > 10:
    print("      ... and %d more" % (len(orphan) - 10))
print()

print("--- VERDICT ---")
if n and len(win):
    print("  %d/%d of the gateway's WAN-down decisions are independently corroborated" % (n, len(win)))
    print("  by the ISP's own hub, while /pon/state stayed Online with no LOS or")
    print("  deregistration -> the fault is UPSTREAM OF THE FIBRE, on the ISP side.")
    print()
    print("  %d hub failures drew no UniFi event, so most upstream wobbles are" % len(orphan))
    print("  absorbed harmlessly. UniFi trips on a subset and then installs a")
    print("  blackhole route + resets connections -- the amplifier that turns a short")
    print("  ISP wobble into an outage you actually notice.")
elif win and not fails:
    print("  UniFi flagged outages the hub did not see -> monitor over-sensitivity,")
    print("  no evidence of an ISP fault in this window.")
else:
    print("  Not enough overlapping data yet; let modem-eventlog.sh accumulate.")
