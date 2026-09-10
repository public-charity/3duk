"""Corridor conform -- burn the road corridor into a COPY of the landscape heightmap (D3).

Why this exists
---------------
BRIEF 1.1 forbids following the raw LIDAR point for point: the road sits on a smoothed curve, and
its cross-section is a 6-12 m flat/cambered plank.  The landscape carries the raw 1 m survey.  A
plank on a rough field is below the field somewhere across its width at nearly every station -- the
whole-network measurement before this pass was 89.06 % of 666,314 stations, 866.06 km of 968.84 km,
worst 13.698 m (``projects/one/Saved/Diag/fusion_before_all.json``).  That is what "the road geometry
fuses with the landscape" means, and no smoothing window fixes it (docs/TERRAIN_ROADS.md 4.5).

So the ground under the built surface is conformed to the road.  The SURVEY product
(``data/<site>/out/terrain``) and the adapter's landscape product are never written: this pass reads
them and writes a new product beside them, with a manifest that says in words that it is no longer
the raw survey and a signed delta raster per tile that proves it cell by cell.

The rule, per 1 m landscape cell, from the cell's signed lateral offset ``d`` to the nearest point of
the road centreline (``o`` = ``edge_offset(side)``, ``back`` = kerb + pavement width on that side,
both per station from the profile data):

    |d| <= o                     the road surface itself,  z_ref + d sin B + camber(d) cos B
    o < |d| <= o + back          the kerb/pavement shelf,  held at the road-edge level
    ... + verge                  the verge,                held at the road-edge level
    ... + blend                  smoothstep back to the raw survey value of that cell

everything but the blend tail sunk by ``sink_field(params, d, ...)`` -- a depth that varies PER
STATION, PER SIDE and ACROSS THE SECTION, read from the profile data: as deep as the thing that
covers that particular place can hide, and no deeper.  A side with a kerb and pavement covers
``SideSpec.skirt`` (0.30 m, DESIGN.md 4.2); a bare footway or railway edge covers only its own
``skirt_drop_m`` (<= 0.03 m by schema); under the carriageway and out in the verge nothing has to be
hidden at all.  See ``sink_sides`` and ``sink_field``.

A sink is needed at all because "the ground is below the road" in the DATA is not the same claim as
"the ground draws below the road" in the ENGINE.  Measured over 241,205 points inside real corridors
on the shipped product (``Saved/Clearance/rules_conformed.json``): the bilinear rule the burn writes
through and the landscape's own triangulated rule disagree by 0.4 mm at the median and 13 mm at the
p99, and NEITHER puts any ground above any road -- yet the landscape still drew over the carriageway
in 16 of 31 street frames of ``renders/b1cd3e5``.  What does that is the landscape's LEVEL OF DETAIL,
which is not the surface its height query returns.

AND THE SINK ALONE CANNOT BUY IT BACK, WHICH IS WHY THE VERGE IS 4.5 m.  The mesh the landscape
rasterises past about 380 m is a resample of each 127-quad subsection onto 63, 31 or 15 quads --
vertices 2.02, 4.10 and 8.47 m apart (``terrain.LandscapeLodSurface``, transcribed from
``ULandscapeComponent::GenerateHeightmapMips`` and ``LandscapeVertexFactory.ush``).  A triangle
8.5 m across is anchored on ground OUTSIDE a 2 m verge, so no depth under the kerb can stop it
cutting the carriageway.  What stops it is flat ground for a whole coarse stride either side of the
road, and the resample's weights are non-negative and sum to one, so lowering LOD-0 cells can only
lower the drawn surface.  Measured on an 18-document A/B subset (1,249 splines), stations with ground
above the road: LOD 1 1.27 % -> 0.11 %, LOD 2 10.37 % -> 1.64 %, LOD 3 22.86 % -> 7.57 %, at
unchanged float.  Verge 2.0 m with the same sink rule gets LOD 2 to 2.57 % and LOD 3 only to 13.72 %,
so the widening is worth its ground.

The blend length is chosen per station and side so the fill or cut face lies at ``batter_deg``
(1:1.5, the usual earthwork batter) rather than at a fixed width: a fixed 3 m blend turns a 4 m cut
into a 53 deg wall.  It is clamped to [blend_min_m, blend_max_m].

Where two corridors cover a cell the LOWER target wins within a zone, and a nearer zone always wins
over a farther one (built surface > verge > blend).  Taking the minimum is what makes the acceptance
gate provable: no road can be penetrated by ground that another road put there.  Where the two
disagree by a lot it is a grade separation -- a bridge over the railway -- and the minimum is also
the right answer there: the ground follows the lower way and the bridge deck flies over it.

JUNCTIONS.  Two things, and they are different.

1. The corridor burn stamps the UNTRIMMED extent of every spline: ``Spline`` is built here with
   ``trim=None`` (SCHEMA.md 4.18 -- the shared spline layer trims an arm back to the junction so
   Renderer A can fill the disc and Renderer B can turn the corner).  Trimming is a mask on ``s`` and
   does not move the surface at any station, so burning the untrimmed extent writes exactly the same
   heights the trimmed arms sit on AND claims most of the ground under the junction disc from every
   arm that reaches it.  Trimming the burn as well would leave an unclaimed hole of up to
   (2 * trim_radius)^2 at every junction and the survey standing in it.  So: do not pass a trim in
   here, and if that ever becomes the default, take the untrimmed spline.

2. A corridor is a BAND along one spline, and between two arms, close to the node, there are wedges
   no band covers as built surface -- only as feathered blend, which is allowed to rise back to the
   survey.  Renderer A lays tarmac across exactly those wedges (``road.junction_surface``), so the
   ground under them has to be conformed to the patch and not to the arms.  Measured over the isle
   before ``junction_targets`` existed: **814 of 87,969 patch vertices (0.93 %) sat BELOW the
   conformed ground, worst 2.890 m** (``Saved/Diag/junction_isle.json``) -- ground standing up
   through the middle of a crossroads.  ``junction_targets`` rasterises the patch polygon into the
   corridor as built surface with ``road.junction_target_z`` as its target, so the burn and the mesh
   are one surface rather than two transcriptions of one.  After it: **94 of 87,969**
   (``Saved/Clearance/junction_isle_v4.json``), and every one that can be attributed belongs to one
   of the 7 junctions with a BRIDGE arm, whose deck carries the elevation of the ground under the
   structure and is therefore not a surface any ground should be conformed to.

Pure numpy (DESIGN.md 14): no scipy, no GDAL, no bpy, so this runs under the env python, Blender's
python and the test suite alike.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from . import schema as S
from .spline import camber_h

RANK_SURFACE = 0        # the built surface: carriageway + kerb + pavement
RANK_VERGE = 1          # the verge shelf, still held at the road-edge level
RANK_BLEND = 2          # the smoothstep tail back to the survey
RANK_NONE = 3
_U_STEPS = 10000        # blend fraction quantisation inside the arbitration key
_RANK_STRIDE = _U_STEPS + 1
KEY_NONE = np.uint16(RANK_NONE * _RANK_STRIDE)


@dataclass
class CorridorParams:
    """Every number the burn depends on; copied verbatim into the product manifest."""
    sink_m: float = 0.03            # the FLOOR of the sink (see sink_profile); kept as the name the
                                    # manifest and the driver have always used
    sink_max_m: float = 0.15        # the CAP, from measurement -- see sink_profile
    sink_cover_frac: float = 0.5    # how much of the block's own cover the sink is allowed to use
    sink_taper: float = 0.10        # the cross-section slope the sink field may use to get from one
                                    # side's cover to another's, and to reach sink_max_m away from a
                                    # covered face.  1:10.  See sink_field.
    sink_flat_m: float = 1.5        # how far either way from a covered face the sink is held FLAT
                                    # at that face's depth before the taper starts.  See sink_field.
    sink_covered_max_m: float = 0.15  # the cap AWAY from any face -- under the carriageway, and out
                                    # in the verge -- where nothing has to be hidden.  sink_max_m is
                                    # still the cap AT a face, which is what float is measured at.
    verge_m: float = 4.5
    blend_min_m: float = 3.0
    blend_max_m: float = 12.0
    batter_deg: float = 34.0
    lateral_step_m: float = 0.7
    station_step_m: float = 0.5
    end_overhang_m: float = 1.5
    sag_delta_m: float = 1.5
    sag_factor: float = 1.5
    apron_m: float = 1.5
    clamp_m: float = 2.0
    report_delta_m: float = 2.0
    layers: tuple = ("roads", "rail")

    def to_json(self) -> dict:
        d = asdict(self)
        d["layers"] = list(self.layers)
        d["note"] = ("corridor half-width per side = edge_offset(side) + kerb_width + pavement_width "
                     "(from the profile data, per station) + verge_m + blend; blend is per station and "
                     "side: clamp(|shelf - survey| / tan(batter_deg), blend_min_m, blend_max_m)")
        d["sink_note"] = ("the sink is PER STATION *and PER SIDE and per lateral offset*, not one "
                          "number for the cross-section (conform.sink_sides + conform.sink_field): "
                          "sink(d) = min(sink_max_m, sink_left + sink_taper*|d - core_left|, "
                          "sink_right + sink_taper*|d + core_right|), where sink_side = "
                          "clip(sink_cover_frac * (SideSpec.skirt where that side carries a kerb or "
                          "pavement, else the road profile's skirt_drop_m), sink_m, sink_max_m).  "
                          "At each side's outer face it is exactly that side's depth, so the float "
                          "measurement is unchanged; under the carriageway and out in the verge it "
                          "reaches %g m, because there the built block or the ribbon itself covers it."
                          % self.sink_max_m)
        d["sink_evidence"] = {
            "floor_m": self.sink_m,
            "floor_why": ("clears the h16 half-quantum 0.0039 m and the p99 of the bilinear vs "
                          "landscape-triangulated disagreement inside real corridors, 0.013 m over "
                          "241,205 points; and is the most a ribbon with no kerb can hide AT ITS OWN "
                          "EDGE (schema caps skirt_drop_m at 0.03 m)"),
            "cap_m": self.sink_max_m,
            "cap_why": ("engine sweep, one camera, one property changed: the landscape lowered by 0, "
                        "5, 10 and 20 cm under cliftonville/princess_margaret_avenue_at_northdown and "
                        "birchington/railway_bridge_over_minnis_road.  0 cm leaves green wedges across "
                        "the carriageway, 10 cm is clean on both, so the DRAWN ground beats the QUERIED "
                        "ground by up to ~0.10 m at eye level; 0.15 m is that with a factor of 1.5 and "
                        "half the 0.30 m pavement skirt, so nothing floats"),
            "taper_why": ("the sink field is allowed to change by sink_taper per metre across the "
                          "section.  That is what lets one side be deep and the other shallow without "
                          "a step, and it is self-limiting on a narrow ribbon: at 1:10 a 0.18 m "
                          "cycleway earns 9 mm, not a notch."),
            "why_it_is_no_longer_a_minimum": (
                "the old rule took the MINIMUM over the two sides and applied it to the whole "
                "cross-section, so 28.3 % of built length sat at the 0.03 m floor because ONE side "
                "had no kerb -- and every frame of renders/7c8b4a6 that still lost its carriageway "
                "stood on such a road.  The constraint was never symmetric: it is about what ONE "
                "outer face can hide."),
            "what_the_sink_cannot_fix": (
                "the landscape's level of detail, most of it.  Measured on the shipped 7c8b4a6 "
                "product over 660,835 stations with the engine's OWN LOD rule "
                "(terrain.LandscapeLodSurface, transcribed from GenerateHeightmapMips and "
                "LandscapeVertexFactory.ush; Saved/Clearance/fusion_before_v5.json): ground above "
                "the road at 0.0002 % of stations at LOD 0, 0.76 % at LOD 1, 8.18 % at LOD 2 and "
                "22.26 % at LOD 3.  The earlier figures of 0.034 / 1.93 / 8.58 % were measured "
                "against a WRONG model of the LOD mesh (a 2^k decimation anchored on the tile grid); "
                "the engine's stride is 127/63, 127/31, 127/15 = 2.016, 4.097, 8.467 m and its "
                "anchor is the subsection lattice.  Depth alone cannot buy those back -- a coarse "
                "triangle 8.5 m across is anchored outside the corridor -- which is why the verge "
                "shelf, and not only the sink, is what this rule widens and lowers."),
        }
        return d


@dataclass
class MosaicGrid:
    """The site's 1 m sample grid: cell centres on integer local metres, row 0 = north."""
    nx: int
    ny: int
    res: int
    tile_m: float = 512.0
    px_m: float = 1.0

    @property
    def q(self) -> int:
        return self.res - 1

    @property
    def W(self) -> int:
        return self.nx * self.q + 1

    @property
    def H(self) -> int:
        return self.ny * self.q + 1

    def tile_origin(self, i: int, j: int):
        """(row, col) of tile (i, j)'s north-west sample in the mosaic."""
        return (self.ny - 1 - j) * self.q, i * self.q

    @classmethod
    def from_manifest(cls, man: dict) -> "MosaicGrid":
        return cls(nx=int(man["nx"]), ny=int(man["ny"]), res=int(man["res"]),
                   tile_m=float(man["tile_m"]), px_m=float(man.get("px_m", 1.0)))


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class ConformAccumulator:
    """The mosaic-wide arbitration.  One cell, one answer -- which is also what keeps the tile seams
    intact: a sample shared by two tiles is one cell here and is cut out of the mosaic twice."""

    def __init__(self, grid: MosaicGrid):
        self.grid = grid
        self.key = np.full((grid.H, grid.W), KEY_NONE, dtype=np.uint16)
        self.z = np.full((grid.H, grid.W), np.inf, dtype=np.float32)
        self.stats = {"contributions": 0, "cells_touched": 0, "arbitrations": 0,
                      "arbitration_max_drop_m": 0.0, "splines": 0, "splines_skipped": 0}

    # -- the write ---------------------------------------------------------------------------
    def add(self, col, row, z, rank, u=None):
        """One batch of contributions.  Duplicates inside the batch are handled by the same
        lexicographic rule as duplicates across batches: (rank, blend fraction) then lowest z."""
        if col.size == 0:
            return
        ru = (np.asarray(rank, dtype=np.int32) * _RANK_STRIDE)
        if u is not None:
            ru = ru + np.clip(np.rint(np.asarray(u) * _U_STEPS), 0, _U_STEPS).astype(np.int32)
        ru = ru.astype(np.uint16)
        idx = (np.asarray(row, dtype=np.int64) * self.grid.W + np.asarray(col, dtype=np.int64))
        z = np.asarray(z, dtype=np.float32)
        flat_key = self.key.reshape(-1)
        flat_z = self.z.reshape(-1)
        old = flat_key[idx]
        np.minimum.at(flat_key, idx, ru)
        new = flat_key[idx]
        improved = new < old
        if improved.any():                      # a nearer zone displaces whatever was there
            flat_z[idx[improved]] = np.inf
        tied = ru == new
        if tied.any():
            it, zt = idx[tied], z[tied]
            prev = flat_z[it]
            np.minimum.at(flat_z, it, zt)
            drop = prev - flat_z[it]
            hit = np.isfinite(prev) & (drop > 1e-3)
            if hit.any():
                self.stats["arbitrations"] += int(hit.sum())
                self.stats["arbitration_max_drop_m"] = max(self.stats["arbitration_max_drop_m"],
                                                           float(drop[hit].max()))
        self.stats["contributions"] += int(col.size)

    def finish(self):
        self.stats["cells_touched"] = int((self.key != KEY_NONE).sum())
        return self.stats


