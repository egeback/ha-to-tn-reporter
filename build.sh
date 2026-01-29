#!/bin/bash

# Configuration
IMAGE_NAME="ghcr.io/egeback/ha-tn-reporter"
# Read version from the Python package to ensure a single source of truth
VERSION=$(grep -oP "__version__ = '\K[^']+" src/reporter/__init__.py)
LATEST_TAG="latest"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

# Exit if version could not be determined
if [ -z "$VERSION" ]; then
    echo "Error: Could not find version in src/reporter/__init__.py"
    exit 1
fi

# Run tests before building
if [ -z "$SKIP_TESTS" ]; then
    echo "Running tests..."
    if ! pytest; then
        echo "Tests failed! Aborting build."
        exit 1
    fi
else
    echo "Skipping tests (SKIP_TESTS is set)..."
fi

# 1. Create and use a new builder instance that supports multi-arch
# This is required because the default builder usually only supports the host arch.
docker buildx create --name multiarch-builder --use || docker buildx use multiarch-builder

# 2. Boot the builder
docker buildx inspect --bootstrap

# 3. Build and Push
# --platform specifies the architectures
# --push is required for multi-arch builds because the local Docker daemon 
# cannot load multi-arch manifests directly.

OUTPUT_ARGS=""
if [ -n "$PUSH_IMAGE" ]; then
    OUTPUT_ARGS="--push"
    echo "Building and pushing $IMAGE_NAME for $PLATFORMS with tags: $VERSION, $LATEST_TAG"
else
    echo "Building (no push) $IMAGE_NAME for $PLATFORMS with tags: $VERSION, $LATEST_TAG"
fi

docker buildx build \
  --platform "$PLATFORMS" \
  -t "$IMAGE_NAME:$VERSION" \
  -t "$IMAGE_NAME:$LATEST_TAG" \
  $OUTPUT_ARGS .

echo "Build complete!"