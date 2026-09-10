# `renders/` — the visual regression record

Each subdirectory here is **one commit hash**, holding the *same* set of viewpoints rendered from the
Isle of Thanet level at that commit:

```
renders/
  b1cd3e5/                       <- git rev-parse --short HEAD at render time
    manifest.json                <- what was rendered, from where, with which camera
    margate/
      margate_bay_from_the_north_west.png
      marine_terrace_west_past_dreamland.png
      ...
    cliftonville/  broadstairs/  ramsgate/  westgate-on-sea/
    birchington/   westwood/     manston/   acol/
  <next hash>/
    ...
```

Nine towns × five locations = **45 images per snapshot**. The point is not that the pictures are pretty.
The point is that they are *the same pictures*, so that putting two snapshots side by side shows whether
the model got better.

## The camera set is fixed, and lives in one file

Every viewpoint — position, aim, height above ground, field of view, and the capture size and exposure —
is defined in [`projects/one/Tools/ue/render_set.json`](../projects/one/Tools/ue/render_set.json).
Nothing about a frame is a command-line argument, and no camera is stored as a yaw: the yaw is derived
from the camera→subject bearing every run, so two snapshots cannot drift apart through a typo.

That file is also where the honesty lives. Read its `honesty` and `known_soft_spot` blocks before
drawing a conclusion from a picture. Several of these frames were chosen *because* they show current
defects: every building is an untextured grey prism, the OSM debug overlay is drawn in magenta over every
road, the offshore tiles are a flat fabricated plate at −0.6 m ODN, the D1 tile-boundary seams run
through the aerials, and Acol's own anchor sits outside the clip so its five frames are of Acol's
surroundings. Nothing was moved, aimed or exposed to hide any of that, and no image is post-processed.

**Corrected 2026-09-09 by the first full snapshot.** This paragraph used to say the road corridor is
*not* buried at eye level, on the strength of a downward trace at the Marine Terrace camera. The 45
frames of `b1cd3e5` disprove it. Of the 31 eye-level frames that stand on or look along a road, the
carriageway is **missing from 16** — grass between two drawn footways, with the magenta overlay still
on top — and partly lost in 4 more. The trace was not wrong: at those same cameras the engine's own
downward trace still hits the road 2.7–6.0 cm above the landscape, and hiding every `LandscapeProxy`
brings the whole street back (`projects/one/Tools/ue/diag_road_visibility.py`). The conform left about
3 cm of clearance and the surface the landscape *rasterises* is not the surface its height query
returns, so the drawn ground wins wherever the 1 m DTM moves more than that inside a quad. The LOD 0
pin is applied and is not the explanation — it is still part of the spec, not a knob, because without
it the same frames would be worse and for a different reason. `renders/b1cd3e5/INDEX.md` has the
numbers and the pictures. **Do not restore the old claim without re-measuring it against a snapshot.**

**Corrected again 2026-09-10 by the second full snapshot, `7c8b4a6`.** The sentence above that says "the
LOD 0 pin is applied and is not the explanation" is **wrong**, and it is wrong in the most expensive
way a sentence can be: it asserted the opposite of what the picture was showing.
`capture.landscape_lod0_screen_size` was 8.0, and `LOD0ScreenSize` is the screen size at which LOD 0
*stops* — screen size falls with distance, so a threshold of 8.0 is above anything the ground subtends and
every landscape component drew at its **coarsest** level, which is exactly the artefact the pin was
believed to remove. The spec now sets it `null`, `07_render_set.py` reads the proxies' real LOD
properties back into the report, and `render_set.ps1` folds them into `manifest.json` per image, so no
future reader has to take a comment's word for it. With that one property changed and nothing else
touched about the cameras, the carriageway is drawn in **30 of the 31 road frames instead of 15**
(`renders/7c8b4a6/INDEX.md`). The two paragraphs above are kept, not deleted, because the record of
what was believed and when is the point of this directory.

The three off-isle towns in `sources/config/thanet_towns.json` — **minster, monkton, cliffsend** — are
deliberately excluded: they lie outside the Wantsum cut, so there is no terrain under them to photograph.

## Render a new snapshot (one command)

From the repo root, with no Unreal editor open (headless and GUI fight over asset locks in `Content/`):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/render_set.ps1 -PerTown
```

That resolves the current commit, creates `renders/<hash>/<town>/`, renders all 45 frames, and writes
`renders/<hash>/manifest.json`. It refuses to overwrite an existing snapshot unless you pass `-Force`.

Useful variants:

```powershell
# one town, or one location, into the same snapshot directory
... -File projects/one/Tools/render_set.ps1 -Only "margate"
... -File projects/one/Tools/render_set.ps1 -Only "broadstairs/st_peters_high_street"

