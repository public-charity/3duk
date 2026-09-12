# Kent Police Volvo V90 estate

Current player vehicle, replacing the earlier XC90 SUV prototype. Authored in
headless Blender with an approximately 4.97 m body, 2.941 m wheelbase, 1.475 m
roof and 0.335 m tyre radius. Police equipment extends above the roof.

Revision 2 uses one continuous, symmetric subdivision shell for the body and
cabin. Wheel openings are quad topology, without Boolean cuts or raised arch
trim. Shape-preserving cubic curves define the shoulder, bonnet and long roof.
The glass, grille, headlights, tail lamps, livery and subtle door lines are flush
UV features, replacing the earlier overlapping panels and thin wire details.
Only wheels, rounded mirrors and the slim lightbar add silhouette geometry.
This is a deliberately simplified game asset, not manufacturer CAD.

`make_atlas.py` builds a deterministic 4096px atlas with five padded islands:
left side, right side, bonnet/roof/glazing, nose and tail. Lettering reads correctly
on both sides. Fixed face regions define seams before subdivision; UV coordinates
are projected afterwards. The base-color texture is sRGB. The linear surface map
stores roughness in R, metalness in G and emission weight in B. Rear glass is
defined analytically about Y=0. No reference photograph is baked into the asset.

## References

- [Kent Police V90 GN22 BWC, photographed 5 February 2025 by policest1100](https://www.flickr.com/photos/83194815@N00/54308983256/).
  Visually inspected for silhouette, front grille, lighting and livery. Photo is
  all rights reserved and is linked only; it is not included or used as a texture.
- [Kent Police marked fleet, 2025](https://www.kent.police.uk/SysSiteAssets/foi-media/kent/lists-and-registers/marked-vehicle-fleet/kent-police-s-marked-vehicle-fleet--2025.pdf),
  page 8, lists V90s in service. No claim about the current assignment of GN22 BWC.
- [Volvo V90 dimensions](https://www.volvocars.com/us/support/car/v90/article/766ee075f0e03896c0a8015109ee0749/).
  Dimensions anchor the estate proportions; the rear livery, simplified badge and
  smaller details remain authored approximations.

## Build, import and render

Run from the repository root, with other Unreal processes closed during import:

```powershell
& 'C:/Users/Shadow/code/3duk-env/env/python.exe' assets/KentPoliceV90/make_atlas.py
& 'C:/Program Files/Blender Foundation/Blender 5.2/blender.exe' -b --python-exit-code 2 --python assets/KentPoliceV90/build_v90.py
powershell -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 -Script 10_import_police_car.py
powershell -ExecutionPolicy Bypass -File projects/one/Tools/build.ps1
powershell -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_python.ps1 -Script 11_render_police_car.py -Render
powershell -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_tests.ps1 -Filter Thanet.Vehicle -Log vehicle_tests.log
```

Blender produces an editable `.blend`, body/wheel FBXs, a build manifest and
front/side/rear PNGs. Add `-- --draft` for a faster `draft_front.png` modelling
check, or `-- --draft --views=rear` for a rear check. The hero cameras use a
66 mm lens at 2.6 m height; the side view uses a distant 250 mm lens.
Unreal assets are generated under `/Game/Thanet/Vehicles/KentPoliceV90`.
The importer creates explicit runtime materials and connects both UV textures;
it imports the authored normals and validates every required material assignment.

The existing `ThanetPoliceCar` pawn now uses estate wheel spacing, tyre radius,
suspension height, visual origin and cabin collision. **E** calls/enters the car
on clear ground or exits when stopped; **WASD** drives, **Space** brakes,
**R** recovers and **L** switches blue lights. The existing Thanet map and
walking/flying controls remain in use.

Driving is a single-player exploration physics model, not a calibrated V90
drivetrain simulation. Existing map collision defects still matter. No detailed
interior, siren audio, damage model or multiplayer implementation is included.

## Validation

The original V90 runtime integration built and passed
`Thanet.Vehicle.PhysicsAndSwitching` on 11 September 2026. The test
covers suspension support, acceleration, braking, reverse, steering, wall
collision, recovery and walking/vehicle possession transfer. It is a controlled
physics fixture, not a full-isle playthrough. Revision 2 retains that wheelbase,
tyre radius and collision setup; its changes are visual assets and materials.

The mesh build asserts bilateral shell symmetry within 0.01 mm and finite UVs.
`build_manifest.json` records the measured error, UV channels and geometry counts.
The current shell plus silhouette features uses 30,152 triangles; each wheel
uses 4,568 triangles, for approximately 48,000 triangles per complete vehicle.
The export welds coincident vertices and recalculates outward face directions.
Use `-- --no-render` to rebuild only the editable model and game exports.

The Blender build uses CPU Cycles for compatibility with the installed driver;
the detected OptiX device could not compile Blender 5.2's kernel. No system or
driver settings were changed. `--views=side,rear` can render a subset without
altering the generated geometry.
