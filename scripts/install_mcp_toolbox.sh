#!/usr/bin/env bash
# Install Google's MCP Toolbox for Databases (`toolbox`), the binary the
# project-scoped .mcp.json launches as the BigQuery MCP server
# (`toolbox --prebuilt bigquery --stdio`).
#
# Written for the Claude Code cloud environment's setup script, which runs at the
# start of every session, but it works on any linux/amd64 or macOS machine:
#
#   bash scripts/install_mcp_toolbox.sh
#   INSTALL_DIR="$HOME/.local/bin" bash scripts/install_mcp_toolbox.sh
#   TOOLBOX_VERSION=1.2.0 bash scripts/install_mcp_toolbox.sh
#   TOOLBOX_VERSION=1.2.0 TOOLBOX_SHA256=<sha256> bash scripts/install_mcp_toolbox.sh
#
# - Pinned: the default version is fixed and its linux/amd64 binary is checked
#   against a recorded SHA-256, so a new session never silently picks up a
#   different release.
# - Verified otherwise: another version or platform is checked against
#   TOOLBOX_SHA256 when given, else against the MD5 that Cloud Storage publishes
#   for the object. That catches a corrupt or truncated download, but it is
#   not an independent pin.
# - Idempotent: exits immediately when that version is already installed.
#
# Binaries come from Google's public release bucket (the same URLs the
# googleapis/mcp-toolbox README uses). Only linux/amd64, darwin/amd64,
# darwin/arm64 and windows/amd64 are published; there is no linux/arm64 build.

set -euo pipefail

TOOLBOX_VERSION="${TOOLBOX_VERSION:-1.1.0}"
TOOLBOX_VERSION="${TOOLBOX_VERSION#v}"
INSTALL_DIR="${INSTALL_DIR:-/usr/local/bin}"
BUCKET="genai-toolbox"

# SHA-256 of gs://genai-toolbox/v1.1.0/linux/amd64/toolbox (recorded 2026-09-28).
PINNED_VERSION="1.1.0"
PINNED_SHA256_LINUX_AMD64="17948e7538914320c4141d155bcf283c9a8c168c6abce09ae87837057899ba29"

log() { echo "install_mcp_toolbox: $*"; }
die() { echo "install_mcp_toolbox: ERROR: $*" >&2; exit 1; }

case "$(uname -s)" in
  Linux) os=linux ;;
  Darwin) os=darwin ;;
  *) die "unsupported OS $(uname -s)" ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) arch=amd64 ;;
  arm64 | aarch64) arch=arm64 ;;
  *) die "unsupported architecture $(uname -m)" ;;
esac
[ "$os/$arch" != "linux/arm64" ] || die "no linux/arm64 build is published; use an amd64 environment"

target="$INSTALL_DIR/toolbox"
if [ -x "$target" ] && "$target" --version 2>/dev/null | grep -q "version ${TOOLBOX_VERSION}+"; then
  log "toolbox ${TOOLBOX_VERSION} already installed at $target"
  exit 0
fi

object="v${TOOLBOX_VERSION}/${os}/${arch}/toolbox"
url="https://storage.googleapis.com/${BUCKET}/${object}"

mkdir -p "$INSTALL_DIR" 2>/dev/null || true
[ -w "$INSTALL_DIR" ] || die "$INSTALL_DIR is not writable; run as root or set INSTALL_DIR"
# Download beside the destination so the final mv is atomic (same filesystem).
tmp="$(mktemp "$INSTALL_DIR/.toolbox.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

log "downloading $url"
curl -fsSL --retry 4 --retry-delay 2 --retry-connrefused -o "$tmp" "$url" \
  || die "download failed (does v${TOOLBOX_VERSION} exist for ${os}/${arch}?)"

sha256_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1
  fi
}

expected_sha="${TOOLBOX_SHA256:-}"
if [ -z "$expected_sha" ] && [ "$TOOLBOX_VERSION" = "$PINNED_VERSION" ] && [ "$os/$arch" = "linux/amd64" ]; then
  expected_sha="$PINNED_SHA256_LINUX_AMD64"
fi

if [ -n "$expected_sha" ]; then
  actual_sha="$(sha256_of "$tmp")"
  [ "$actual_sha" = "$expected_sha" ] \
    || die "SHA-256 mismatch for $object: expected $expected_sha, got $actual_sha"
  log "SHA-256 verified ($actual_sha)"
else
  command -v openssl >/dev/null 2>&1 || die "openssl is needed to verify an unpinned version (or set TOOLBOX_SHA256)"
  meta_url="https://storage.googleapis.com/storage/v1/b/${BUCKET}/o/${object//\//%2F}?fields=md5Hash"
  expected_md5="$(curl -fsSL --retry 4 --retry-delay 2 "$meta_url" | sed -n 's/.*"md5Hash": *"\([^"]*\)".*/\1/p')"
  [ -n "$expected_md5" ] || die "could not read the published MD5 for $object"
  actual_md5="$(openssl dgst -md5 -binary "$tmp" | base64)"
  [ "$actual_md5" = "$expected_md5" ] \
    || die "MD5 mismatch for $object: published $expected_md5, got $actual_md5"
  log "MD5 matches Cloud Storage metadata (no pinned SHA-256 for v${TOOLBOX_VERSION} ${os}/${arch})"
fi

chmod 0755 "$tmp"
mv -f "$tmp" "$target"
trap - EXIT
log "installed $("$target" --version) at $target"

case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *) log "WARNING: $INSTALL_DIR is not on PATH; .mcp.json runs plain 'toolbox'" ;;
esac
