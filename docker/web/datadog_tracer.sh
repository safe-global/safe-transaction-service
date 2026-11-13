#!/bin/bash
# Sourced by the start scripts. Start a process as "${DDTRACE_RUN[@]}" <cmd>.

DDTRACE_RUN=()
dd_apm_enabled=${DD_APM_ENABLED:-}
case "${dd_apm_enabled,,}" in
  y | yes | t | true | on | 1) DDTRACE_RUN=(ddtrace-run) ;;
esac
unset dd_apm_enabled
