# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-20

First release of the ThermoSave integration for Home Assistant.

### Added

- Config flow that logs in to an existing ThermoSave account with an email
  address and a one-time code, plus reauthentication when the stored login
  stops working.
- Automatic discovery of every device claimed by the account, including
  devices claimed after setup.
- Water heater entity with the Auto (follow schedule), Heat now (forced on)
  and Away (forced off) operation modes.
- State and Power sensors.
- Last seen and Timezone diagnostic sensors, and an Online diagnostic binary
  sensor.
- Schedule calendar that shows the device's power-saving windows as events
  repeating every day, in the device's timezone:
  - Create, edit and delete events in the Home Assistant calendar to change
    the schedule on the device. Editing or deleting one occurrence changes
    that window on every day.
  - Windows can cross midnight and can last up to 24 hours. All-day events
    and zero-length windows are rejected with an error.
  - The configured windows are also exposed as state attributes (`windows`
    and `schedule_window_count`), so they can be used in templates and
    automations.
- Bundled `pythermosave` client for the ThermoSave cloud API, so no extra
  Python packages are installed.
- ThermoSave brand icon and logo.

[Unreleased]: https://github.com/thermosave/ha-thermosave/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/thermosave/ha-thermosave/releases/tag/v1.0.0