def quantise_h16(z, per_unit=128.0, offset=32768.0):
    """The landscape's own encoding (DESIGN.md 8): the burn is written through it, so what the test
    measures and what the engine imports are the same numbers, not the same intention."""
    return np.clip(np.rint(np.asarray(z, dtype=np.float64) * per_unit) + offset, 0, 65535)


def burn_heightfield(hf, grid: MosaicGrid, acc: "ConformAccumulator", per_unit=128.0, offset=32768.0,
                     quantise: bool = True):
    """A copy of ``hf`` with the accumulator's targets written into its tiles.  Used by the tests and
    by anything that wants the conformed field without going through the product directory."""
    import copy as _copy
    out = _copy.copy(hf)
    out.tiles = {}
    res = grid.res
    changed = 0
    for key, T in hf.tiles.items():
        i, j = key
        r0, c0 = grid.tile_origin(i, j)
        k = acc.key[r0:r0 + res, c0:c0 + res]
        zt = acc.z[r0:r0 + res, c0:c0 + res]
        m = (k != KEY_NONE) & np.isfinite(zt) & np.isfinite(T)
        A = np.array(T, dtype=np.float32)
        if m.any():
            v = np.asarray(zt, dtype=np.float64)[m]
            if quantise:
                v = (quantise_h16(v, per_unit, offset) - offset) / per_unit
            changed += int(m.sum())
            A[m] = v.astype(np.float32)
        out.tiles[key] = A
    out.source = (hf.source or "") + " +conform(%d cells)" % changed
    return out


