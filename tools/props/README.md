# Props

Street furniture for the walkable world. Each prop is a Blender script in this folder that
writes an FBX + albedo pair into `unity/VirtualMargate/Assets/_Project/Art/Props/<Name>/`,
and `Margate/7 - Build Props` (`MargatePropBuilder.cs`) turns the pair into URP materials,
an LODGroup, a collider and `P_<Name>.prefab` next to the source.

```bash
blender --background --factory-startup --python tools/props/build_litterbin.py
# then in Unity:  Margate/7 - Build Props
```

Blender 5.2 or later (bpy + numpy, both bundled). Mac: `/Applications/Blender.app/Contents/MacOS/Blender`.

---

## Litter bin — Glasdon Jubilee 110

The black hooded bin with the gold `LITTER` band that stands on every Thanet pavement.
Scanned from a real one (RealityScan, phone video), rebuilt as clean parametric geometry,
snapped to the manufacturer's published size, and given a generated stylised texture.

| | |
|---|---|
| Size | 1.158 × 0.598 × 0.553 m (spec) |
| LODs | 2216 / 1128 / 308 tris — thresholds 12% / 4% / 1% screen height |
| Texture | `T_LitterBin_D.png` 1024×512 sRGB, one material for all LODs |
| Shell | 23 mm wall, cut apertures on LOD0/1; LOD2 is a single skin with the openings painted |
| Origin | base centre, on the ground, Y up |
| Provenance | `data/provenance/litterbin.json` |

`build_litterbin.py` needs **no inputs**. Every dimension in it was measured from the scan
and lives in the script as a named constant; the scan itself (50 MB) is not in the repo.

### How it was made

1. **Capture.** 9 s handheld phone orbit, 720p. Frames pulled with
   `ffmpeg -vf fps=15 -q:v 1 -qmin 1` (138 frames). Blur was scored with ffmpeg's
   `blurdetect`; this clip needed no culling, the kitchen test clip did.
2. **RealityScan 2.2** → OBJ, 507k faces, 8k texture. Reconstruction region was left wide,
   so the export included the car park, a planter and a passer-by.
3. **Blender, headless.** Cropped to the bin (ground plane fit, then the empty radial gap
   between bin and background), stood upright on its own wall-normal axis, squared, ground
   bisected, decimated to 100k, stubber hole cut, hood recoloured.
4. **Measured.** 60 horizontal slices gave the profile: a straight rounded square body
   (half-width 3.78 scan units, superellipse n≈5.2) with raised bands at the foot and under
   the hood (4.02–4.05, rounder n≈3.4), a vertical hood to z=13.9, a ~1-unit shoulder onto a
   near-circular plateau (r 2.9) at z=14.85, apertures 4.0 × 2.0 centred at z=12.6 on all
   four faces, plates from the baked atlas.
5. **Rebuilt** as a superellipse sweep (96 → 32/16/12 verts per ring), solidified, apertures
   booleaned, scan texture baked with Cycles to check placement, then **replaced** by the
   generated albedo the script now produces directly: flat plastic in the scan's sampled
   tone, straight gold lines, `LITTER` rendered from a real serif font, framed plates.

### Caveats — read before scanning the next bin

- **Black glossy plastic photographs as the sky.** The hood came back light grey mush with
  sky-reflection texture and the stubber hole bridged over with flat triangles. Recolour
  the hood; do not try to bake it. Any dark reflective street object will do this.
- **The scan is not the spec.** The scan read 7.80 × 7.15 units and one face looked
  "dented" 0.5 units in. It was not dented — the Jubilee 110 is **598 × 553 mm**, not
  square. Check the manufacturer's dimensions before "fixing" a scan, and use them for scale;
  three axes agreed on the same factor within 1.5%.
- **Cutting the ground removes the foot.** A bisect at ground+margin took 0.37 units off
  the base. The script restores it; the total height is what is matched to spec.
- **Video frames have no EXIF.** RealityScan solves focal length from the imagery. Fine for
  a single-camera clip; the thing to suspect first if alignment fragments.
- **Bake UVs stretch at profile steps.** Laying out the atlas by mean vertex displacement
  between rings gave a 0.15-unit step 78 rows and the 0.75-unit LITTER band 48. The script
  now lays v out by 2D profile length with a density weight per segment, and places all art
  by **z**, never by row. Change the profile and the art stays put.
- **Vertex colours lie about infill.** RealityScan's vertex colours were dark where its
  texture was sky-grey. Classify by sampling the texture, not the vertex colours.
- **Unity has no glTF importer in this project** (`Packages/manifest.json`), so the asset is
  FBX. Export from Blender with `apply_scale_options='FBX_SCALE_ALL'` and
  `bake_space_transform=True` or you get the classic 0.01 scale and −89.98° root rotation.
- **`.fbx` and `.png` are LFS** (`.gitattributes`). Commit with git-lfs installed.
- **Fonts differ per machine.** The script looks for Times New Roman Bold in the usual
  Windows/macOS/Linux places and falls back to Blender's built-in sans. The committed texture
  was built on Windows.

### Not done

- Nothing places bins yet. The OSM extract already carries `amenity=waste_basket` nodes
  (step 01 fetches amenity points), so the obvious next step is a scatter pass that drops
  `P_LitterBin` at each one, draped to the DTM — real bins in their real places.
- Plates are blank gold. The council wave logo and the pictogram can be added to the
  albedo generator if they are wanted at walking distance.
