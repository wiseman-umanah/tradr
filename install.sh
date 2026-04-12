#!/bin/bash

echo "Installing tradr..."

# check python
if ! command -v python3 &> /dev/null; then
    echo "Python3 is required. Install it first."
    exit 1
fi

# check version
PYTHON_VERSION=$(python3 -c "import sys; print(sys.version_info.minor)")
if [ "$PYTHON_VERSION" -lt 11 ]; then
    echo "Python 3.11 or higher is required."
    exit 1
fi

# install
pip install tradr

echo "tradr installed! Run 'tradr' to get started."