# -------------------------------------------------------------------------------------------
def dense_stations(sp, step_m: float, overhang_m: float = 0.0, max_turn_rad: float = 0.0):
    """Uniform arc-length samples of the centreline: the stamping rays.  Only the geometry of the
    ray matters here; every height is evaluated at the exact projected station afterwards.

    ``overhang_m`` extends the rays straight on past both ends.  Without it the four cells of the
    quad the road's own end vertex sits in are only partly stamped, and the unstamped corner keeps a
    survey height that can still be above the cap -- measured at 9.3 mm on the first smoke run.  The
    height carried out over the overhang is the end cross-section (the station is clamped to
    [0, L]), which is also what closes the 1-2 m gap where a side road stops short of the way it
    joins.

    ``max_turn_rad`` bounds how far the ray may swing between two samples.  Where a way turns
    sharply the perpendicular rays fan out and leave an unstamped wedge on the OUTSIDE of the
    corner, which the road ribbon's own quad covers -- 19 mm of ground left standing in the
    carriageway of roads:851451479:0 before this was added.  Extra rays are inserted there with the
    position and the direction both interpolated, which is exactly the surface the quad sweeps."""
    step = max(step_m, 1e-6)
    n = max(2, int(np.ceil(sp.length / step)) + 1)

    def frames_at(u):
        x = np.interp(u, sp.s, sp.xy[:, 0])
        y = np.interp(u, sp.s, sp.xy[:, 1])
        tx = np.interp(u, sp.s, sp.t_h_xy[:, 0])
        ty = np.interp(u, sp.s, sp.t_h_xy[:, 1])
        L = np.hypot(tx, ty)
        L[L < 1e-12] = 1.0
        return x, y, tx / L, ty / L

    # every STATION is a ray, not only the uniform grid: the ribbon's rows are the stations, so a
    # station missing from the sweep is a row of road whose ground was never claimed.  Splines whose
    # last few stations sit inside a few centimetres with the tangent swinging 90 degrees (a
    # Catmull-Rom tail on a near-duplicate end point -- roads:30893057:0, roads:169730575:0) are the
    # ones that showed it.
    sd = np.unique(np.concatenate([np.linspace(0.0, sp.length, n), sp.s]))
    x, y, tx, ty = frames_at(sd)
    if max_turn_rad > 0.0 and len(sd) > 2:
        dot = np.clip(tx[:-1] * tx[1:] + ty[:-1] * ty[1:], -1.0, 1.0)
        m = np.maximum(1, np.ceil(np.arccos(dot) / max_turn_rad).astype(np.int64))
        m = np.minimum(m, 256)
        if (m > 1).any():
            idx = np.repeat(np.arange(len(sd) - 1), m)
            off = np.arange(m.sum()) - np.repeat(np.cumsum(m) - m, m)
            f = off / np.repeat(m, m).astype(np.float64)
            sd = np.append(sd[idx] + f * (sd[idx + 1] - sd[idx]), sd[-1])
            # re-interpolated, never lerped between the two ends: the tangent between two rays does not
            # have to lie between their tangents, and lerping it misses exactly the swing that needs
            # the extra rays.
            x, y, tx, ty = frames_at(sd)
    if overhang_m > 0.0:
        m0 = int(np.ceil(overhang_m / step))
        e = np.arange(1, m0 + 1) * step
        sd = np.concatenate([-e[::-1], sd, sp.length + e])
        x = np.concatenate([x[0] - e[::-1] * tx[0], x, x[-1] + e * tx[-1]])
        y = np.concatenate([y[0] - e[::-1] * ty[0], y, y[-1] + e * ty[-1]])
        tx = np.concatenate([np.full(m0, tx[0]), tx, np.full(m0, tx[-1])])
        ty = np.concatenate([np.full(m0, ty[0]), ty, np.full(m0, ty[-1])])
    return sd, x, y, tx, ty


