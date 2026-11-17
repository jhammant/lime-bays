#!/usr/bin/env bash
# Deploy the committed HEAD to endor (loom) as https://limebays.hammantlabs.com
#
# Ships only git-tracked files (git archive), so nothing untracked (venvs, private data) can reach endor or the image.
# The optional private index is wired in from outside the image:
#   - volume  /mnt/tank/apps/limebays/private -> /private (read-only; holds bays_private.sqlite)
#   - secret  LIMEBAYS_PRIVATE_TOKEN from loom's fleet secrets (enables /p/<token>/mcp)
# Without them the server runs public-only.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

if ! git diff --quiet HEAD; then
  echo "uncommitted changes: commit first (only HEAD is deployed)" >&2
  exit 1
fi

sha=$(git rev-parse --short HEAD)
stage=".hlsite/$sha/endor-stage"
mkdir -p "$stage"
git archive HEAD | tar -x -C "$stage"

if find "$stage" \( -name '*.kml' -o -name '*.sqlite' -o -name 'bays_private*' -o -name 'CONNECTOR-URL*' \) | grep -q .; then
  echo "refusing to deploy: private-looking files in the stage" >&2
  exit 1
fi

cat > "$stage/fleet.app.yaml" <<'YAML'
name: limebays
runtime: docker
port: 8000
access: public
hostname: limebays.hammantlabs.com
manifest_version: 2
metadata:
  description: "Remote MCP server: nearest dockless e-bike parking bays in London"
  owner: hammantlabs-sites
health:
  path: /health
secrets: [LIMEBAYS_PRIVATE_TOKEN]
volumes:
  - /mnt/tank/apps/limebays/private:/private:ro
YAML

hlsite deploy "$stage" --on endor --slug limebays --access public
