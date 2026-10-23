# Configuration

This directory contains small, reviewable configuration files for local development and future model-run coordination.

Keep credentials out of configuration files. Use `.env.example` as the list of local environment variables and keep real values in an approved secret store.

`windows/modeling-workstation.json` is the reviewed software release catalog for
the Windows workstation installer. Keep publisher checksum sources and installer
evidence with each release; see [workstation setup](../docs/windows-workstation-setup.md)
for maintenance and validation requirements.
