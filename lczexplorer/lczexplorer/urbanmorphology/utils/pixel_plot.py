"""Utility for plotting LST time series of a single pixel.

Usage::

    python -m utils.pixel_plot CITY_ID day|night CHANGE_CODE PIXEL_INDEX

The script reports how many valid pixels exist for ``CHANGE_CODE`` and
displays a plot with:

* Median values of the stable urban pixels (LCZ unchanged ``<=10``).
* Their fitted linear trend and equation.
* Raw LST values for the requested pixel on the left y-axis.
* Detrended values on a secondary axis due to the smaller range.
"""

import os
import numpy as np
import matplotlib.pyplot as plt

from utils import config as Config
from utils.TaskManager import FileManager
from utils.processors import DetrendAnalyzer


def plot_pixel_timeseries(city_id, daynight, change_code, pixel_idx):
    """Plot raw and detrended LST series for a single pixel.

    Parameters
    ----------
    city_id : int
        Identifier of the city.
    daynight : {"day", "night"}
        Whether to use day or night composites.
    change_code : int
        LCZ change code, e.g. 1112.
    pixel_idx : int
        Index of the pixel within the selected change class after removing
        invalid values.

    Returns
    -------
    tuple
        ``(n_valid, fig)`` where ``n_valid`` is the number of valid pixels for
        the given ``change_code`` and ``fig`` is the created Matplotlib figure.
    """
    input_dir = Config.get_input_path(city_id)
    file_dict = FileManager.get_city_files(city_id, input_dir)

    analyzer = DetrendAnalyzer(n_years=Config.DETREND_N)
    years = sorted(file_dict.keys())
    valid_years = [
        y for y in years
        if daynight in file_dict[y] and (
            isinstance(file_dict[y][daynight], tuple) or 'lcz' in file_dict[y]
        )
    ]
    if len(valid_years) < 2 * analyzer.n_years + 5:
        raise ValueError("Insufficient time series length for analysis")

    lcz_stack, lst_stack = analyzer._load_data_stack(file_dict, valid_years, daynight)

    n = analyzer.n_years
    year1, year2 = valid_years[n - 1], valid_years[-n]
    idx1, idx2 = valid_years.index(year1), valid_years.index(year2)

    lcz_s, lcz_e = lcz_stack[..., 0], lcz_stack[..., -1]
    lcz1, lcz2 = lcz_stack[..., idx1], lcz_stack[..., idx2]
    change = lcz1 * 100 + lcz2

    urban_mask = (lcz_s == lcz_e) & (lcz_s <= 10) & (lcz_s > 0)
    urban_data = lst_stack[urban_mask, :]
    urban_data = urban_data[~np.any(urban_data == -32768, axis=1)]
    if urban_data.shape[0] == 0:
        raise ValueError("No stable urban pixels found")

    urban_median = np.nanmedian(urban_data / 100, axis=0)
    slope, intercept = np.polyfit(valid_years, urban_median, 1)

    mask = change == change_code
    sample = lst_stack[mask, :]
    sample = sample[~np.any(sample == -32768, axis=1)]
    n_valid = sample.shape[0]
    if n_valid == 0:
        raise ValueError(f"No valid pixels for change code {change_code}")
    if pixel_idx >= n_valid or pixel_idx < 0:
        raise IndexError(f"pixel_idx should be in [0, {n_valid-1}]")

    series = sample[pixel_idx] / 100
    trend = slope * np.array(valid_years) + intercept
    detrended = series - trend

    fig, ax = plt.subplots()
    ax.plot(valid_years, urban_median, "o", color="gray", label="Stable median")
    ax.plot(
        valid_years,
        trend,
        "k--",
        label=f"Fit: y={slope:.2f}x+{intercept:.2f}",
    )
    ax.plot(valid_years, series, "o-", label="Raw LST")

    ax.set_xlabel("Year")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title(f"City {city_id} {daynight.capitalize()} Pixel {pixel_idx}")

    ax2 = ax.twinx()
    ax2.plot(valid_years, detrended, "s-", color="C2", label="Detrended")
    ax2.set_ylabel("Detrended (°C)")

    lines, labels = ax.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax2.legend(lines + lines2, labels + labels2, loc="best")
    fig.tight_layout()

    return n_valid, fig


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Plot LST time series for a single pixel")
    parser.add_argument("city_id", type=int, help="City identifier")
    parser.add_argument("daynight", choices=["day", "night"], help="Day or night composites")
    parser.add_argument("change_code", type=int, help="LCZ change code")
    parser.add_argument("pixel_idx", type=int, help="Index within the selected change pixels")
    args = parser.parse_args()

    count, fig = plot_pixel_timeseries(args.city_id, args.daynight, args.change_code, args.pixel_idx)
    print(f"Valid pixels for change code {args.change_code}: {count}")
    plt.show()

