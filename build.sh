#!/bin/bash

# Configuration
IMAGE_NAME="ghcr.io/your-username/ha-tn-reporter"
TAG="latest"

# 1. Create and use a new builder instance that supports multi-arch
# This is required because the default builder usually only supports the host arch.
docker buildx create --name multiarch-builder --use || docker buildx use multiarch-builder

# 2. Boot the builder
docker buildx inspect --bootstrap

# 3. Build and Push
# --platform specifies the architectures
# --push is required for multi-arch builds because the local Docker daemon 
# cannot load multi-arch manifests directly.
echo "Building and pushing $IMAGE_NAME:$TAG for amd64 and arm64..."

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "$IMAGE_NAME:$TAG" \
  --push .

echo "Build complete!"