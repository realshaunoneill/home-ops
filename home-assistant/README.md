# Home Assistant config

Versioned Home Assistant config for this homelab. Two unrelated sets live here:
household essentials tracking (a template you install), and UPS/Unraid alerting
(a record of automations already deployed).

## Files

- `packages/household_essentials.yaml`: entities, binary sensors, and automations.
- `dashboards/household_essentials.yaml`: Lovelace view with + / - controls.
- `packages/ups_and_unraid_alerts.yaml`: UPS and Unraid alerting. **Already live**
  in HA's `automations.yaml` — see below.

## Install

1. Copy the package file into Home Assistant at `/config/packages/household_essentials.yaml`.
2. Copy the dashboard file into Home Assistant at `/config/dashboards/household_essentials.yaml`.
3. Ensure `configuration.yaml` includes package support:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

4. Add a dashboard entry to `configuration.yaml` (merge with existing `lovelace` section):

```yaml
lovelace:
  dashboards:
    household-essentials:
      mode: yaml
      title: Household Essentials
      icon: mdi:cart-variant
      show_in_sidebar: true
      filename: dashboards/household_essentials.yaml
```

5. Run Home Assistant config check, then restart Home Assistant.

## Notes

- Alerts use `notify.notify` and `shopping_list.add_item`.
- To target a phone directly, set `input_text.household_essentials_notify_service`
  to your mobile app service name (for example `notify.mobile_app_shauns_iphone`).
- Counts and minimums are configurable from the dashboard.
- Prometheus should expose these entities through the existing Home Assistant scrape job.

## UPS and Unraid alerting

`packages/ups_and_unraid_alerts.yaml` is a **record**, not something to install.
Those six automations were deployed into HA's `automations.yaml` on 2026-08-29 via
the REST config API and are running now. Keep the file in step if you edit them in
the UI; use it to restore if `automations.yaml` is lost.

One value is redacted: the `webhook_id` for `ups_apcupsd_webhook`. This repo is
public. The real value lives in HA's `automations.yaml` and in the hook script on
the Unraid flash — read it from either if restoring.

### Companion pieces outside this repo

- **Unraid apcupsd event hooks** — `/boot/config/apcupsd-hooks/{onbattery,offbattery,changeme,commfailure}`,
  all copies of `apc-ha-notify`, which POSTs to the HA webhook. `apccontrol` runs a
  script named after the event, then continues its own default action (they exit 0,
  not 99, so Unraid's own notification still fires). Stock originals are kept
  alongside as `*.stock`.
- **Boot persistence** — Unraid's `/etc` is a RAM filesystem, so `/boot/config/go`
  reinstalls the hooks on every boot. Backup at `/boot/config/go.bak-20260829`.
- **apcupsd thresholds** — set on the hosts, not here. Unraid's persist in
  `/boot/config/plugins/dynamix.apcupsd/dynamix.apcupsd.cfg`; Proxmox's in
  `/etc/apcupsd/apcupsd.conf`. Both backed up as `*.bak-20260828`.

### Gotchas worth knowing before debugging these

- Both the `unraid` and `apcupsd` integrations title themselves "Vault", so both
  emit `*.vault_*` entities. They are different integrations.
- `sensor.vault_ups_smart_ups_1500_load` (from the `unraid` integration) is **not a
  real measurement**. This UPS's USB HID interface exposes no load, line voltage or
  temperature at all — `apcaccess` returns 28 fields with no `LOADPCT`/`NOMPOWER`.
  Only a serial cable would provide them. Don't build on that sensor.
- If UPS entities go `unavailable` while the integration still reports healthy,
  suspect the rename-orphan pattern: 16 dead `apc_ups_*` duplicates were removed on
  2026-08-29, all still attached to a *loaded* config entry with `restored: true`.
