#!/bin/sh
# Keep the Virgin Media hub's status page (192.168.100.1) reachable from the LAN.
#
# The hub is in bridge mode, so its management address is on the WAN side and the
# gateway has no source address in that subnet — a static route alone does NOT
# work (verified: the gateway sources from 89.100.220.88 and the hub cannot
# reply). Giving eth4 a second address in 192.168.100.0/24 fixes the source, and
# SNAT lets LAN clients use it too.
#
# This runs from cron every minute because it is NOT sticky: a WAN link bounce
# flushes the address (observed — pinning the port to 1G bounced the link and the
# address vanished), and UniFi rewrites iptables whenever network config changes.
# Every action below is idempotent, so re-running costs nothing and it self-heals.
#
# Lives in /data because that survives firmware upgrades. /etc/cron.d does NOT —
# after a firmware update, re-add:
#   echo '* * * * * root /data/modem-access.sh' > /etc/cron.d/modem-access
IFACE=eth4
ADDR=192.168.100.2
PREFIX=192.168.100.2/24
SUBNET=192.168.100.0/24

# 1. source address in the hub's subnet
ip addr show dev "$IFACE" 2>/dev/null | grep -q "$PREFIX" \
  || ip addr add "$PREFIX" dev "$IFACE" 2>/dev/null

# 2. UniFi uses per-interface policy routing tables, and the WAN table's default
#    route would otherwise send the hub's subnet off to the ISP. Pin it.
for TBL in main "201.$IFACE"; do
  ip route show "$SUBNET" dev "$IFACE" table "$TBL" 2>/dev/null | grep -q . \
    || ip route add "$SUBNET" dev "$IFACE" src "$ADDR" table "$TBL" 2>/dev/null
done

# 3. rewrite LAN sources so the hub has a route back
iptables -t nat -C POSTROUTING -d "$SUBNET" -o "$IFACE" -j SNAT --to-source "$ADDR" 2>/dev/null \
  || iptables -t nat -I POSTROUTING 1 -d "$SUBNET" -o "$IFACE" -j SNAT --to-source "$ADDR" 2>/dev/null

# 4. and allow the forward
iptables -C FORWARD -d "$SUBNET" -o "$IFACE" -j ACCEPT 2>/dev/null \
  || iptables -I FORWARD 1 -d "$SUBNET" -o "$IFACE" -j ACCEPT 2>/dev/null
