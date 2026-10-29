#!/usr/bin/env bash
# Give the installer its own process group, including on macOS.
set -u
set -m
seconds=$1
shift
installer=
watchdog=
timed_out=0

cleanup() {
    trap '' USR1
    if [ -n "$watchdog" ]; then
        kill -TERM -- "-$watchdog" 2>/dev/null || :
        wait "$watchdog" 2>/dev/null || :
    fi
    if [ -n "$installer" ]; then
        kill -TERM -- "-$installer" 2>/dev/null || :
        if [ "$timed_out" -eq 1 ]; then sleep 1; fi
        kill -KILL -- "-$installer" 2>/dev/null || :
        wait "$installer" 2>/dev/null || :
    fi
}
trap 'cleanup' EXIT
trap 'timed_out=1' USR1
trap 'exit 130' INT
trap 'exit 143' TERM HUP

"$@" < /dev/null &
installer=$!
parent=$$
(sleep "$seconds"; kill -USR1 "$parent") &
watchdog=$!
wait "$installer"
status=$?
if [ "$timed_out" -eq 1 ]; then
    echo "Android installation timed out after ${seconds}s" >&2
    status=124
fi
cleanup
trap - EXIT
exit "$status"
