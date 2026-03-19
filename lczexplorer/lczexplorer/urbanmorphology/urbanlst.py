#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Urban Morphology LCZ Mapping – CLI entry point.

This module wires together the utility packages under ``utils/`` to provide a
six-step processing pipeline:

1. Export Landsat 3-year median composites to GEE assets.
2. Run LandTrendr-based texture change detection to produce a YOD asset.
3. Classify LCZ for each year using one of three configurable scenarios.
4. Apply temporal consistency correction and optional land-cover fusion.
5. Generate LCZ change visualisations.
6. Validate classification accuracy against a reference dataset.

Steps are controlled by the boolean flags in ``utils/config.py::STEP_FLAGS``.
Run the tool from the command line::

    urbanlst --city_ids 36081 --sampling_method stable

or call ``main()`` directly from a notebook.
"""

import argparse
import os
from typing import List, Optional

import ee

from utils import config as Config
from utils.geemodules import (
    ChangeDetector,
    LandsatProcessor,
    LCZClassifier,
    LCZTimeSeriesScenarios,
    TemporalAggregator,
)
from utils.processors import AssetManager
from utils.TaskManager import TaskManager
from utils.accuracy import validate_series
from utils.time_series_scenarios import LCZTimeSeriesScenarios as _LCZScenarios

# ---------------------------------------------------------------------------
# Earth Engine initialisation
# ---------------------------------------------------------------------------

try:
    ee.Initialize(project="chinalcz")
except Exception:
    print("Earth Engine not initialised – attempting authentication …")
    ee.Authenticate(auth_mode="notebook")
    ee.Initialize(project="chinalcz")

region_fc = Config.get_region_fc()
years = Config.YEARS
step_flags = Config.STEP_FLAGS
change_class_csv = Config.CHANGE_CLASS_CSV

# ---------------------------------------------------------------------------
# Region / feature helpers
# ---------------------------------------------------------------------------


def _get_city_region(city_id: int) -> ee.Feature:
    return Config.get_region_fc().filter(ee.Filter.eq("id", int(city_id))).first()


# ---------------------------------------------------------------------------
# Scenario dispatch helpers
# ---------------------------------------------------------------------------


def _normalize_scenario_choice(choice: Optional[str]) -> int:
    """Normalise a user-supplied scenario identifier to an integer 1–3."""
    if choice is None:
        return 0
    mapping = {
        "1": 1, "scenario1": 1, "sc1": 1,
        "2": 2, "scenario2": 2, "sc2": 2,
        "3": 3, "scenario3": 3, "sc3": 3,
    }
    return mapping.get(str(choice).strip().lower(), 0)


def _prompt_classification_scenario() -> int:
    """Return the active scenario number, prompting the user when not preset."""
    preset = getattr(Config, "CLASSIFICATION_SCENARIO", None)
    scenario = _normalize_scenario_choice(preset)
    if scenario:
        return scenario

    print(
        "\n⚙️  STEP3_CLASSIFICATION is enabled.  Choose a classification scenario:\n"
        "  1) Yearly sample assets  – one dedicated sample asset per year\n"
        "  2) Single-year samples   – reuse a fixed-year sample + YOD-guided fusion\n"
        "  3) No external samples   – confidence-mask based (2020 pseudo-labels)\n"
    )
    try:
        user_input = input("Enter 1 / 2 / 3 (default 1): ").strip()
    except Exception:
        user_input = ""

    scenario = _normalize_scenario_choice(user_input or "1")
    if not scenario:
        raise ValueError("Invalid scenario choice – please enter 1, 2 or 3.")
    return scenario


def _run_classification_scenario(
    city_id: int,
    scenario_choice: int,
    bound: ee.FeatureCollection,
    class_field: str,
) -> None:
    """Build the per-year LCZ ImageCollection and submit export tasks."""

    runner = _LCZScenarios(
        years=Config.YEARS,
        samples_class_property=class_field,
    )

    if scenario_choice == 1:
        result_ic = runner.scenario_one(city_id)
        suffix = "_scenario1"
    elif scenario_choice == 2:
        result_ic = runner.scenario_two(city_id)
        suffix = "_scenario2"
    elif scenario_choice == 3:
        result_ic = runner.scenario_three(city_id)
        suffix = "_scenario3"
    else:
        raise ValueError(f"Unknown scenario: {scenario_choice}")

    _export_lcz_collection(result_ic, city_id, suffix, bound, scale=Config.SCALE)


def _export_lcz_collection(
    result_ic: ee.ImageCollection,
    city_id: int,
    suffix: str,
    region: ee.FeatureCollection,
    scale: int = 100,
) -> None:
    """Submit one EE export task per year in *result_ic*.

    We iterate over ``Config.YEARS`` (a plain Python list) rather than calling
    ``result_ic.aggregate_array('year').getInfo()``.  The latter forces GEE to
    evaluate the entire ImageCollection computation on the client before any
    export task is submitted, which exceeds the user memory limit for large
    cities.  Instead we filter the collection server-side for each year and
    skip years whose result image is empty (size == 0).
    """
    for year in Config.YEARS:
        asset_name = f"LCZ_{city_id}_{year}{suffix}"
        existing = AssetManager.find_asset(asset_name, "LCZ_CLASSIFICATION")
        if existing:
            print(f"✅ Already exists: {existing}")
            continue

        year_col = result_ic.filter(ee.Filter.eq("year", year))

        # Do NOT call size().getInfo() here.  result_ic is an ee.ImageCollection
        # whose images are the outputs of RF classifiers applied to large rasters.
        # Calling size().getInfo() forces GEE to evaluate ALL upstream pixel-level
        # computations (stratifiedSample + classify) before returning a single
        # integer, which exceeds the user memory limit for large cities.
        #
        # Instead, use ee.Algorithms.If server-side to select either the
        # classified image or a sentinel constant(0) image.  The Export task
        # is submitted unconditionally; GEE evaluates the computation lazily
        # on the server only when the task actually runs.
        sentinel = ee.Image.constant(0).rename(f"LCZ_{year}").toInt16()
        img = ee.Image(
            ee.Algorithms.If(
                year_col.size().gt(0),
                year_col.first().rename(f"LCZ_{year}"),
                sentinel,
            )
        )
        out_id = f"{Config.GEE_ASSETS['LCZ_CLASSIFICATION']}{asset_name}"
        task = ee.batch.Export.image.toAsset(
            image=img.toInt16(),
            description=asset_name,
            assetId=out_id,
            region=region.geometry(),
            scale=scale,
            maxPixels=1e13,
        )
        task.start()
        print(f"🚀 Export submitted: {out_id}")


# ---------------------------------------------------------------------------
# Main processing pipeline
# ---------------------------------------------------------------------------


def main(
    city_ids: List[int],
    sampling_method: str = "stable",
    asset_path: Optional[str] = None,
    asset_paths: Optional[List[str]] = None,
    class_property: str = "LCZ",
    val_ratio: Optional[float] = None,
) -> None:
    """Run the full pipeline for each city in *city_ids*.

    Parameters
    ----------
    city_ids:
        List of integer city identifiers matching the GUB feature collection.
    sampling_method:
        Sampling strategy used by ``LCZClassifier`` in steps outside the
        scenario-based classification (``"stable"``, ``"target"``, ``"cross"``,
        or ``"asset"``).
    asset_path:
        GEE asset path when ``sampling_method == "asset"``.
    asset_paths:
        Per-year asset paths when using the ``"asset"`` method with yearly
        samples.
    class_property:
        Property name in the training sample feature collection that holds the
        LCZ class label.
    val_ratio:
        When provided, this fraction of samples is held out for validation.
    """
    suffix = f"_{sampling_method}" if sampling_method and sampling_method != "stable" else ""

    for city_id in city_ids:
        print(f"\n=== Processing city ID: {city_id} ===")
        bound = region_fc.filter(ee.Filter.eq("id", city_id))

        # ------------------------------------------------------------------
        # Step 1: Export Landsat 3-year median composites
        # ------------------------------------------------------------------
        if step_flags.get("STEP1_LANDSAT_EXPORT", False):
            for year in years:
                asset_exists = False
                for base_path in Config.LANDSAT_BASES:
                    check_id = f"{base_path}/landsat_{year}_{city_id}_3yr"
                    try:
                        ee.data.getAssetAcl(check_id)
                        print(f"✅ Already exists: {check_id}")
                        asset_exists = True
                        break
                    except Exception:
                        continue

                if asset_exists:
                    continue

                export_id = f"{Config.LANDSAT_EXPORT_BASE}/landsat_{year}_{city_id}_3yr"
                try:
                    composite = LandsatProcessor.get_median_composite(year, bound)
                    task = ee.batch.Export.image.toAsset(
                        image=composite,
                        description=f"landsat_{year}_{city_id}_3yr",
                        assetId=export_id,
                        scale=30,
                        region=bound.geometry(),
                        maxPixels=1e13,
                    )
                    task.start()
                    print(f"🚀 Export submitted: {export_id}")
                except Exception as exc:
                    print(f"❌ Export failed for {export_id}: {exc}")

            TaskManager.wait_for_tasks()

        # ------------------------------------------------------------------
        # Step 2: Change detection (YOD)
        # ------------------------------------------------------------------
        if step_flags.get("STEP2_CHANGE_DETECTION", False):
            yod_asset = f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open"
            try:
                ee.data.getAssetAcl(yod_asset)
                print(f"✅ Already exists: YOD_{city_id}_open")
            except Exception:
                try:
                    detector = ChangeDetector()
                    yod_img = detector.detect_changes(city_id, years, bound)
                    task = ee.batch.Export.image.toAsset(
                        image=yod_img,
                        description=f"YOD_{city_id}_open",
                        assetId=yod_asset,
                        scale=30,
                        region=bound.geometry(),
                        maxPixels=1e13,
                    )
                    task.start()
                    print(f"🚀 YOD export submitted: {yod_asset}")
                except Exception as exc:
                    print(f"❌ Change detection failed: {exc}")

            TaskManager.wait_for_tasks()

        # ------------------------------------------------------------------
        # Step 3: LCZ classification (scenario-based)
        # ------------------------------------------------------------------
        if step_flags.get("STEP3_CLASSIFICATION", False):
            try:
                scenario_choice = _prompt_classification_scenario()
                print(f"🚀 Starting classification – Scenario {scenario_choice}")
                _run_classification_scenario(city_id, scenario_choice, bound, class_property)
            except Exception as exc:
                print(f"❌ Classification failed: {exc}")

            TaskManager.wait_for_tasks()

        # ------------------------------------------------------------------
        # Step 4: Temporal aggregation, consistency correction, YOD fusion
        # ------------------------------------------------------------------
        if step_flags.get("STEP4_AGGREGATION", False):
            try:
                print("🚀 Step 4: temporal consistency correction and aggregation")
                use_smooth = step_flags.get("STEP4_TEMPORAL_SMOOTHING", False)
                use_landcover_fusion = step_flags.get("STEP4_LANDCOVER_FUSION", False)
                bound_geometry = bound.geometry()

                lcz_series = TemporalAggregator.get_lcz_series(city_id, years, sampling_method)
                landcover_series = None

                if use_landcover_fusion:
                    landcover_series = TemporalAggregator.get_landcover_series(
                        bound_geometry, years
                    )
                    lcz_series = TemporalAggregator.replace_with_landcover(
                        lcz_series, bound_geometry, years
                    )

                if use_smooth:
                    print("🚀 Applying temporal smoothing …")
                    smoothed = TemporalAggregator.temporal_smoothing(lcz_series)
                    smoothed = smoothed.map(
                        lambda img: ee.Image(img).toInt16().copyProperties(
                            img, img.propertyNames()
                        )
                    )
                    lcz_series = smoothed

                    for year in years:
                        img = lcz_series.filter(ee.Filter.eq("year", year)).first()
                        out_id = (
                            f"{Config.GEE_ASSETS['LCZ_TEMP_SMOOTH']}"
                            f"LCZ_{city_id}_{year}{suffix}_smooth"
                        )
                        try:
                            ee.data.getAssetAcl(out_id)
                            print(f"✅ Already exists: {out_id}")
                            continue
                        except Exception:
                            pass

                        task = ee.batch.Export.image.toAsset(
                            image=img.rename(f"LCZ_{year}").toInt16(),
                            description=f"LCZ_{city_id}_{year}{suffix}_smooth",
                            assetId=out_id,
                            region=bound.geometry(),
                            scale=100,
                            maxPixels=1e13,
                        )
                        task.start()

                    TaskManager.wait_for_tasks()

                stacked = TemporalAggregator.stack_images(lcz_series)
                corrected = TemporalAggregator.correct_temporal_consistency(stacked, years)

                landcover_stack = (
                    TemporalAggregator.stack_images(landcover_series)
                    if landcover_series is not None
                    else None
                )

                # Export per-year corrected results
                for year in years:
                    corrected_band = corrected.select(f"LCZ_{year}")
                    out_id = f"{Config.GEE_ASSETS['LCZ_CORRECTED']}LCZ_{city_id}_{year}{suffix}"
                    try:
                        ee.data.getAssetAcl(out_id)
                        print(f"✅ Already exists: {out_id}")
                        continue
                    except Exception:
                        pass

                    task = ee.batch.Export.image.toAsset(
                        image=corrected_band.toInt16(),
                        description=f"LCZ_{city_id}_{year}{suffix}",
                        assetId=out_id,
                        region=bound.geometry(),
                        scale=30,
                        maxPixels=1e13,
                    )
                    task.start()

                # YOD-integrated export (latest year backwards)
                print("▶️  Integrating classification with YOD …")
                yod_img = ee.Image(f"{Config.GEE_ASSETS['LCZ_YOD']}YOD_{city_id}_open")
                integrated_series = TemporalAggregator.integrate_with_change_detection(
                    corrected, yod_img, years, landcover_stack
                )

                for year in reversed(years):
                    asset_id = (
                        f"{Config.GEE_ASSETS['LCZ_FINAL']}"
                        f"LCZ_{city_id}_{year}{suffix}_integrated"
                    )
                    try:
                        ee.data.getAssetAcl(asset_id)
                        print(f"✅ Already exists: {asset_id}")
                        continue
                    except Exception:
                        pass

                    export_img = integrated_series[year]
                    task = ee.batch.Export.image.toAsset(
                        image=export_img.toInt16(),
                        description=f"LCZ_Integrated_{city_id}_{year}{suffix}",
                        assetId=asset_id,
                        region=bound.geometry(),
                        scale=30,
                        maxPixels=1e13,
                    )
                    task.start()

            except Exception as exc:
                print(f"❌ Step 4 failed: {exc}")

            TaskManager.wait_for_tasks()

    # ------------------------------------------------------------------
    # Step 5: LCZ change visualisation (city-level loop outside city loop)
    # ------------------------------------------------------------------
    if step_flags.get("STEP5_VISUALISATION", False):
        from utils.visualizer import LCZPlotter
        from utils.lcz_tools import compute_lcz_transition

        for city_id in city_ids:
            input_path = Config.get_input_path(city_id)
            output_path = Config.get_output_path(city_id)
            os.makedirs(output_path, exist_ok=True)
            LCZPlotter.plot_lcz_changes(city_id, input_path, output_path, years, change_class_csv)
            try:
                compute_lcz_transition(city_id, output_path)
            except Exception as exc:
                print(f"❌ Transition calculation failed for {city_id}: {exc}")

    # ------------------------------------------------------------------
    # Step 6: Accuracy validation
    # ------------------------------------------------------------------
    if step_flags.get("STEP6_VALIDATION", False):
        val_fc = Config.VALIDATION_FC
        label = Config.VALIDATION_FIELD
        for city_id in city_ids:
            results = validate_series(city_id, years, val_fc, label, sampling_method)
            for year, (oa, matrix) in results.items():
                print(f"Accuracy for city {city_id}, year {year}: {oa}")
                print(matrix.getInfo())


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cli_main() -> None:
    parser = argparse.ArgumentParser(
        description="Urban Morphology LCZ Mapping CLI Tool",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--city_ids", nargs="+", type=int, required=True,
        help="List of city IDs to process",
    )
    parser.add_argument(
        "--sampling_method", type=str, default="stable",
        choices=["stable", "target", "cross", "asset"],
        help="Sampling strategy for LCZ classification (used in Steps 1/4/6)",
    )
    parser.add_argument(
        "--asset_path", type=str, default=None,
        help="GEE asset path when using the 'asset' sampling method",
    )
    parser.add_argument(
        "--asset_paths", nargs="+", default=None,
        help="Per-year asset paths for the 'asset' sampling method",
    )
    parser.add_argument(
        "--val_ratio", type=float, default=None,
        help="Fraction of samples held out for validation (0–1)",
    )
    parser.add_argument(
        "--class_property", type=str, default="LCZ",
        help="Class property name in the training sample feature collection",
    )
    args = parser.parse_args()
    main(
        args.city_ids,
        args.sampling_method,
        args.asset_path,
        args.asset_paths,
        args.class_property,
        args.val_ratio,
    )


if __name__ == "__main__":
    cli_main()
