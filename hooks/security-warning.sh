#!/usr/bin/env bash
# Post-tool hook: surface security warnings from node audit results.
# Reads tool output JSON from stdin. Exits 0 always (non-blocking).

input=$(cat)
if echo "$input" | grep -qi "DANGEROUS"; then
  echo "SECURITY: Dangerous node patterns detected. Review the audit results above before proceeding."
fi
