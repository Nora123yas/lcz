import pandas as pd
import ee
from pathlib import Path
from typing import Optional, List
from . import config as Config

CLASSES = [
    "VD_total",
    "Densification",
    "De-densification",
    "De-urbanization",
    "Expansion",
    "Stable",
]


def compute_lcz_transition(city_id: str,
                            output_dir: Path,
                            gee_lcz_path: str = None,
                            year_start: int = None,
                            year_end: int = None,
                            scale: int = 100) -> Optional[Path]:
    """Compute LCZ transitions at 100m resolution using GEE images."""
    gee_lcz_path = gee_lcz_path or Config.GEE_ASSETS.get("LCZ_FINAL", "")
    year_start = year_start or Config.START_YEAR
    year_end = year_end or Config.END_YEAR

    img_start = ee.Image(f"{gee_lcz_path}LCZ_{city_id}_{year_start}_target_integrated")
    img_end = ee.Image(f"{gee_lcz_path}LCZ_{city_id}_{year_end}_target_integrated")

    mask = (img_start.gt(0).And(img_start.lte(17))
            .And(img_end.gt(0)).And(img_end.lte(17)))
    img_start = img_start.updateMask(mask)
    img_end = img_end.updateMask(mask)

    change_img = ee.Image.pixelArea().rename("area").addBands(
        img_start.multiply(100).add(img_end).rename("code")
    )

    stats = change_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1, groupName="code"),
        geometry=img_end.geometry(),
        scale=scale,
        maxPixels=1e13,
        tileScale=16,
    )

    groups = ee.List(stats.get("groups")).getInfo()
    if not groups:
        print(f"\u26a0\ufe0f {city_id}: no data or permission")
        return None

    records = []
    total = 0.0
    for d in groups:
        code = int(d["code"])
        area = d["sum"]
        records.append({
            "from": code // 100,
            "to": code % 100,
            "code": code,
            "area_m2": area,
        })
        total += area

    for r in records:
        r["percentage"] = r["area_m2"] / total * 100 if total else 0

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    year_str = f"{year_start}to{year_end}"
    out_csv = output_dir / f"LCZ_transition_{city_id}_{year_str}_100m.csv"
    pd.DataFrame(records).to_csv(out_csv, index=False, encoding="utf-8-sig")
    print(f"\u2705 Saved {out_csv}")
    return out_csv


def compute_city_class_percent(city_id: str,
                                base_dir: Path,
                                change_map: pd.DataFrame,
                                year_str: str,
                                verbose: bool = False) -> Optional[pd.Series]:
    """Return percentage of transition classes for one city."""
    csv_path = base_dir / str(city_id) / "output" / f"LCZ_transition_{city_id}_{year_str}_100m.csv"
    if not csv_path.exists():
        if verbose:
            print(f"\u26a0\ufe0f Missing CSV for city {city_id}: {csv_path}")
        return None

    try:
        df = pd.read_csv(csv_path).merge(change_map, on="code", how="left")
    except Exception as e:  # pragma: no cover - IO issues
        if verbose:
            print(f"\u274c Failed loading {csv_path}: {e}")
        return None

    if df.empty or df["class"].isna().all():
        if verbose:
            print(f"\u26a0\ufe0f No valid class mapping for city {city_id}")
        return None

    df_cls = (
        df.groupby("class", dropna=False)
        .agg(total_percentage=("percentage", "sum"))
        .reset_index()
    )

    percent = dict(zip(df_cls["class"], df_cls["total_percentage"]))
    series = pd.Series({cls: percent.get(cls, 0.0) for cls in CLASSES}, name=city_id)
    if verbose:
        print(series)
    return series


def summarize_cities(city_meta_path: Path,
                      change_csv: Path,
                      base_dir: Path,
                      year_str: str,
                      output_csv: Path) -> pd.DataFrame:
    """Aggregate class percentages for all cities."""
    meta = pd.read_excel(city_meta_path, dtype=str)
    meta.columns = [str(c).lower().strip() for c in meta.columns]
    change_map = pd.read_csv(change_csv)[["change", "class"]].rename(columns={"change": "code"})

    records = []
    for _, row in meta.iterrows():
        city_id = str(row["id"])
        result = compute_city_class_percent(city_id, base_dir, change_map, year_str)
        if result is None:
            continue
        record = {
            "id": city_id,
            "name": row.get("name", ""),
            "continent": row.get("continent") or row.get("CONTINENT"),
            "climtype": row.get("climtype") or row.get("CLIMTYPE"),
        }
        record.update(result.to_dict())
        records.append(record)

    df_out = pd.DataFrame(records)
    output_csv = Path(output_csv)
    df_out.to_csv(output_csv, index=False, encoding="utf-8-sig")
    print(f"\ud83d\udcbe Summary saved to {output_csv}")
    return df_out


def show_city_per(city_id: str,
                   summary_csv: Path,
                   classes: Optional[List[str]] = None,
                   sort_desc: bool = True) -> None:
    """Display class percentage for one city from summary table."""
    df = pd.read_csv(summary_csv, dtype={"id": str})
    row = df[df["id"] == str(city_id)]
    if row.empty:
        print(f"\u274c City ID {city_id} not found\n")
        return

    data = row.iloc[0]
    classes = classes or [c for c in df.columns if c not in ["id", "name", "continent", "climtype"]]
    values = {cls: data.get(cls, 0.0) for cls in classes}
    df_out = pd.DataFrame({"class": list(values.keys()), "percentage": list(values.values())})
    df_out = df_out.sort_values("percentage", ascending=not sort_desc)

    print(f"\n=== \u57ce\u5e02 {city_id} \u5404\u7c7b\u53d8\u5316\u7ec4\u6210 (100m) ===")
    print(df_out.to_string(index=False, formatters={"percentage": "{:.2f}".format}))
    print()
