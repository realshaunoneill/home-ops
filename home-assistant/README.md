# Home Assistant inventory templates

This folder contains versioned Home Assistant templates for household essentials tracking.

## Files

- `packages/household_essentials.yaml`: entities, binary sensors, and automations.
- `dashboards/household_essentials.yaml`: Lovelace view with + / - controls.

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
