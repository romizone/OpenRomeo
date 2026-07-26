"""Agent coworker platform runtime (codename: coworker)."""

# The single source of truth for the Python side — pyproject reads it dynamically and the
# server reports it on /openapi.json. Keep in step with the desktop manifests
# (surfaces/gui: package.json, src-tauri/Cargo.toml, src-tauri/tauri.conf.json) at release.
__version__ = "1.0.8"
