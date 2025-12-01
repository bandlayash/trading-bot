#!/bin/bash
set -e

# Clean old layer
rm -rf python layer
mkdir -p python

# Build inside Amazon Linux 2023 (matches Lambda)
docker run --rm \
  -v "$PWD":/var/task \
  -w /var/task \
  public.ecr.aws/amazonlinux/amazonlinux:2023 \
  /bin/bash -c "
    yum update -y &&
    yum install -y python3 python3-devel gcc gcc-c++ make \
                    tar gzip unzip findutils

    pip3 install --upgrade pip
    pip3 install -r requirements.txt -t python/
"

# Zip layer
zip -r layer.zip python/
echo "✓ Layer built: layer.zip"
