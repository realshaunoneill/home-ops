# Grafana Stack (local endpoint)

This stack provides dashboards, alerting, and now local log ingestion for UniFi.

## Components

- `grafana` UI and provisioning
- `loki` log store (named volume `loki_data`)
- `promtail` syslog receiver -> Loki forwarder

## UniFi log ingestion

UniFi is configured to send Activity Logging (Syslog) to:

- server: `192.168.0.20`
- port: `1514/udp`

Promtail listens on host `1514/udp` and labels streams with:

- `job=unifi-syslog`
- `source=unifi`
- parsed labels such as `host`, `severity`, `facility`, `app`

## Grafana provisioning

- Datasources are provisioned inline in `docker-compose.yml`:
  - Prometheus (`uid=prometheus`)
  - Loki (`uid=loki`)
- Dashboards are file-provisioned from `./dashboards`.
- Alert rules are provisioned from inline config mounted to:
  - `/etc/grafana/provisioning/alerting/unifi-alert-rules.yml`

## UniFi dashboard and alert

- Dashboard: `UniFi Logs` (`uid=unifi-logs`)
  - includes live logs, host/severity breakdown, and a threat-focused panel
- Alert rule: `UniFi High-Severity Log Spike`
  - query window: 5 minutes
  - threshold: > 25 warning+ events
  - `for`: 10 minutes

## Redeploy notes

- Use Portainer GitOps pull/redeploy on stack `grafana`.
- If using Portainer API redeploy, re-supply the existing stack `Env` array in
  the PUT body to avoid wiping stored stack env vars.
