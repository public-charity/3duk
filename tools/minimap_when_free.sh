#!/bin/bash
cd /Users/alex.breadman/vibe/pigs
U="/Applications/Unity/Hub/Editor/6000.3.23f1/Unity.app/Contents/MacOS/Unity"
P="$PWD/unity/VirtualMargate"
while pgrep -f "Unity.app/Contents/MacOS/Unity -projectPath" >/dev/null; do sleep 5; done
sleep 3
echo "lock released; building"
"$U" -projectPath "$P" -batchmode -quit -executeMethod MargateBootstrap.BuildAll -logFile "$PWD/tools/.mm1.log"
grep -E "error CS|Shader error" tools/.mm1.log | head -8
"$U" -projectPath "$P" -batchmode -quit -executeMethod MargateMinimapVerify.Run -logFile "$PWD/tools/.mm2.log"
grep -E "\[MM\]|error CS" tools/.mm2.log | head -10
echo "MINIMAP CHECK DONE"