def sink_profile(sp, params: CorridorParams):
    """(N,) how deep the burn may sink the ground under the built surface, per station.

    The sink is not taste and it is not one number for the isle.  It is bounded above by what the
    built block can COVER, and that is profile data:

    * a side that carries a kerb or a pavement hides ``SideSpec.skirt`` -- 0.30 m in every shipped
      edge profile (DESIGN.md 4.2: the block's outer face reaches that far below the road-edge
      plane).  Ground sunk less than the skirt is inside the block and cannot be seen from outside.
    * a way with no kerb and no pavement -- a footway, a track, a railway -- hides only its own
      ``skirt_drop_m``, which the schema caps at 0.03 m (``schema.py:448``).  Sinking such a way
      deeper is daylight under the ribbon's edge, which is the float half of the measurement and is
      exactly render defect 4 of ``renders/b1cd3e5/INDEX.md``.

    So: ``sink = clip(sink_cover_frac * min(cover over the two sides), sink_m, sink_max_m)``:
    0.15 m under a kerbed carriageway, 0.03 m under a bare ribbon, nothing in between invented.

    WHERE THE TWO NUMBERS COME FROM (2026-09-09, clearance agent; every figure measured, not chosen):

    * the FLOOR, 0.03 m.  It has to clear the h16 half-quantum (0.0039 m) and the disagreement
      between the rule the burn writes through and the rule the landscape interpolates with.  Over
      241,205 points inside real Thanet corridors that disagreement is 0.4 mm at the median, 5.4 mm
      at the p95, 13.4 mm at the p99 and 0.799 m at its maximum, with 0.20 % of points over 3 cm and
      0.014 % over 10 cm (``Saved/Clearance/rules_v4.json``) -- so 0.03 m is 2.2x the p99, and it is
      also the most a bare ribbon can hide (schema caps ``skirt_drop_m`` at 0.03 m).

      THAT MEASUREMENT ALSO SETTLES A HYPOTHESIS.  "The conform was burned against bilinear while
      the landscape rasterises triangles, and that is why the roads are invisible" is FALSE at this
      scale: on the shipped 0.03 m product neither rule put ground above the road at ANY of those
      241,205 points (``Saved/Clearance/rules_conformed.json``), and over the whole isle the two
      rules disagree about the gate on exactly one station of 660,835.  The rule still has to be the
      landscape's -- ``Heightfield.sampling`` and ``road_fusion_audit.py --sampling`` both default to
      ``landscape_triangulated`` for that reason -- but it is not what hides a carriageway.
    * the CAP, 0.15 m.  A sweep in the engine, same camera, same level, one thing changed: the
      landscape lowered by 0, 5, 10 and 20 cm under
      ``cliftonville/princess_margaret_avenue_at_northdown`` and
      ``birchington/railway_bridge_over_minnis_road``.  At +0 cm (the shipped 0.03 m sink) green
      wedges cut the carriageway across its width; at +5 cm they are gone on the first and a scatter
      remains on the second; at +10 cm both are clean.  So the drawn ground beats the queried ground
      by up to about 0.10 m at eye level.  0.15 m is that with a factor of 1.5, and it is half the
      0.30 m pavement skirt, so the block still covers it twice over and the float measurement does
      not move (float = sink - skirt = -0.15 m, i.e. none).

    The mechanism behind that engine sweep is the landscape's LEVEL OF DETAIL, which is not the
    surface ``GetHeightAtLocation`` returns -- see ``terrain.LandscapeLodSurface`` and the header of
    ``projects/one/Tools/road_fusion_audit.py``.

    RETRACTION, 2026-09-10.  The paragraph that stood here quoted 0.034 % of corridor points above
    the road at LOD 1, 1.93 % at LOD 2 and 8.58 % at LOD 3.  Those figures were measured against
    ``Heightfield.lod_skeleton``, a model of the LOD mesh with the stride and the anchor both wrong.
    Re-measured on the same shipped product with the engine's own rule, whole isle, 660,835
    stations (``Saved/Clearance/fusion_before_v5.json``): **0.0002 % at LOD 0, 0.76 % at LOD 1,
    8.18 % at LOD 2, 22.26 % at LOD 3**.  The sink did not "buy LOD 1 outright"; it never came
    close.  What this rule does about that is in the module header, and what it cannot do is in
    ``to_json``'s ``what_the_sink_cannot_fix``.
    """
    sides = sink_sides(sp, params)
    return np.minimum(sides[S.LEFT], sides[S.RIGHT])


def sink_sides(sp, params: CorridorParams):
    """``{LEFT: (N,), RIGHT: (N,)}`` -- the deepest the burn may go under EACH side's own outer face.

    This is the correction of the defect the 2026-09-10 verifier found.  The old rule took the
    MINIMUM over the two sides and applied one depth to the whole cross-section, so a road with a
    kerb and pavement on one side only was pinned to the 0.03 m floor along its entire width by the
    side that had no cover.  Measured over the whole isle, 961.5 km of built length
    (``Saved/Clearance/sink_census_v5.json``): **40.5 % of length sat at the floor under the old
    rule, 27.5 % under the new one at the carriageway centre**, and every frame in
    ``renders/7c8b4a6`` that still lost its carriageway stood on such a road
    (``north_foreland_lighthouse`` is ``roads:1028594193:1``, secondary, kerbed on one side, 0.030 m
    at all 112 stations).  Be exact about what this change reaches: only **3.99 % of built length,
    38.4 km**, has sides whose cover DIFFERS -- the rest of the 40.5 % is bare on both sides, and no
    per-side rule can help it.  The other 13 points come from the taper reaching the middle of a way
    wide enough for it.

    The constraint was never symmetric.  It is a statement about ONE face: at the outer face of the
    block on side X, ground more than ``SideSpec.skirt`` below the road-edge plane is daylight under
    THAT face.  What happens under the carriageway, or under the other side's pavement, is not that
    face's business -- nothing can see it.  So each side gets its own depth and ``sink_field`` joins
    them."""
    drop = np.asarray(sp.skirt_drop_m, dtype=np.float64) * np.ones(sp.n)
    out = {}
    for side in (S.LEFT, S.RIGHT):
        spec = sp.side_spec[side]
        has = np.asarray(spec.present, dtype=bool) & (np.asarray(spec.back_offset, dtype=np.float64) > 0.0)
        cover = np.where(has, np.asarray(spec.skirt, dtype=np.float64), drop)
        out[side] = np.clip(cover * float(params.sink_cover_frac),
                            float(params.sink_m), float(params.sink_max_m))
    return out


