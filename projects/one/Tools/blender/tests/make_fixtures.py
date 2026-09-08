"""Write tests/fixtures/{straight_100,sine_5_50,curve_R20_200,rail_R300_600}.json and expected.json.

expected.json holds every number of SCHEMA.md 9.3 and DESIGN.md 3.7-3.8 plus the values re-frozen by the
implementation where the design prototype's numbers could not survive the normative rules:

  * station counts of sine_5_50 / curve_R20_200 / rail_R300_600 include the WAYPOINT-mandatory stations of
    SCHEMA.md 3.2 (the design prototype counted adaptive stations only: 101 / 117); spacing statistics are
    measured on adaptive-to-adaptive gaps, where the design's crest / inflection / arc numbers hold;
  * the smoothing factors are for the ARC-LENGTH (trapezoidal) moving average (spline.py), which
    reproduces the B6 dtm_ma15 table of the test stretch to 1 mm where uniform station weights missed
    s = 100 by 2.5 cm; the thresholds (>= 2.5 / 1.7 / 3.0, ripple <= 0.010) are unchanged.

Both test suites (numpy here, C++ Automation) read this one file.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import synthetic as syn  # noqa: E402

FIXTURES = syn.FIXTURES_DIR


def dump(obj, path):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1, allow_nan=False)
        fh.write("\n")


EXPECTED = {
    "_about": "Frozen expectations for the Streetscape geometry core (SCHEMA.md 9.3, DESIGN.md 3.7-3.8) and the "
              "values re-frozen by Tools/blender/streetscape (see make_fixtures.py docstring). Read by "
              "Tools/blender/tests/test_*.py and Plugins/Streetscape Automation tests.",
    "noise": {
        "lowbias32": {"0": "0x0", "1": "0x688990c0", "2": "0xd1132181", "0xdeadbeef": "0xe628c683"},
        "unit_noise_0_4_seed7": [-0.33847302, 0.94551079, -0.62749659, 0.96820159, 0.64059920],
        "tol": 1e-8,
        "fbm3_range": [-1.0, 1.0],
        "value_noise3_continuity_1mm_max": 0.01,
    },
    "straight_100": {
        "fixture": "straight_100.json",
        "L": 100.0,
        "N": 54, "n_adaptive": 51, "off_grid_stations": [69.085, 71.83, 72.745],
        "N_without_drop_kerb": 51,
        "gap_min": 0.17, "gap_max": 2.0, "adaptive_gap": 2.0,
        "w": {"40": 6.0, "45": 7.0, "50": 8.0}, "w_max": 8.0, "w_tol": 1e-9,
        "width_override": {"segment": {"s0_m": 60.0, "s1_m": 80.0, "width_m": 5.0, "ramp_m": 5.0},
                           "w": {"55": 8.0, "57.5": 6.5, "60": 5.0, "70": 5.0, "80": 5.0, "85": 8.0}},
        "n_int": 9, "ribbon_rows": 11, "ribbon_verts": 594, "ribbon_tris": 1060,
        "overlap_m": 0.04, "skirt_drop_m": 0.02, "tuck_depth_m": 0.03, "tuck_in_m": 0.02,
        "coincident_per_station": 2, "coincident_total_per_side": 108, "coincident_strict_band": 0,
        "kerb": {"row_B_h": -0.03, "row_A_o": -0.02, "flush_tol": 1e-12, "height_coherence_tol": 1e-9},
        "drop_kerb": {"flat_centre_s": 70.915, "hk_flat": 0.006, "ramp_mid_down_s": 69.5425, "ramp_mid_up_s": 72.2875,
                      "hk_ramp_mid": 0.0655, "hk_back_flat": 0.150, "hk_back_nominal": 0.170, "tol": 1e-6},
        "centre_dashes": {"count": 17, "first": [0.0, 4.0], "last": [96.0, 100.0], "vd": [-0.05, 0.05], "tol": 1e-9},
        "double_yellow": {"pair_centre_inward": 0.25, "line_centres_inward": [0.35, 0.15], "line_width": 0.1,
                          "shift_40_to_45": 0.5, "shift_per_station": {"44": 0.4, "46": 0.6, "48": 0.8, "50": 1.0}},
        "lift_m": 0.004, "lift_tol": 1e-9,
        "marking_strips": 19,
        "camber": {"h0": 0.0, "h_pm3_parabolic": -0.0375, "h_pm3_planar": -0.075},
        "posts": {"chain_link_45_100_pitch3": 19, "railing_20_60_pitch2": 21, "chain_link_45_95_pitch3": 18, "railing_95_140_pitch2": 23},
        "railing_rails": 3,
    },
    "smoothing": {
        "_note": "2 % grade + 0.1*sqrt(3)*unit_noise(i, 7) on 51 stations at 2 m; interior s in [10, 90]; arc-length MA",
        "W20": {"factor_min": 2.5, "factor_measured": 2.748, "max_err_max": 0.08, "max_err_measured": 0.0626,
                "grade": 0.0196, "grade_tol": 0.002},
        "W10": {"factor_min": 1.7, "factor_measured": 2.039},
        "W20_2pass": {"factor_min": 3.0, "factor_measured": 3.175},
        "ripple_8m": {"rms_raw": 0.0700, "rms_raw_tol": 0.0005, "rms_max": 0.010, "rms_measured": 0.0072},
        "design_prototype_uniform_weights": {"W20": 2.837, "W10": 1.942, "W20_2pass": 3.308, "ripple": 0.0065},
    },
    "bank": {"raw_deg": 5.71, "raw_tol": 0.02, "clamped_deg": 4.0, "roll_all_deg": 2.0,
             "rate_limit_deg_per_m": 0.25, "frames_tol": 1e-12},
    "sine_5_50": {
        "fixture": "sine_5_50.json",
        "L": 109.2, "L_tol": 0.1,
        "N": 119, "N_tol": 3, "N_design_prototype_adaptive_only": 101,
        "crest_spacing_max": 0.85, "inflection_spacing_min": 1.5, "ratio_min": 1.8,
        "measured": {"crest_mean": 0.8395, "inflection_mean": 1.535, "ratio": 1.829},
        "_measure": "adaptive-to-adaptive gaps; crest = |x mod 25 - 12.5| < 3, inflection = min(x mod 25, 25 - x mod 25) < 3",
    },
    "curve_R20_200": {
        "fixture": "curve_R20_200.json",
        "L": 200.0, "L_tol": 0.05,
        "N": 125, "N_tol": 2, "N_design_prototype_adaptive_only": 117,
        "arc_spacing": 1.00, "arc_tol": 0.03, "straight_spacing": 1.99, "straight_tol": 0.02,
        "ratio": 2.0, "ratio_tol": 0.1,
        "measured": {"arc_mean": 0.983, "straight_in": 1.980, "straight_out": 1.976, "ratio": 2.014},
        "_measure": "adaptive-to-adaptive gaps; arc = gap midpoint s in (62, 89); straights s < 58 and s > 94",
    },
    "rail_R300_600": {
        "fixture": "rail_R300_600.json",
        "L": 600.0, "L_tol": 0.05,
        "N": 653, "N_tol": 3,
        "sampling": {"step_m": 1.0, "min_step_m": 0.25, "curvature_gain": 60.0, "smoothing_window_m": 40.0,
                     "smoothing_passes": 2, "bank_max_deg": 6.0},
        "gauge_inner_faces": 1.435, "gauge_tol": 0.001,
        "rail_centres": 1.50485, "rail_centres_tol": 0.001,
        "rail_top_above_ballast": 0.21375, "rail_top_tol": 1e-6,
        "sleeper_pitch": 0.65, "sleeper_pitch_tol": 1e-6, "sleepers_rule": "floor(L/0.65)+1", "sleepers": 924,
        "ballast_toe_width": 4.75, "ballast_top_width": 3.4,
        "straight_spacing": 1.00, "straight_tol": 0.02, "bend_spacing": 0.83, "bend_tol": 0.03,
        "measured": {"straight": 0.998, "bend": 0.8334},
        "z_raw_nan_count": 0,
    },
    "hedge": {"offset_m": 0.1, "noise_amplitude_m": 0.06, "noise_tol": 1e-9, "card_density_per_m2": 12, "card_tol_frac": 0.05,
              "card_surface": "triangles whose mean section height is above 0.05 m (the base band and the bottom face carry no cards)",
              "offset_rule": "inner face = barrier outer face + offset_m where a barrier is in force, else pavement back edge + offset_m",
              "offset_tol": 1e-9},
    "test_stretch": {
        "file": "schema/examples/test_stretch.json",
        "terrain": "data/thanet/out/unreal/landscape, or data/margate/out/terrain tiles (5,5)+-1 shifted +5120 (Margate origin 632800/168200 -> Thanet 627680/163080)",
        "L": 171.40, "L_tol": 0.05,
        "n_samples": 116,
        "z_ref": {"10": 20.47, "100": 19.35, "160": 18.24}, "z_ref_tol": 0.02,
        "z_ref_measured": {"10": 20.4688, "100": 19.3492, "160": 18.2393},
        "z_raw_nan_count": 0, "step_min_floor": 0.125, "step_max": 2.0, "bank_abs_max": 4.0,
        "overlap": 0.04, "w_max": 7.0,
        "instances": {"post_round": 18, "post_square": 23, "leaf_card": 1650},
        "marking_strips": 31, "marking_strips_rule": "29 centre dashes (4 m / 2 m over 171.4 m, last one clipped) + 2 double-yellow lines",
        "buffers": {"road": [1794, 2756], "edge_left": [1508, 2318], "edge_right": [2696, 3448], "hedge_right": [364, 724]},
        "hedge_s_range": [55.0, 90.0],
        "hedge_inner_face_on_6m_section": 5.075,
        "overlay_points": 91, "overlay_lift_m": 0.3,
    },
}


def main():
    os.makedirs(FIXTURES, exist_ok=True)
    for name, builder in syn.FIXTURE_BUILDERS.items():
        dump(builder(), os.path.join(FIXTURES, name + ".json"))
    dump(EXPECTED, os.path.join(FIXTURES, "expected.json"))
    print("wrote %s: %s expected.json" % (FIXTURES, " ".join(n + ".json" for n in syn.FIXTURE_BUILDERS)))


if __name__ == "__main__":
    main()
