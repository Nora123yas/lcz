"""urbanmorphology – Configuration File
========================================

HOW TO USE
----------
This file is the single place you need to edit before running the pipeline.
It is organised into four sections:

  ① REQUIRED  – You MUST fill these in before running anything.
  ② PIPELINE  – Turn individual processing steps on / off.
  ③ SCENARIO  – Choose a classification scenario and set its parameters.
  ④ ADVANCED  – Defaults that rarely need changing (edit only if needed).

Quick-start checklist
---------------------
  1. Fill in all fields marked  ← REQUIRED
  2. Set ACTIVE_SCENARIO to 1, 2, or 3
  3. Fill in the corresponding Scenario block
  4. Toggle the STEPS you want to run to True
  5. Run:  urbanlst --city_ids <your_city_id>
"""

import ee
import os


# ============================================================
# ①  REQUIRED  –  fill these in before running
# ============================================================

# Google Earth Engine project ID
GEE_PROJECT = "chinalcz"

# City IDs to process (integers matching the GUB feature collection)
# Example: [36081] or [36081, 36082, 36083]
CITY_IDS = [36081]

# Year range to process (inclusive)
START_YEAR = 2003
END_YEAR   = 2020

# GEE asset folder paths  (trailing slash required)
# These folders must already exist in your GEE asset manager.
GEE_ASSETS = {
    # Raw per-year LCZ classification results
    "LCZ_CLASSIFICATION": "projects/chinalcz/assets/worldlcz_classification/",
    # Temporally corrected results
    "LCZ_CORRECTED":      "projects/chinalcz/assets/worldlcz_corrected/",
    # Year-of-disturbance (change detection output)
    "LCZ_YOD":            "projects/chinalcz/assets/worldlcz_yod/",
    # Final integrated results (after YOD fusion)
    "LCZ_FINAL":          "projects/chinalcz/assets/worldlcz_final/",
    # Temporally smoothed intermediate results
    "LCZ_TEMP_SMOOTH":    "projects/chinalcz/assets/worldlcz_TempFilter/",
    # Global Urban Boundary feature collection
    "GUB":                "projects/globallcz/assets/gub/gub2018",
}

# Landsat composite asset paths (searched in order; first match is used)
LANDSAT_BASES = [
    "projects/chinalcz/assets/worldlcz",
    "projects/ee-yogurt/assets/worldlcz",
]

# Custom Landsat asset path template (optional).
# If set, this template takes priority over LANDSAT_BASES.
# Use {year} and {city_id} as placeholders.
#
# Example (your exported format):
#LANDSAT_ASSET_TEMPLATE = "projects/dalianlcz/assets/landsat/landsat_{year}_3years"
#
# Example (with city_id in path):
#   LANDSAT_ASSET_TEMPLATE = "projects/myproject/assets/landsat/{city_id}/landsat_{year}_3yr"
#
# Leave as None to use the default LANDSAT_BASES search logic.
LANDSAT_ASSET_TEMPLATE = "projects/dalianlcz/assets/landsat/landsat_{year}_3years"

# Destination folder when *exporting* new Landsat composites (Step 1)
LANDSAT_EXPORT_BASE = "projects/chinalcz/assets/worldlcz"


# ============================================================
# ②  PIPELINE  –  toggle processing steps on / off
# ============================================================
# Set a step to True to run it, False to skip it.
# Steps run in order: 1 → 2 → 3 → 4 → 5 → 6.

STEPS = {
    # Step 1 – Export Landsat 3-year median composites to GEE assets.
    #           Skip if composites already exist.
    "STEP1_LANDSAT_EXPORT":    False,

    # Step 2 – LandTrendr texture change detection → Year-of-Disturbance (YOD) asset.
    #           Skip if YOD asset already exists.
    "STEP2_CHANGE_DETECTION":  True,

    # Step 3 – Per-year LCZ classification using the scenario chosen below.
    "STEP3_CLASSIFICATION":    True,

    # Step 4 – Temporal consistency correction and YOD-guided integration.
    "STEP4_AGGREGATION":       False,

    #   Sub-options for Step 4 (only used when STEP4_AGGREGATION is True):
    #   Apply a temporal mode filter before consistency correction.
    "STEP4_TEMPORAL_SMOOTHING": False,
    #   Replace non-urban pixels with FROM-GLC Plus land-cover classes.
    "STEP4_LANDCOVER_FUSION":   False,

    # Step 5 – Generate LCZ change visualisations (requires local raster files).
    "STEP5_VISUALISATION":     False,

    # Step 6 – Validate classification accuracy against a reference dataset.
    "STEP6_VALIDATION":        False,
}

# Keep the old key name as an alias so existing code does not break
STEP_FLAGS = STEPS


