#!/bin/sh
# Read-only inventory; no credentials, database contents or environment values.
set -eu
printf '\n== OS ==\n'
cat /etc/os-release
printf '\n== CPU and memory ==\n'
getconf _NPROCESSORS_ONLN
free -h
printf '\n== Disk ==\n'
df -h / /opt /var
printf '\n== Listening ports ==\n'
ss -lnt
printf '\n== Available tools ==\n'
for tool in python3 docker nginx systemctl git uv soffice; do
    command -v "$tool" || true
done
printf '\n== Container status ==\n'
if command -v docker >/dev/null 2>&1; then
    docker ps --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
fi
