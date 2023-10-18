#!/bin/sh -e

if [ ! -z "${ALLOW_INTERFACES}" ]; then
  sed -i "s/.*allow-interfaces=.*/allow-interfaces=${ALLOW_INTERFACES}/" /etc/avahi/avahi-daemon.conf
fi

if [ ! -z "${DENY_INTERFACES}" ]; then
  sed -i "s/.*deny-interfaces=.*/deny-interfaces=${DENY_INTERFACES}/" /etc/avahi/avahi-daemon.conf
fi

rm -f /var/run/avahi-daemon/*

exec "$@"