# ============================================================
# ③  SCENARIO  –  choose a classification scenario
# ============================================================
# Set ACTIVE_SCENARIO to 1, 2, or 3, then fill in the
# corresponding block below.  Leave the other blocks as-is.
#
#   Scenario 1 – Yearly sample assets
#       Best when you have a dedicated labelled sample for every year.
#
#   Scenario 2 – Single-year sample + YOD-guided fusion
#       Best when you have one reliable labelled sample (e.g. for 2020)
#       and want to reuse it across all years.
#
#   Scenario 3 – No external samples (confidence-mask based)
#       Best when you have no labelled samples at all.  Uses the 2020
#       LCZ product as pseudo-labels and builds a confidence mask from
#       three independent Random Forest runs.

ACTIVE_SCENARIO = None   # ← set to 1, 2, or 3


# ------ Scenario 1 settings ------
# Path template for per-year training sample assets.
# Use {year} as the placeholder.
# Example: "users/yourname/Samples/training_{year}"
SCENARIO1_SAMPLE_TEMPLATE = "projects/dalianlcz/assets/Samples/training_{year}"   # ← REQUIRED for Scenario 1


# ------ Scenario 2 settings ------
# A single training sample asset reused across all years.
# Example: "users/yourname/Samples/training_2020"
SCENARIO2_SAMPLE_ASSET = "projects/dalianlcz/assets/Samples/training_2020"      # ← REQUIRED for Scenario 2

# Year-of-disturbance asset override.
# Leave as None to use the auto-generated YOD from Step 2.
SCENARIO2_YOD_ASSET = "projects/dalianlcz/assets/yod/yoddissdalian"

# Number of ghost sample points drawn from FROM-GLC Plus in changed areas.
SCENARIO2_GHOST_POINTS = 500


# ------ Scenario 3 settings ------

# Pseudo-label source for Scenario 3.
# Set to "image" to use a single custom GEE Image asset (see SCENARIO3_MAP_2020_ASSET below).
# Set to "global_lcz" to use the GEE official global LCZ ImageCollection
#   (ee.ImageCollection("RUB/RUBCLIM/LCZ/global_lcz_map/latest")).
#   No extra asset path is needed; the collection is filtered by city boundary automatically.
SCENARIO3_PSEUDO_LABEL_SOURCE = "image"   # "image" | "global_lcz"

# [Used when SCENARIO3_PSEUDO_LABEL_SOURCE = "image"]
# Your own 2020 LCZ product used as pseudo-labels (must contain a "remapped" band).
# Example: "projects/yourproject/assets/result2020"
SCENARIO3_MAP_2020_ASSET  = "projects/jjjdata/assets/aggregatedmaps_v2/result2020"

# [Used when SCENARIO3_PSEUDO_LABEL_SOURCE = "global_lcz"]
# GEE collection ID for the official global LCZ map.
# The default value below is the public collection; change only if you have a private copy.
SCENARIO3_GLOBAL_LCZ_COLLECTION = "RUB/RUBCLIM/LCZ/global_lcz_map/latest"
# Which band to use from the global LCZ collection: "LCZ_Filter" or "LCZ_Majority".
SCENARIO3_GLOBAL_LCZ_BAND       = "LCZ_Filter"

# Output path for the generated confidence mask.
# Example: "projects/yourproject/assets/NoSample/confi_mask_36081"
SCENARIO3_CONFI_MASK_OUT  = None   # ← REQUIRED for Scenario 3


# ============================================================
# ④  ADVANCED  –  defaults that rarely need changing
# ============================================================

# ----- Spatial resolution -----
# Output pixel size in metres for classification and export.
SCALE = 100

# ----- Random Forest -----
# Number of trees in the Random Forest classifier.
CLASSIFIER_TREES = 150

# Number of training samples per LCZ class (Scenarios 1 & 2).
SAMPLES_PER_CLASS = 200

# ----- Scenario 3 confidence-mask tuning -----
# Samples per class for each RF round when building the confidence mask.
SCENARIO3_CF_N_PER_CLASS = 100
# Number of independent RF rounds (more rounds → stricter mask).
SCENARIO3_CF_ROUNDS      = 3
# Trees per round.
SCENARIO3_CF_RF_TREES    = 100
# Fixed random seeds for reproducibility (one per round).
SCENARIO3_CF_SEEDS       = [1001, 1002, 1003]
# Samples per class for the final per-year classification in Scenario 3.
SCENARIO3_SAMPLES_PER_CLASS = 300
# tileScale passed to GEE sampling calls.
# Increase this value if you hit "User memory limit exceeded" errors.
# Recommended: 8 for small cities, 16 for large cities (e.g. city_id=1010),
# 32 for very large regions. Higher values reduce memory use but increase runtime.
SCENARIO3_TILE_SCALE     = 16

# ----- GLC → LCZ class cross-walk (Scenarios 2 & 3) -----
# Maps FROM-GLC Plus land-cover codes to LCZ classes.
# Keys = GLC codes, Values = LCZ classes.
GLC_TO_LCZ_MAP = {1: 14, 2: 11, 3: 14, 4: 13, 5: 17, 6: 17, 9: 15}