# print the set and the camera each location resolves to, render nothing
... -File projects/one/Tools/render_set.ps1 -List
```

`-PerTown` runs one editor commandlet per town. World Partition has no unload from Python, so a single
process that streams nine towns keeps every region resident; an out-of-memory kill costs the whole run.
Measured on 2026-09-09: a single batch of **two** locations (one aerial, one street) took **115 s** wall
— editor start, one 1500 m region stream, two captures — and reached **9.2 GB** resident, with the
process taking another minute to die after `LogExit`. Nine batches of five will take somewhere around
an hour, mostly editor startup, streaming and teardown. Use `-PerTown` for the full set.

A frame that comes back black, empty or blown out **fails the run** rather than being written into a
snapshot (`render_set.json → capture.guards`), and the driver additionally refuses any image under 50 KB.
An incomplete snapshot is recorded as `counts.partial = true` in its manifest.

### Then quality-check it, and write its INDEX.md

The driver's guards only prove a frame is not black and not tiny. Run the independent check as well —
it decodes every PNG with stdlib zlib (there is no PIL on this machine) and fails a frame that is a
single flat colour, is not fully opaque, or is more than 85 % one colour, which is what an all-sky or
all-grass frame looks like when a camera is wrong or a region never streamed:

```bash
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/qc_renders.py renders/<hash>
```

Then write `renders/<hash>/INDEX.md`: one row per image saying what it shows and what is wrong in it.
`renders/b1cd3e5/INDEX.md` is the model to follow, and the first thing a future session should read.
A snapshot without an INDEX is a pile of pictures nobody will interpret in six months.

### Don't trust exit 0 on its own

`Tools/ue/run_ue_python.ps1` rewrites the engine's exit code to 0 whenever the Python script succeeded
and the only counted engine error is this machine's VC++ redistributable advisory. Measured on
2026-09-09, that override also swallows an **access violation**: both smoke runs returned a raw
`-1073741819` (`0xC0000005`) from `UnrealEditor-Cmd`, after `LogExit: Exiting`, on runs whose images and
reports were complete and correct and whose logs held no crash marker. It is a teardown crash after the
work finished.

`render_set.ps1` therefore does not take exit 0 as proof. Per batch it requires the script's own
`THANET_OK` line in the log, an empty crash-marker scan, the report file, and then every image on disk
at its expected size — and it records the **raw** engine exit code in `manifest.batches` either way. If
you see the yellow `NOTE ... raw exit code` line, that is this, already accounted for. If you see a
`THANET_OK`, crash-marker or missing-image failure instead, the run genuinely did not finish.

## Compare two snapshots

`manifest.json` is what makes two directories comparable. It records the commit and its full hash, the
ISO date, the spec's own sha256, the engine version, the capture settings, whether the worktree was
dirty, and one entry per image with the location id, the **camera transform actually used** (including
the ground height sampled at the camera and the resulting absolute Z) and the file's size and sha256.

Start every comparison by proving the cameras were the same:

```bash
# same spec => same 45 cameras.  (`python` on this box is a broken Store stub; use the env interpreter.)
PY=C:/Users/Shadow/code/3duk-env/env/python.exe
$PY -c "import json;print(json.load(open('renders/A/manifest.json'))['spec']['sha256'])"
$PY -c "import json;print(json.load(open('renders/B/manifest.json'))['spec']['sha256'])"
```

Then find which frames changed at all, without opening a single image. **Read the caveat under the
snippet before trusting a `CHANGED` line** — a matching sha256 proves a frame did not change, but a
differing one does not prove it did.

```bash
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
C:/Users/Shadow/code/3duk-env/env/python.exe - <<'PY'
import json
A = json.load(open("renders/A/manifest.json"))
B = json.load(open("renders/B/manifest.json"))
a = {i["id"]: i for i in A["images"]}
b = {i["id"]: i for i in B["images"]}
print("spec identical:", A["spec"]["sha256"] == B["spec"]["sha256"])
for k in sorted(set(a) & set(b)):
    if a[k]["sha256"] != b[k]["sha256"]:
        dz = round(b[k]["camera"]["eye_z_m"] - a[k]["camera"]["eye_z_m"], 3)
        print("CHANGED %-46s  dbytes %+8d  camera dz %+7.3f m" % (k, b[k]["bytes"] - a[k]["bytes"], dz))
print("only in A:", sorted(set(a) - set(b)))
print("only in B:", sorted(set(b) - set(a)))
PY
```

A non-zero `camera dz` is not a bug: `camera_height_m` is metres **above the ground**, so an eye-level
camera follows the terrain as the terrain is corrected. That is deliberate — a viewer standing on the
street must stay standing on it — and it is exactly why the manifest records the sampled ground and the
absolute Z, so vertical drift is a number you can read rather than something invisible.

### The renderer is *nearly*, not exactly, deterministic

Measured on 2026-09-09 by rendering the same two cameras twice from the same commit and the same spec:

| frame | pixels differing between two runs | worst channel delta |
|---|---|---|
| `margate/marine_terrace_west_past_dreamland` (eye level) | 0 of 1,440,000 | 0 |
| `margate/margate_bay_from_the_north_west` (aerial) | 9 of 1,440,000 (0.0006 %) | 21 |

So: **equal sha256 ⇒ nothing changed. Different sha256 ⇒ maybe nothing changed.** Use the hash as the
cheap filter that clears most of the set, then judge the rest by eye and by the numbers the manifest
already carries per image — `bytes`, `guards.mean_luminance`, `guards.distinct_rgb`. A handful of stray
pixels in an aerial is engine noise; a luminance shift of whole points, or a visible difference at the
same zoom, is the model.

Then look at the frames that changed, side by side, at the same zoom.

## These PNGs cost real repository space, forever

`.gitattributes` sends `*.png` through **git-lfs**, so the images do not bloat the git object database —
but LFS storage is still storage, and a git history never forgets. At the current 1600 × 900 capture the
two measured frames came out at 1.5 MB (eye level) and 1.9 MB (aerial), so a full snapshot of 45 images
is roughly **70–80 MB**, and every snapshot you commit adds about its own size to the repository
permanently. You cannot get it back by deleting the directory later.

So: take a snapshot when a commit meaningfully changes what the model looks like, not on every commit.
Keep the manifests (they are small text) even for snapshots you would rather not have taken — the record
of what was measured is worth more than the disk it costs.
