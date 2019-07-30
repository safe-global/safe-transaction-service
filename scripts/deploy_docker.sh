#!/bin/bash

set -euo pipefail

if [ "$TRAVIS_PULL_REQUEST" = "false" ]; then
    echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
    if [ "$1" = "develop" -o "$1" = "master" ]; then
        # If image does not exist, don't use cache
        docker pull gnosispm/$DOCKERHUB_PROJECT:$1 && \
        docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile . --cache-from gnosispm/$DOCKERHUB_PROJECT:$1 || \
        docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile .
    else
        docker pull gnosispm/$DOCKERHUB_PROJECT:staging && \
        docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile . --cache-from gnosispm/$DOCKERHUB_PROJECT:staging || \
        docker build -t $DOCKERHUB_PROJECT -f docker/web/Dockerfile .
    fi
    docker tag $DOCKERHUB_PROJECT gnosispm/$DOCKERHUB_PROJECT:$1
    docker push gnosispm/$DOCKERHUB_PROJECT:$1
fi
