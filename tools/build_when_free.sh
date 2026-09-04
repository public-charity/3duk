#!/bin/bash
# Waits for the Unity GUI to release the project lock, then builds roads and renders proof shots.
cd /Users/alex.breadman/vibe/pigs
U="/Applications/Unity/Hub/Editor/6000.3.23f1/Unity.app/Contents/MacOS/Unity"
P="$PWD/unity/VirtualMargate"
while pgrep -f "Unity.app/Contents/MacOS/Unity -projectPath" >/dev/null; do sleep 5; done
sleep 3
echo "lock released, building roads..."
"$U" -projectPath "$P" -batchmode -quit -executeMethod MargateBootstrap.BuildAll -logFile "$PWD/tools/.roads-build.log"
grep -E "\[Margate\]|error CS" tools/.roads-build.log | head -12
"$U" -projectPath "$P" -batchmode -quit -executeMethod MargateShots.Capture -logFile "$PWD/tools/.roads-shots.log"
grep -cE "\[Margate\] shot" tools/.roads-shots.log | xargs echo "shots rendered:"
echo "BUILD DONE"