def sink_field(params: CorridorParams, d, sink_left, sink_right, core_left, core_right):
    """How deep the burn sinks the ground at signed lateral offset ``d`` (+ is LEFT).

    The deepest cross-section that (a) is no deeper than each side's own cover AT that side's outer
    face, (b) never changes by more than ``sink_taper`` per metre across the road, and (c) never
    exceeds ``sink_max_m``:

        sink(d) = min( sink_covered_max_m,
                       sink_left  + taper * max(0, |d - core_left|  - sink_flat_m),
                       sink_right + taper * max(0, |d + core_right| - sink_flat_m) )

    THE TAPER REACHES BOTH WAYS, AND THAT WAS MEASURED, NOT ASSUMED.  An inward-only variant (v6 of
    ``Saved/Clearance/ab_sweep_v5.json``) has the float fraction identical to four decimal places --
    0.141097 either way -- and clearly worse penetration (LOD 2 5.81 % against 4.74 %), so the
    outward half is free and is kept.  What is NOT free is depth close to a face: see the margin.

    ``sink_flat_m`` HOLDS THE SINK FLAT FOR 1.5 m EITHER SIDE OF A COVERED FACE, and it is not
    tidiness -- it is the raster.  The burn is written onto a 1 m grid that the landscape reads by
    interpolating between posts, so a cell 1 m outside the pavement's outer face is read by the very
    triangle that draws the ground AT that face.  Without the margin the taper leaks across the face
    and the measured daylight under it grows: on the 18-document A/B subset, taper with no margin
    took the float fraction from 13.0 % to 21.0 % of stations while the margin keeps it at the
    baseline.  1.5 m is the 1 m reach of that interpolation with half a cell of slack.

    Three more properties, and each one is why a term is there:

    * **At each outer face it is exactly that side's depth**, so the float measurement -- which is
      taken at the outer face of the built block, ``fusion.edge_points`` -- is unchanged, side for
      side, from the old rule on the sides that had cover and strictly deeper only where a face can
      hide it.  A one-side-kerbed road now sinks 0.15 m under its carriageway and 0.03 m under its
      bare edge instead of 0.03 m everywhere.
    * **Under the carriageway it reaches the cap**, because the carriageway ribbon is what covers it
      and the ribbon is opaque.  Depth there is free clearance against the renderer's coarse mesh.
    * **Outside the block it reaches the cap too**, at 1:10, which is the verge falling away from the
      road as a verge does.  That is not decoration: the mesh the landscape DRAWS past about 380 m is
      a resample whose vertices are 2.02, 4.10 and 8.47 m apart (``terrain.LandscapeLodSurface``), so
      what decides whether a road survives at distance is the ground for a whole stride either side
      of it, not the strip under the kerb.  The resample weights are non-negative and sum to one, so
      lowering any LOD-0 cell can only lower the drawn surface: this is the one lever that is
      monotone in the right direction.

    ``sink_taper`` bounds the cost of all three.  A 1:10 cross-fall is invisible on grass, and on a
    ribbon 0.18 m wide (there is one, ``roads:132194822:0``) it earns 9 mm rather than digging a
    notch beside the path."""
    a = float(params.sink_taper)
    flat = float(params.sink_flat_m)
    d = np.asarray(d, dtype=np.float64)
    dl = np.maximum(0.0, np.abs(d - np.asarray(core_left)) - flat)
    dr = np.maximum(0.0, np.abs(d + np.asarray(core_right)) - flat)
    v = np.minimum(np.asarray(sink_left) + a * dl, np.asarray(sink_right) + a * dr)
    return np.minimum(v, float(params.sink_covered_max_m))


def corridor_half_widths(sp):
    """(N,) per-station built-surface half width per side, from the profile data.

    ``edge_offset`` is the edge contract (DESIGN.md 3.6) -- carriageway plus any parking-bay extra --
    and ``SideSpec.back_offset`` is kerb width + pavement width for that side.  Nothing here computes
    ``width / 2``."""
    out = {}
    for side in (S.LEFT, S.RIGHT):
        spec = sp.side_spec[side]
        back = np.asarray(spec.back_offset, dtype=np.float64) if spec.has_kerb_or_pavement else np.zeros(sp.n)
        out[side] = (np.asarray(sp.edge_offset(side), dtype=np.float64), back)
    return out


def shelf_levels(sp, params: CorridorParams, z_raw_at):
    """Per station and side: the shelf level the built surface holds, the survey level under the far
    edge of the verge, the signed earthwork (shelf - survey; + fills, - cuts) and the blend length
    that puts the fill or cut face at ``batter_deg``.

    Shared by the burn and by the clamped-run report, so the runs handed to the geometry track for
    embankments are exactly the places the burn moved the ground the most."""
    halves = corridor_half_widths(sp)
    sinb = np.sin(np.radians(sp.bank_deg))
    cosb = np.cos(np.radians(sp.bank_deg))
    nfx, nfy = -sp.t_h_xy[:, 1], sp.t_h_xy[:, 0]
    tanb = max(np.tan(np.radians(params.batter_deg)), 1e-3)
    sides = sink_sides(sp, params)
    out = {}
    for side in (S.LEFT, S.RIGHT):
        o, back = halves[side]
        core = o + back
        # this side's OWN depth: the shelf it holds, and therefore the earthwork and blend length it
        # needs, are that side's business (sink_sides).
        sink = sides[side]
        zsh = sp.z_ref + side * o * sinb + sp.surface_h(side * o) * cosb - sink
        off = float(side) * (core + params.verge_m) * cosb
        zr = z_raw_at(sp.xy[:, 0] + off * nfx, sp.xy[:, 1] + off * nfy)
        earth = zsh - zr
        blend = np.clip(np.abs(np.where(np.isfinite(earth), earth, 0.0)) / tanb,
                        params.blend_min_m, params.blend_max_m)
        out[side] = {"o": o, "core": core, "shelf_z": zsh, "raw_z": zr, "earthwork_m": earth,
                     "blend_m": blend, "sink_m": sink}
    return out


