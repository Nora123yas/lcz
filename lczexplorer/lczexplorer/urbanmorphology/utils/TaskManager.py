import ee
import re
import os
import time

class TaskManager:
    @staticmethod
    def wait_for_tasks():
        while True:
            tasks = ee.data.getTaskList()
            running = [t for t in tasks if t['state'] in ['READY', 'RUNNING']]
            if not running:
                break
            print(f"⏳ {len(running)} tasks running...")
            time.sleep(90)


class FileManager:
    @staticmethod
    def get_city_files(city_id, input_folder):
        """Extract files for a specific city from folder.

        Supports stacked multi-year overlays, legacy combined per-year files
        and the new separate LCZ / LST exports.
        The returned mapping is ``{year: {day|night: (path or (path, band_index)),
        'lcz': path}}``.  For combined per-year files the day/night value is the
        path to the image.  For stacked overlays the value is a tuple with the
        starting band index.
        """

        overlay_single = re.compile(rf'(day|night)_LST_LCZ_{city_id}_(\d{{4}})(?:_\w+)?\.tif')
        stacked = re.compile(rf'(day|night)_LST_LCZ_{city_id}_(\d{{4}})-(\d{{4}})(?:_\w+)?\.tif')
        lst_single = re.compile(rf'(day|night)_LST_{city_id}_(\d{{4}})(?:_\w+)?\.tif')
        lcz_single = re.compile(rf'LCZ_{city_id}_(\d{{4}})(?:_\w+)?\.tif')

        file_dict = {}

        for fname in os.listdir(input_folder):
            m = stacked.match(fname)
            if m:
                daynight, start, end = m.group(1), int(m.group(2)), int(m.group(3))
                path = os.path.join(input_folder, fname)
                for i, y in enumerate(range(start, end + 1)):
                    file_dict.setdefault(y, {})[daynight] = (path, i * 2)
                continue

            m = overlay_single.match(fname)
            if m:
                daynight, year = m.group(1), int(m.group(2))
                file_dict.setdefault(year, {})[daynight] = os.path.join(input_folder, fname)
                continue

            m = lst_single.match(fname)
            if m:
                daynight, year = m.group(1), int(m.group(2))
                file_dict.setdefault(year, {})[daynight] = os.path.join(input_folder, fname)
                continue

            m = lcz_single.match(fname)
            if m:
                year = int(m.group(1))
                file_dict.setdefault(year, {})['lcz'] = os.path.join(input_folder, fname)

        return dict(sorted(file_dict.items()))

