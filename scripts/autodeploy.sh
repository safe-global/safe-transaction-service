#!/bin/bash

set -ev

curl -s --output /dev/null --write-out "%{http_code}" \
    -H "Content-Type: application/json" \
    -X POST \
    -u "$AUTODEPLOY_TOKEN" \
    -d '{"push_data": {"tag": "'$TARGET_ENV'" }}' \
    $AUTODEPLOY_URL