# FROM-GLC Plus asset path template (used by Scenarios 2 & 3).
FROM_GLC_PLUS_ASSET_TEMPLATE = "projects/globallcz/assets/fromglc_plus/plus_{year}"

# ----- Texture change detection (Step 2) -----
INPUT_TYPE               = "SWIR1"
GLCM_SIZE                = 3
TEXTURE_METHOD           = "glcm_diss"   # "glcm_diss" | "stddev"
TEXTURE_STABLE_THRESHOLD = 1.0
TEXTURE_MMU              = 5
TEXTURE_MAG_THRESHOLD    = 0.5
TEXTURE_PREVAL_THRESHOLD = -9999
BUILTUP_LANDCOVER_ASSET  = "projects/globallcz/assets/fromglc_plus/plus_2000"

# ----- Google Satellite Embedding collection -----
# Used as features for years > 2016.
ALPHA_EARTH_COLLECTION = "GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL"

# ----- FROM-GLC Plus EE module (fallback when asset root is not set) -----
FROM_GLC_PLUS_MODULE_ID  = "users/leyu/codes:get_FROM_GLC_PLus_LandCover_Map"
FROM_GLC_PLUS_ASSET_ROOT = "projects/globallcz/assets/fromglc_plus"

# ----- Accuracy validation (Step 6) -----
VALIDATION_FC    = "projects/example/assets/validation_samples"
VALIDATION_FIELD = "LCZ"

# ----- Local file paths (Step 5 visualisation) -----
# Root directory containing per-city raster folders on your local machine.
LOCAL_DATA_ROOT  = "/Users/yourname/Downloads/LST_LCZ"
CHANGE_CLASS_CSV = "/Users/yourname/Downloads/AllChanges_v2.csv"

# ----- LST detrending (pixel-level analysis) -----
DETREND_N = 5   # must satisfy: n >= 3 and 2n <= len(YEARS) - 5

# ----- Cities to skip during batch processing -----
SKIPPED_CITIES = []


# ============================================================
# Internal aliases  –  do not edit below this line
# ============================================================

YEARS = list(range(START_YEAR, END_YEAR + 1))

# Scenario config aliases used by time_series_scenarios.py
CLASSIFICATION_SCENARIO              = ACTIVE_SCENARIO
CLASS_SCENARIO1_SAMPLE_TEMPLATE      = SCENARIO1_SAMPLE_TEMPLATE
CLASS_SCENARIO2_SAMPLE_ASSET         = SCENARIO2_SAMPLE_ASSET
CLASS_SCENARIO2_YOD_ASSET            = SCENARIO2_YOD_ASSET
CLASS_SCENARIO2_LC_TEMPLATE          = FROM_GLC_PLUS_ASSET_TEMPLATE
CLASS_SCENARIO2_GHOST_POINTS         = SCENARIO2_GHOST_POINTS
CLASS_SCENARIO3_PSEUDO_LABEL_SOURCE  = SCENARIO3_PSEUDO_LABEL_SOURCE
CLASS_SCENARIO3_MAP_2020_ASSET       = SCENARIO3_MAP_2020_ASSET
CLASS_SCENARIO3_GLOBAL_LCZ_COLLECTION = SCENARIO3_GLOBAL_LCZ_COLLECTION
CLASS_SCENARIO3_GLOBAL_LCZ_BAND      = SCENARIO3_GLOBAL_LCZ_BAND
CLASS_SCENARIO3_CONFI_MASK_OUT       = SCENARIO3_CONFI_MASK_OUT
CLASS_SCENARIO3_LC_TEMPLATE          = FROM_GLC_PLUS_ASSET_TEMPLATE
CLASS_SCENARIO3_CF_N_PER_CLASS       = SCENARIO3_CF_N_PER_CLASS
CLASS_SCENARIO3_CF_ROUNDS            = SCENARIO3_CF_ROUNDS
CLASS_SCENARIO3_CF_RF_TREES          = SCENARIO3_CF_RF_TREES
CLASS_SCENARIO3_CF_SEEDS             = SCENARIO3_CF_SEEDS
CLASS_SCENARIO3_SAMPLES_PER_CLASS    = SCENARIO3_SAMPLES_PER_CLASS
CLASS_SCENARIO3_TILE_SCALE           = SCENARIO3_TILE_SCALE
CLASS_FIELD                          = "LCZ"
IDS                                  = CITY_IDS


def get_region_fc() -> ee.FeatureCollection:
    """Return the Global Urban Boundary feature collection."""
    return ee.FeatureCollection(GEE_ASSETS["GUB"])


def get_input_path(city_id: int) -> str:
    """Return the local input raster directory for *city_id*."""
    return os.path.join(LOCAL_DATA_ROOT, str(city_id))


def get_output_path(city_id: int) -> str:
    """Return the local output directory for *city_id*."""
    return os.path.join(LOCAL_DATA_ROOT, str(city_id), "output")