def spline_targets(sp, params: CorridorParams, z_raw_at, stats=None):
    """Yield ``(cx, cy, z, rank, u)`` batches: cell centres in LOCAL METRES (integer valued, x east /
    y north from the site origin -- the caller turns them into mosaic row/col), the target height,
    the zone rank and the blend fraction.

    ``z_raw_at(x, y)`` samples the *unconformed* landscape (the blend tail has to reach the survey
    value of the very cell it is writing, or the corridor edge would step)."""
    halves = corridor_half_widths(sp)
    oL, backL = halves[S.LEFT]
    oR, backR = halves[S.RIGHT]
    coreL = oL + backL
    coreR = oR + backR
    reach_L = coreL + params.verge_m + params.blend_max_m
    reach_R = coreR + params.verge_m + params.blend_max_m
    kinds = np.array(sp.camber_kind, dtype=object)
    sinb = np.sin(np.radians(sp.bank_deg))
    cosb = np.cos(np.radians(sp.bank_deg))

    # the shelf level per station and side, and the survey level under the far edge of the verge:
    # together they set how long the blend has to be for a batter_deg face.
    shelf = shelf_levels(sp, params, z_raw_at)
    sink = sink_sides(sp, params)
    # shelf_z already carries the sink; the zone evaluator adds it back for the road surface itself
    zshelf = {side: shelf[side]["shelf_z"] + sink[side] for side in (S.LEFT, S.RIGHT)}
    blend = {side: shelf[side]["blend_m"] for side in (S.LEFT, S.RIGHT)}

    reach_max = float(max(np.max(reach_L + blend[S.LEFT]), np.max(reach_R + blend[S.RIGHT])))
    sd, dx, dy, dtx, dty = dense_stations(sp, params.station_step_m, params.end_overhang_m,
                                          max_turn_rad=0.5 / max(reach_max, 1e-3))
    dnx, dny = -dty, dtx
    sd_c = np.clip(sd, 0.0, sp.length)
    reach_d = np.maximum(np.interp(sd_c, sp.s, reach_L + blend[S.LEFT]),
                         np.interp(sd_c, sp.s, reach_R + blend[S.RIGHT]))
    valid_d = np.isfinite(np.interp(sd_c, sp.s, sp.z_ref))

    step = max(params.lateral_step_m, 1e-3)
    block = max(1, int(200000 / max(int(np.ceil(2 * reach_d.max() / step)) + 1, 1)))
    for a in range(0, len(sd), block):
        b = min(a + block, len(sd))
        R = float(reach_d[a:b].max())
        lat = np.arange(-R, R + 0.5 * step, step)
        if lat.size == 0:
            continue
        keep = valid_d[a:b]
        if not keep.any():
            continue
        PX = (dx[a:b, None] + lat[None, :] * dnx[a:b, None]).ravel()
        PY = (dy[a:b, None] + lat[None, :] * dny[a:b, None]).ravel()
        # Every ladder point claims the FOUR cells of the unit square it falls in, not just the
        # nearest one: a cell is stamped whenever a ladder point lands within 1 m of it in x and y.
        # Rounding to the nearest cell only reaches 0.5 m, and that is not enough where the rays fan
        # out -- a way whose last five stations sit inside 8 cm with the tangent swinging 90 deg
        # (roads:30893057:0) left its own carriageway cell unstamped and 0.096 m of ground standing
        # in it.  Each stamped cell is then projected on its own, so the extra reach costs coverage,
        # never accuracy.
        fx, fy = np.floor(PX), np.floor(PY)
        cx = np.concatenate([fx, fx + 1.0, fx, fx + 1.0])
        cy = np.concatenate([fy, fy, fy + 1.0, fy + 1.0])
        rep = lambda v: np.tile(np.repeat(v[a:b], lat.size), 4)          # noqa: E731
        ex = cx - rep(dx)
        ey = cy - rep(dy)
        tX = rep(dtx)
        tY = rep(dty)
        along = ex * tX + ey * tY
        latc = ex * (-tY) + ey * tX
        s_star = rep(sd) + along
        ok = np.tile(np.repeat(keep, lat.size), 4)
        if not ok.any():
            continue
        cx, cy, latc, s_star = cx[ok], cy[ok], latc[ok], s_star[ok]
        yield _evaluate(sp, params, cx, cy, latc, s_star, kinds, sinb, cosb, sink,
                        oL, oR, coreL, coreR, zshelf, blend, z_raw_at, stats)


# -------------------------------------------------------------------------------------------
# the junction disc: the tarmac Renderer A lays across the node
# -------------------------------------------------------------------------------------------
def resample_loop(loop, step_m: float = 0.35):
    """A closed polygon (K, 3) resampled so no two consecutive points are further apart than
    ``step_m``.  Used only for the patch's apron, where "how far is this cell from the tarmac" has to
    be answered for a few hundred cells: nearest RESAMPLED VERTEX is then within ``step_m / 2`` of
    nearest point-on-edge, which is two orders of magnitude finer than the apron it decides."""
    P = np.asarray(loop, dtype=np.float64)
    if len(P) < 2:
        return P
    Q = np.vstack([P, P[:1]])
    seg = np.hypot(np.diff(Q[:, 0]), np.diff(Q[:, 1]))
    n = np.maximum(1, np.ceil(seg / max(step_m, 1e-3)).astype(np.int64))
    idx = np.repeat(np.arange(len(P)), n)
    off = np.arange(int(n.sum())) - np.repeat(np.cumsum(n) - n, n)
    t = (off / np.repeat(n, n).astype(np.float64))[:, None]
    return Q[idx] * (1.0 - t) + Q[idx + 1] * t


def junction_sag(loop, apex, X, Y, base, delta_m: float = 0.5, factor: float = 1.5):
    """The same second-difference correction ``sag_correction`` applies to a ribbon, applied to the
    patch fan: the landscape draws a straight line between two burned posts, and where the fan is
    convex across a triangle edge that line lies ABOVE the surface it was burned from.  Zero on a
    plane at any grade, which is why it is a correction and not a minimum over a stencil."""
    from .road import junction_target_z
    v = np.zeros(X.shape, dtype=np.float64)
    for dx, dy in ((delta_m, 0.0), (0.0, delta_m)):
        a = junction_target_z(loop, apex, X + dx, Y + dy)
        b = junction_target_z(loop, apex, X - dx, Y - dy)
        m = np.isfinite(a) & np.isfinite(b) & np.isfinite(base)
        if m.any():
            v[m] += np.maximum(0.0, 0.5 * (a[m] + b[m]) - base[m])
    return v * factor


