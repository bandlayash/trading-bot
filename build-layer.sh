#!/bin/bash
set -e

# Clean old layer
rm -rf python layer
mkdir -p python

echo "Building Lambda layer dependencies in Amazon Linux 2023..."

# Build dependencies inside Amazon Linux 2023
docker run --rm \
  -v "$PWD":/var/task \
  -w /var/task \
  public.ecr.aws/amazonlinux/amazonlinux:2023 \
  /bin/bash -c "
    yum update -y
    yum install -y python3 python3-devel gcc gcc-c++ make tar gzip unzip findutils
    python3 -m pip install --upgrade pip
    python3 -m pip install -r requirements.txt -t python/
  "

# Zip the layer
zip -r layer.zip python/
echo "✓ Lambda layer built: layer.zip"
