"""Accuracy evaluation utilities."""
from utils import config as Config


def confusion_matrix(y_true, y_pred, labels=None):
    """Compute confusion matrix and label order."""
    if labels is None:
        labels = sorted(set(y_true) | set(y_pred))
    label_to_idx = {l: i for i, l in enumerate(labels)}
    size = len(labels)
    matrix = [[0 for _ in labels] for _ in labels]
    for t, p in zip(y_true, y_pred):
        i = label_to_idx[t]
        j = label_to_idx[p]
        matrix[i][j] += 1
    return labels, matrix


def calculate_accuracy(y_true, y_pred, labels=None):
    labels, matrix = confusion_matrix(y_true, y_pred, labels)
    total = sum(sum(row) for row in matrix)
    correct = sum(matrix[i][i] for i in range(len(matrix)))
    accuracy = correct / total if total else 0
    return accuracy, labels, matrix


def validate_year(city_id, year, validation_fc_path, label_field, sampling_method='stable'):
    """Validate a single year's classification using a validation feature collection."""
    import ee
    suffix = f"_{sampling_method}" if sampling_method and sampling_method != 'stable' else ""
    img_id = f"{Config.GEE_ASSETS['LCZ_FINAL']}LCZ_{city_id}_{year}{suffix}_integrated"
    band = f"LCZ_integrated_{year}"
    class_img = ee.Image(img_id).select(band)
    validation_fc = ee.FeatureCollection(validation_fc_path)
    samples = class_img.sampleRegions(
        collection=validation_fc,
        properties=[label_field],
        scale=30,
        geometries=False
    )
    matrix = samples.errorMatrix(label_field, band)
    return matrix.accuracy(), matrix


def validate_series(city_id, years, validation_fc_path, label_field, sampling_method='stable'):
    results = {}
    for year in years:
        oa, matrix = validate_year(city_id, year, validation_fc_path, label_field, sampling_method)
        results[year] = (oa, matrix)
    return results
