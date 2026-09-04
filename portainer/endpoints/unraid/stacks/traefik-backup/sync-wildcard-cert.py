#!/usr/bin/env python3
"""Sync the *.home.shaunoneill.com wildcard cert from cevo's acme.json to the
unraid traefik-backup stack.

Run this ON cevo (it needs to read /opt/traefik/letsencrypt/acme.json), on a
schedule. Traefik renews at 30 days remaining, so weekly is plenty:

    0 4 * * 1  root  /usr/bin/python3 /opt/home-ops/sync-wildcard-cert.py \
                       --portainer-token-file /root/.portainer-token

WHY THIS EXISTS
    traefik-backup deliberately has no ACME resolver: two Traefiks doing
    DNS-01 for the same names collide on _acme-challenge TXT records, which is
    the Cloudflare 81058 error that blocks ALL issuance, cevo's included. So
    the backup serves the cert cevo already holds, and this keeps that copy
    fresh.

HOW IT GETS THERE
    cevo has no SSH key for unraid. It uses the Portainer-proxied Docker API
    instead: create a stopped helper container that bind-mounts the certs
    directory, PUT a tar into it, delete it. Docker's archive endpoint works on
    a container that has never been started, so this needs no running
    container and does not disturb traefik-backup.

Prints no key material. Exits non-zero on any failure so cron mails you.
"""
import argparse
import base64
import io
import json
import os
import re
import ssl
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request

ACME = "/opt/traefik/letsencrypt/acme.json"
DOMAIN = "*.home.shaunoneill.com"
CERT_DIR = "/mnt/user/appdata/traefik-backup/certs"
HELPER = "traefik-backup-certsync"
ENDPOINT = 4  # unraid


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portainer-url", default="http://localhost:9000/api")
    ap.add_argument("--portainer-token-file", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.portainer_token_file) as f:
        token = f.read().strip()
    base = f"{args.portainer_url}/endpoints/{ENDPOINT}/docker"

    def api(path, data=None, method=None, raw=None, ctype="application/json"):
        headers = {"X-API-Key": token}
        body = None
        if raw is not None:
            body, headers["Content-Type"] = raw, ctype
        elif data is not None:
            body = json.dumps(data).encode()
            headers["Content-Type"] = ctype
        req = urllib.request.Request(base + path, data=body,
                                     headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                out = r.read()
                return r.status, (json.loads(out) if out.strip()
                                  and ctype == "application/json" else {})
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()[:300]

    # 1. extract the wildcard from acme.json
    with open(ACME) as f:
        store = json.load(f)
    cert = key = None
    for resolver in store.values():
        for entry in (resolver.get("Certificates") or []):
            if entry.get("domain", {}).get("main") == DOMAIN:
                cert = base64.b64decode(entry["certificate"])
                key = base64.b64decode(entry["key"])
    if not cert or not key:
        print(f"ERROR: {DOMAIN} not found in {ACME}", file=sys.stderr)
        return 1

    # sanity-check before shipping it anywhere
    chain = re.findall(rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
                       cert, re.S)
    if not chain or b"PRIVATE KEY" not in key:
        print("ERROR: extracted material does not look like a cert+key",
              file=sys.stderr)
        return 1
    dates = subprocess.run(
        ["openssl", "x509", "-noout", "-subject", "-dates"],
        input=chain[0], capture_output=True)
    print(f"extracted {DOMAIN}: chain={len(chain)} "
          f"cert={len(cert)}B key={len(key)}B")
    print(dates.stdout.decode().strip())

    if args.dry_run:
        print("--dry-run: not uploading")
        return 0

    # 2. tar it up, mode 0600 for the key
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, blob, mode in (("wildcard.crt", cert, 0o644),
                                 ("wildcard.key", key, 0o600)):
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(blob), mode
            tar.addfile(info, io.BytesIO(blob))
    payload = buf.getvalue()

    # 3. stopped helper container that bind-mounts the certs dir
    api(f"/containers/{HELPER}?force=true", method="DELETE")
    st, r = api(f"/containers/create?name={HELPER}", {
        "Image": "alpine:3.20",
        "Cmd": ["true"],
        "HostConfig": {"Binds": [f"{CERT_DIR}:/certs"], "NetworkMode": "none"},
    })
    if st >= 400:
        print(f"ERROR: create helper failed: {st} {r}", file=sys.stderr)
        return 1
    cid = r["Id"]

    try:
        # PUT archive works on a never-started container
        st, r = api(f"/containers/{cid}/archive?path=/certs",
                    raw=payload, method="PUT", ctype="application/x-tar")
        if st >= 400:
            print(f"ERROR: upload failed: {st} {r}", file=sys.stderr)
            return 1
        print(f"uploaded wildcard.crt + wildcard.key to {CERT_DIR}")
    finally:
        api(f"/containers/{cid}?force=true", method="DELETE")

    # 4. Traefik watches the file provider but NOT the cert files themselves,
    #    so nudge it. Restart is ~1s and this stack holds no state.
    st, _ = api("/containers/traefik-backup/restart", method="POST")
    print(f"traefik-backup restart -> {st}")
    return 0 if st < 400 else 1


if __name__ == "__main__":
    sys.exit(main())
