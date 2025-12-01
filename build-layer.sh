#!/bin/bash
set -e

LAYER_DIR="layer/python"
rm -rf layer
mkdir -p $LAYER_DIR

echo "Building Lambda Layer for Python 3.12 on Amazon Linux 2023..."

docker run --rm \
  -v "$(pwd)":/var/task \
  public.ecr.aws/lambda/python:3.12 \
  /bin/bash -c "
    set -e
    echo 'Installing dependencies inside Amazon Linux 2023...'
    python3.12 -m pip install --upgrade pip
    python3.12 -m pip install -r requirements.txt -t layer/python
  "

echo "Removing unnecessary files..."
find layer/python -name '*.dist-info' -type d -exec rm -rf {} +
find layer/python -name '__pycache__' -type d -exec rm -rf {} +

echo "Creating layer.zip..."
cd layer
zip -r ../layer.zip .
cd ..

echo "Done"
echo "Created layer.zip — ready to publish as a Lambda Layer."