def junction_targets(plan, junction_id: str, splines, params: CorridorParams, max_span_m: float = 200.0):
    """``(cx, cy, z, rank, u)`` for one junction patch, or ``None`` when the patch does not build.

    Cell centres are integer local metres, exactly as ``spline_targets`` yields them, so the driver
    turns both into mosaic row/col the same way.  The target is ``road.junction_target_z`` -- the
    barycentric evaluation of the very fan ``build_junction_patch`` emits -- less the sag correction
    and less the sink.

    THE SINK IS THE SHALLOWEST OF THE ARMS'.  ``sink_profile`` already takes the minimum over a
    spline's two sides, on the rule that the burn may only sink the ground as far as the built block
    covers.  A patch is covered by whatever its arms carry round the corner, so the same minimum is
    taken over the arms at their trim stations: a crossroads of kerbed roads sinks the full
    ``sink_max_m``, and one footway in the junction pulls the whole disc back to the floor.  That
    keeps the disc and its arms from stepping and keeps the float measurement where it was.

    The patch is stamped as RANK_SURFACE, including an apron of ``apron_m`` outside its boundary, for
    the same reason the ribbon's is: the landscape interpolates linearly to the next post, so a cell
    just outside the tarmac is read by the triangle that draws the tarmac's edge.  Arbitration is
    still the minimum, so where an arm's own corridor asked for something lower, the lower answer
    wins and neither surface is penetrated.

    ``max_span_m`` refuses a patch whose plan bounding box is absurd (a trim radius that ran away
    would otherwise rasterise a square kilometre); it is a guard, not a modelling choice, and the
    largest real Thanet junction spans about 45 m."""
    from .road import junction_surface, junction_target_z
    from .spline import resolve_arm_frames
    res = junction_surface(plan, junction_id, splines)
    if res is None:
        return None
    loop, apex = res
    frames = resolve_arm_frames(plan, junction_id, splines)
    if not frames:
        return None
    sink = min(float(sink_profile(af.spline, params)[af.i]) for af in frames)
    apron = float(params.apron_m)
    lx, ly = loop[:, 0], loop[:, 1]
    if not (np.isfinite(lx).all() and np.isfinite(ly).all() and np.isfinite(apex).all()):
        return None
    x0 = int(np.floor(lx.min() - apron - 1.0))
    x1 = int(np.ceil(lx.max() + apron + 1.0))
    y0 = int(np.floor(ly.min() - apron - 1.0))
    y1 = int(np.ceil(ly.max() + apron + 1.0))
    if (x1 - x0) > max_span_m or (y1 - y0) > max_span_m:
        return None
    W = x1 - x0 + 1
    H = y1 - y0 + 1
    X, Y = np.meshgrid(np.arange(x0, x1 + 1, dtype=np.float64),
                       np.arange(y0, y1 + 1, dtype=np.float64))
    X = X.ravel()
    Y = Y.ravel()
    acc = np.full(X.shape, np.inf, dtype=np.float64)

    # (a) the surface at the cell centre, less its own sag correction
    z = junction_target_z(loop, apex, X, Y)
    inside = np.isfinite(z)
    if inside.any():
        z[inside] = z[inside] - junction_sag(loop, apex, X[inside], Y[inside], z[inside],
                                             0.5, params.sag_factor)
        acc[inside] = z[inside]

    # (b) the fan's own EDGES, densely, each point claiming all four cells of the unit square it
    # falls in.  A cell centre tells you nothing about a crease that runs between two cells, and the
    # patch fan is full of creases: it is a cone from the node apex down to each arm's end row, so
    # every apex-to-boundary spoke is one.  Where the crease is a valley the landscape's straight
    # line between two posts lies ABOVE it, which is fusion again -- measured at 1.601 m on
    # junction:21_3:4 (a 4-arm junction whose arms span 14.1-20.8 m) before these pins were added.
    # Pinning every point of every edge to all four of its neighbouring posts bounds each post by the
    # lowest bit of surface within a metre of it, so no post can sit above a crease it touches.
    pin = [resample_loop(loop, 0.35)]
    sp_t = np.arange(0.0, 1.0, 0.35 / max(float(np.max(np.hypot(loop[:, 0] - apex[0],
                                                                loop[:, 1] - apex[1]))), 1e-6))
    if sp_t.size:
        A = np.asarray(apex, dtype=np.float64)[None, None, :]
        pin.append((A + (loop[:, None, :] - A) * sp_t[None, :, None]).reshape(-1, 3))
    P = np.vstack(pin)
    fx = np.floor(P[:, 0]).astype(np.int64)
    fy = np.floor(P[:, 1]).astype(np.int64)
    pcx = np.concatenate([fx, fx + 1, fx, fx + 1]) - x0
    pcy = np.concatenate([fy, fy, fy + 1, fy + 1]) - y0
    pz = np.tile(P[:, 2], 4)
    ok = (pcx >= 0) & (pcx < W) & (pcy >= 0) & (pcy < H) & np.isfinite(pz)
    if ok.any():
        np.minimum.at(acc, (pcy[ok] - 0) * W + pcx[ok], pz[ok])

    # (c) the apron: cells the tarmac does not cover but whose post is read by the triangle that
    # draws its edge.  Held at the nearest boundary point's height, as the ribbon's apron is.
    out_idx = np.where(~np.isfinite(acc))[0]
    if out_idx.size:
        D = pin[0]
        dx = X[out_idx][:, None] - D[None, :, 0]
        dy = Y[out_idx][:, None] - D[None, :, 1]
        d2 = dx * dx + dy * dy
        j = np.argmin(d2, axis=1)
        near = d2[np.arange(len(j)), j] <= apron * apron
        if near.any():
            acc[out_idx[near]] = D[j[near], 2]

    keep = np.isfinite(acc)
    if not keep.any():
        return None
    n = int(keep.sum())
    return (X[keep], Y[keep], acc[keep] - sink,
            np.full(n, RANK_SURFACE, dtype=np.int32), np.zeros(n))


def built_surface(sp, s_star, d, kinds, sinb, cosb, oL, oR):
    """The height of the BUILT surface at (arc position, signed lateral offset), laterally clamped to
    the kerb line so that beyond the carriageway it returns the road-edge level -- the shelf the kerb,
    pavement and verge are held at.  One function, so the burn, the sag correction and the shelf all
    speak about the same surface."""
    s_star = np.clip(s_star, 0.0, sp.length)
    z_ref = np.interp(s_star, sp.s, sp.z_ref)
    sb = np.interp(s_star, sp.s, sinb)
    cb = np.interp(s_star, sp.s, cosb)
    o_l = np.interp(s_star, sp.s, oL)
    o_r = np.interp(s_star, sp.s, oR)
    dc = np.clip(d, -o_r, o_l)
    k = np.clip(np.searchsorted(sp.s, s_star, side="right") - 1, 0, sp.n - 1)
    w = np.interp(s_star, sp.s, sp.width)
    cf = np.interp(s_star, sp.s, sp.crossfall_pct)
    cm = np.interp(s_star, sp.s, sp.camber_m)
    return z_ref + dc * sb + camber_h(kinds[k], w, cf, cm, dc) * cb


