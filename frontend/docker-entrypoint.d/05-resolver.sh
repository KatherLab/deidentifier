#!/bin/sh
# Inject the container network's DNS server into the nginx config so the
# backend hostname is re-resolved at request time (resolver + variable
# proxy_pass). Without this, nginx caches the backend IP once at startup and
# serves 502/"host unreachable" after the backend container is recreated.
# Works on Docker (127.0.0.11) and Podman/aardvark (gateway IP) alike.
set -e

RESOLVER="$(awk '/^nameserver/ {print $2; exit}' /etc/resolv.conf)"
[ -n "$RESOLVER" ] || RESOLVER="127.0.0.11"
case "$RESOLVER" in
    *:*) RESOLVER="[$RESOLVER]" ;;  # IPv6 needs brackets in nginx syntax
esac

sed -i "s|__RESOLVER__|$RESOLVER|g" /etc/nginx/conf.d/default.conf
echo "nginx resolver set to $RESOLVER"
