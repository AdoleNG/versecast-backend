#!/bin/bash

# Change directory to the folder containing this script
cd "$(dirname "$0")"

echo "Starting VerseCast launcher server..."
echo "You may minimize this window."

while true
do
    python3 launcher_server.py
    echo "Launcher crashed or exited. Restarting in 3 seconds..."
    sleep 3
done