def sag_correction(sp, s_star, d, kinds, sinb, cosb, oL, oR, base, delta, factor=1.0):
    """How far the LANDSCAPE can rise above the road between two cells, and therefore how much
    further the burn has to sink.

    The landscape interpolates linearly between its 1 m posts; the road surface does not have to be
    linear between them.  Where the surface is convex -- the sag of a vertical curve, the kink where
    a steep OSM way leaves its junction, the corner where the cambered carriageway meets the flat
    kerb shelf -- the straight line between two burned posts lies ABOVE the surface it was burned
    from, and the road fuses again by exactly that much.  Measured on the A-road at Manston
    (roads:32352025:0 station 0, a 145 % grade off the junction) it was 0.264 m, the single worst
    residual of the first full run.

    The excess is the second difference, so subtract it: one term along the road, one across it, each
    clamped at zero because a crest (concave) interpolates BELOW the surface and needs nothing.  It is
    measured at several half-spans up to ``delta`` and the largest kept, because a kink shorter than
    the span reads as almost straight at that span: on the cliff footway roads:1387728616:0, whose
    z_ref climbs 9.3 -> 19.6 m in 2.5 m, the 1.5 m span alone left 0.472 m standing.  A straight grade,
    however steep, has a second difference of zero at every span and is not touched -- which is why
    this is the correction and a plain minimum over a stencil is not (that would sink a 10 % grade by
    a tenth of the span and make the road float)."""
    out = None
    for f in (1.0, 2.0 / 3.0, 1.0 / 3.0):
        h = delta * f
        a = built_surface(sp, s_star + h, d, kinds, sinb, cosb, oL, oR)
        b = built_surface(sp, s_star - h, d, kinds, sinb, cosb, oL, oR)
        c = built_surface(sp, s_star, d + h, kinds, sinb, cosb, oL, oR)
        e = built_surface(sp, s_star, d - h, kinds, sinb, cosb, oL, oR)
        v = np.maximum(0.0, 0.5 * (a + b) - base) + np.maximum(0.0, 0.5 * (c + e) - base)
        out = v if out is None else np.maximum(out, v)
    return out * factor


def _evaluate(sp, params, cx, cy, lat, s_star, kinds, sinb, cosb, sink,
              oL, oR, coreL, coreR, zshelf, blend, z_raw_at, stats=None):
    s_star = np.clip(s_star, 0.0, sp.length)
    cb = np.interp(s_star, sp.s, cosb)
    left = lat >= 0.0
    o = np.where(left, np.interp(s_star, sp.s, oL), np.interp(s_star, sp.s, oR))
    core = np.where(left, np.interp(s_star, sp.s, coreL), np.interp(s_star, sp.s, coreR))
    bl = np.where(left, np.interp(s_star, sp.s, blend[S.LEFT]), np.interp(s_star, sp.s, blend[S.RIGHT]))
    d = lat / np.where(np.abs(cb) > 1e-6, cb, 1.0)
    ad = np.abs(d)
    # PER SIDE and per lateral offset, not one depth for the cross-section: sink_field.
    sk = sink_field(params, d,
                    np.interp(s_star, sp.s, sink[S.LEFT]), np.interp(s_star, sp.s, sink[S.RIGHT]),
                    np.interp(s_star, sp.s, coreL), np.interp(s_star, sp.s, coreR))

    reach = core + params.verge_m + bl
    inside = ad <= core + params.verge_m
    rank = np.full(cx.shape, RANK_NONE, dtype=np.int32)
    z = np.full(cx.shape, np.nan)
    u = np.zeros(cx.shape)

    if inside.any():
        si, di = s_star[inside], d[inside]
        base = built_surface(sp, si, di, kinds, sinb, cosb, oL, oR)
        sag = sag_correction(sp, si, di, kinds, sinb, cosb, oL, oR, base, params.sag_delta_m,
                             params.sag_factor)
        zi = base - sk[inside] - sag
        idx = np.where(inside)[0]
        # the apron: cells outside the built surface but close enough that the landscape's linear
        # interpolation at the pavement's outer edge reads them.  They arbitrate as built surface, so a
        # neighbouring way cannot raise them and push its ground up through this way's pavement --
        # measured at 0.121 m on the A299 slip road before this was added.
        rank[idx] = np.where(ad[inside] <= core[inside] + params.apron_m, RANK_SURFACE, RANK_VERGE)
        z[idx] = zi

    m_blend = (~inside) & (ad <= reach)
    if m_blend.any():
        sb_ = s_star[m_blend]
        db = d[m_blend]
        side_o = np.where(db >= 0, 1.0, -1.0) * (core[m_blend] + params.verge_m)
        shelf = built_surface(sp, sb_, side_o, kinds, sinb, cosb, oL, oR)
        # the blend starts from the level the VERGE EDGE holds, so the sink is read at the verge
        # edge, not at the blend cell's own offset: otherwise the two zones step where they meet.
        sk_shelf = sink_field(params, side_o,
                              np.interp(sb_, sp.s, sink[S.LEFT]), np.interp(sb_, sp.s, sink[S.RIGHT]),
                              np.interp(sb_, sp.s, coreL), np.interp(sb_, sp.s, coreR))
        shelf = shelf - sk_shelf - sag_correction(sp, sb_, side_o, kinds, sinb, cosb, oL, oR,
                                                  shelf, params.sag_delta_m, params.sag_factor)
        t = (ad[m_blend] - (core[m_blend] + params.verge_m)) / np.maximum(bl[m_blend], 1e-6)
        zr = z_raw_at(cx[m_blend], cy[m_blend])
        wgt = smoothstep(t)
        zb = (1.0 - wgt) * shelf + wgt * zr
        good = np.isfinite(zb)
        sel = np.where(m_blend)[0][good]
        rank[sel] = RANK_BLEND
        z[sel] = zb[good]
        u[sel] = t[good]

    # Outside the built surface and its apron the ground may move by at most `clamp_m`.  Without it a
    # cliff-top way whose verge edge hangs 17 m over the beach builds a 17 m earth shelf out of the
    # chalk face, and a promenade under a cliff cuts a 14 m notch into it -- measured on
    # roads:28875046:0 (+17.472 m) and roads:179363634:0 (-14.624 m).  The BUILT surface is never
    # clamped: it is what the acceptance gate is about, and clamping it would be the fusion again.
    # The step left at the apron edge is a real retaining wall or embankment, and its run is written
    # to conform_clamped.json for Renderer B (BRIEF 1.1's own answer to this case).
    m_out = (rank == RANK_VERGE) | (rank == RANK_BLEND)
    if params.clamp_m > 0 and m_out.any():
        zr = z_raw_at(cx[m_out], cy[m_out])
        zc = np.clip(z[m_out], zr - params.clamp_m, zr + params.clamp_m)
        good = np.isfinite(zr)
        hit = good & (np.abs(zc - z[m_out]) > 1e-9)
        z[np.where(m_out)[0][good]] = zc[good]
        if stats is not None:
            stats["cells_clamped"] = stats.get("cells_clamped", 0) + int(hit.sum())

    keep = (rank != RANK_NONE) & np.isfinite(z)
    return cx[keep], cy[keep], z[keep], rank[keep], u[keep]
