#!/usr/bin/env python3
# Copyright 2026 Fatima M. Pillosu
# SPDX-License-Identifier: Apache-2.0
# See LICENSE and NOTICE for licence terms and attribution.
"""Historical PoFF inference from ERA5/ERA5-ecPoint GRIB inputs.

Scientific conventions follow probability_of_flash_flood, commit 17e1b5f.
All command-line dates denote accumulation START dates, at 00 UTC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile

import numpy as np
import pandas as pd

LOG = logging.getLogger("poff")
FEATURES = (
    "tp_prob_1", "tp_prob_max_1_adj_gb", "tp_prob_50",
    "tp_prob_max_50_adj_gb", "swvl", "sdfor", "lai",
)
SATURATION = np.array([np.nan, .403, .439, .430, .520, .614, .766, .472])
STATIC_INPUTS = (
    "sdfor", "land_sea_mask", "soil_type", "cover_low", "cover_high",
    "climatology", "return_periods", "neighbourhoods",
)
DAILY_INPUTS = ("rainfall", "swvl1", "swvl2", "swvl3", "lai_low", "lai_high")
PUBLIC_METADATA_FIELDS = ("license", "creator_name", "creator_url", "attribution")


def date_range(first: datetime, last: datetime):
    if last < first:
        raise ValueError("The end date must be on or after the start date")
    day = first
    while day <= last:
        yield day
        day += timedelta(days=1)


def expand_path(template: str, root: str, day: datetime) -> Path:
    """Dates are explicit: start = D 00 UTC, end = D+1 00 UTC."""
    return Path(template.format(root=root, start=day, end=day + timedelta(days=1)))


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def json_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run_identity(config, model_path):
    """One provenance definition shared by inference and independent verification."""
    model_hash = sha256_file(model_path)
    run_hash = json_hash({
        "config": config, "model_sha256": model_hash,
        "code_sha256": sha256_file(Path(__file__)),
    })
    return model_hash, run_hash


def check_range(name, values, minimum, maximum):
    values = np.asarray(values)
    if np.isinf(values).any():
        raise ValueError(f"{name}: infinite values")
    finite = values[np.isfinite(values)]
    if np.any(finite < minimum) or np.any(finite > maximum):
        raise ValueError(f"{name}: values outside [{minimum}, {maximum}]")


def soil_saturation(layer1, layer2, layer3, soil_type):
    """Fraction, not percent; maximum saturation depends on ERA5 soil type."""
    soil_type = np.asarray(soil_type)
    valid = np.isfinite(soil_type) & (soil_type >= 1) & (soil_type <= 7)
    if np.any(valid & (soil_type != np.floor(soil_type))):
        raise ValueError("Soil type must contain integer codes")
    maximum = np.full(soil_type.shape, np.nan)
    maximum[valid] = SATURATION[soil_type[valid].astype(int)]
    for name, values in zip(("swvl1", "swvl2", "swvl3"), (layer1, layer2, layer3)):
        check_range(name, values, 0, 1)
    integrated = .07 * layer1 + .21 * layer2 + .72 * layer3
    return np.minimum(integrated / maximum, 1.0)


def rainfall_features(fields, threshold1, threshold50, expected_count=99):
    """Stream percentiles; compute percent exceedance and the dry-day mask.

    Inputs must share units (the runner converts both to mm). Missing rainfall
    in any percentile remains missing, rather than being counted as dry.
    """
    counts1 = np.zeros(threshold1.shape, dtype=np.int32)
    counts50 = np.zeros(threshold50.shape, dtype=np.int32)
    total = np.zeros(threshold1.shape, dtype=np.float64)
    complete = np.ones(threshold1.shape, dtype=bool)
    count = 0
    for field in fields:
        field = np.asarray(field)
        if field.shape != total.shape:
            raise ValueError("Rainfall and climatology have different grid sizes")
        check_range("rainfall", field, 0, np.inf)
        complete &= np.isfinite(field)
        counts1 += field >= threshold1
        counts50 += field >= threshold50
        total += field
        count += 1
    if count != expected_count:
        raise ValueError(f"Expected {expected_count} rainfall percentiles; found {count}")
    p1 = np.where(complete & np.isfinite(threshold1), counts1 * 100.0 / count, np.nan)
    p50 = np.where(complete & np.isfinite(threshold50), counts50 * 100.0 / count, np.nan)
    return p1, p50, np.where(complete, total, np.nan)


class Neighbourhoods:
    """Use the supplied mapping unchanged; flatten it once for fast maxima."""

    def __init__(self, rows, npoints):
        if len(rows) != npoints:
            raise ValueError("Neighbourhood mapping does not match the grid size")
        converted = []
        for row in rows:
            raw = np.asarray(row)
            if raw.ndim != 1 or raw.size == 0:
                raise ValueError("Each grid point must have a non-empty neighbourhood")
            if not np.issubdtype(raw.dtype, np.integer):
                # npy object arrays sometimes contain Python ints in object rows.
                if any(not isinstance(x, (int, np.integer)) for x in raw):
                    raise ValueError("Neighbourhood indices must be integers")
            indices = raw.astype(np.int64)
            if (indices < 0).any() or (indices >= npoints).any():
                raise ValueError("Neighbourhood index outside the input grid")
            converted.append(indices)
        lengths = np.array([len(row) for row in converted])
        self.starts = np.r_[0, np.cumsum(lengths)[:-1]]
        self.indices = np.concatenate(converted)

    def maximum(self, values):
        # np.maximum propagates NaN, matching np.max in the research script.
        return np.maximum.reduceat(np.asarray(values)[self.indices], self.starts)


def validate_model(model):
    if list(model.classes_) != [0, 1]:
        raise ValueError("Expected binary model classes [0, 1]")
    if model.n_features_in_ != len(FEATURES):
        raise ValueError("The model must expect seven predictors")
    names = model.get_booster().feature_names
    if names is not None and list(names) != list(FEATURES):
        raise ValueError(f"Model feature order differs from {FEATURES}")


def predict_day(model, features, rainfall_total, land_mask, batch_size):
    """Predict wet land points; dry land is zero and ocean/missing rain is NaN."""
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    if tuple(features) != FEATURES:
        raise ValueError("Feature names or ordering differ from the model contract")
    size = len(land_mask)
    for name, values in features.items():
        if np.shape(values) != (size,):
            raise ValueError(f"{name}: incorrect grid size")
        if np.isinf(values).any():
            raise ValueError(f"{name}: infinite values")
    result = np.full(size, np.nan, dtype=np.float32)
    land = np.asarray(land_mask) > 0
    known_rain = np.isfinite(rainfall_total)
    result[land & known_rain & (rainfall_total == 0)] = 0
    selected = np.flatnonzero(land & known_rain & (rainfall_total > 0))
    missing_count = 0
    for offset in range(0, len(selected), batch_size):
        indices = selected[offset:offset + batch_size]
        frame = pd.DataFrame({name: features[name][indices] for name in FEATURES})
        missing_count += int(frame.isna().any(axis=1).sum())
        # Preserve XGBoost's learned missing-value handling, as in inference code.
        probabilities = np.asarray(model.predict_proba(frame))
        if probabilities.shape != (len(indices), 2):
            raise ValueError("Unexpected predict_proba output shape")
        positive = probabilities[:, 1]
        if not np.isfinite(positive).all() or np.any((positive < 0) | (positive > 1)):
            raise ValueError("Model returned invalid probabilities")
        result[indices] = positive * 100
    if missing_count:
        LOG.warning("XGBoost handled missing predictor values at %d wet land points", missing_count)
    return result


class GribReader:
    """Metview I/O with checks for grid ordering, not implicit regridding."""

    def __init__(self, reference_path):
        import metview as mv
        self.mv = mv
        self.reference = mv.read(str(reference_path))
        if len(self.reference) != 1:
            raise ValueError("SDFOR must contain exactly one GRIB field")
        self.latitude = np.asarray(mv.latitudes(self.reference))
        self.longitude = np.asarray(mv.longitudes(self.reference))
        self.npoints = len(self.latitude)

    def values(self, field, label):
        values = np.asarray(self.mv.values(field), dtype=np.float64)
        lat = np.asarray(self.mv.latitudes(field))
        lon = np.asarray(self.mv.longitudes(field))
        if values.shape != (self.npoints,) or lat.shape != self.latitude.shape:
            raise ValueError(f"{label}: different grid size")
        if not np.allclose(lat, self.latitude, rtol=0, atol=1e-6):
            raise ValueError(f"{label}: different latitude ordering")
        delta = (lon - self.longitude + 180) % 360 - 180
        if not np.all(np.abs(delta) <= 1e-6):
            raise ValueError(f"{label}: different longitude ordering")
        return values

    def single(self, path):
        fields = self.mv.read(str(path))
        if len(fields) != 1:
            raise ValueError(f"{path}: expected a single GRIB field; found {len(fields)}")
        return self.values(fields, str(path))

    def rainfall(self, path, count, scale):
        fields = self.mv.read(str(path))
        if len(fields) != count:
            raise ValueError(f"{path}: expected {count} percentile fields; found {len(fields)}")
        for i in range(len(fields)):
            yield self.values(fields[i], f"{path} field {i + 1}") * scale

    def thresholds(self, path, periods_path, scale):
        periods = np.load(periods_path, allow_pickle=False).reshape(-1)
        fields = self.mv.read(str(path))
        if len(fields) != len(periods):
            raise ValueError("Climatology GRIB and return-period list have different lengths")
        result = []
        for period in (1, 50):
            matches = np.flatnonzero(periods == period)
            if len(matches) != 1:
                raise ValueError(f"Climatology must have exactly one {period}-year threshold")
            values = self.values(fields[int(matches[0])], f"{period}-year climatology") * scale
            check_range("climatology", values, 0, np.inf)
            result.append(values)
        finite = np.isfinite(result[0]) & np.isfinite(result[1])
        if np.any(result[1][finite] < result[0][finite]):
            raise ValueError("50-year rainfall thresholds are below 1-year thresholds")
        return result


def load_config(path):
    with Path(path).open(encoding="utf-8") as stream:
        config = json.load(stream)
    for key in ("root", "model", "model_label", "inputs", "output"):
        if key not in config:
            raise ValueError(f"Configuration is missing {key}")
    for key in STATIC_INPUTS + DAILY_INPUTS:
        if key not in config["inputs"]:
            raise ValueError(f"Configuration is missing inputs.{key}")
    publication = config.get("output_metadata", {})
    if not isinstance(publication, dict):
        raise ValueError("output_metadata must be an object")
    if set(publication) - set(PUBLIC_METADATA_FIELDS):
        raise ValueError("output_metadata contains unsupported fields")
    if any(not isinstance(value, str) or not value.strip() for value in publication.values()):
        raise ValueError("output_metadata values must be non-empty strings")
    config.setdefault("batch_size", 100_000)
    config.setdefault("threads", 4)
    config.setdefault("percentile_count", 99)
    config.setdefault("rainfall_scale_to_mm", 1.0)
    config.setdefault("climatology_scale_to_mm", 1.0)
    for key in ("batch_size", "threads", "percentile_count"):
        if not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    for key in ("rainfall_scale_to_mm", "climatology_scale_to_mm"):
        if not np.isfinite(config[key]) or config[key] <= 0:
            raise ValueError(f"{key} must be positive and finite")
    # Static files must stay constant throughout a multi-day run.
    for key in STATIC_INPUTS:
        if "{start" in config["inputs"][key] or "{end" in config["inputs"][key]:
            raise ValueError(f"Static input {key} cannot depend on the date")
    if "{start" in config["model"] or "{end" in config["model"]:
        raise ValueError("The saved model cannot vary by date within a run")
    return config


def input_paths(config, day):
    return {
        key: expand_path(template, config["root"], day)
        for key, template in config["inputs"].items()
    }


def input_manifest(paths):
    """Record file identity cheaply; large GRIB files are not fully rehashed."""
    manifest = {}
    for name, path in paths.items():
        stat = path.stat()
        if not path.is_file() or stat.st_size == 0:
            raise ValueError(f"{name}: expected a non-empty file: {path}")
        manifest[name] = {
            "path": str(path.resolve()), "size_bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }
    return manifest


def check_input_files(config, days):
    """Read-only path check, usable without Metview or loading the estimator."""
    checked = set()
    errors = []
    outputs = set()
    all_inputs = set()
    for day in days:
        paths = input_paths(config, day)
        paths["model"] = expand_path(config["model"], config["root"], day)
        for name, path in paths.items():
            absolute = path.resolve()
            all_inputs.add(absolute)
            if absolute not in checked:
                checked.add(absolute)
                if not path.is_file() or path.stat().st_size == 0:
                    errors.append(f"{name}: missing or empty: {path}")
        output = expand_path(config["output"], config["root"], day).resolve()
        if output in outputs:
            raise ValueError("Output template maps multiple days to the same file")
        outputs.add(output)
    if all_inputs & outputs:
        raise ValueError("An output path would overwrite an input file")
    for error in errors:
        LOG.error(error)
    LOG.info("Checked %d distinct input files; %d missing or empty", len(checked), len(errors))
    return not errors


class Runner:
    """Keep model, grid, climatology and other static inputs resident in memory."""

    def __init__(self, config, first_day):
        import joblib

        self.config = config
        paths = input_paths(config, first_day)
        model_path = expand_path(config["model"], config["root"], first_day)
        self.static_manifest = input_manifest({key: paths[key] for key in STATIC_INPUTS})
        self.static_manifest.update(input_manifest({"model": model_path}))
        self.model_hash, self.run_hash = run_identity(config, model_path)
        self.model = joblib.load(model_path)
        validate_model(self.model)
        self.model.set_params(n_jobs=config["threads"])
        self.reader = GribReader(paths["sdfor"])
        self.static = {key: self.reader.single(paths[key]) for key in (
            "sdfor", "land_sea_mask", "soil_type", "cover_low", "cover_high",
        )}
        for name in ("land_sea_mask", "cover_low", "cover_high"):
            check_range(name, self.static[name], 0, 1)
        check_range("sdfor", self.static["sdfor"], 0, np.inf)
        self.threshold1, self.threshold50 = self.reader.thresholds(
            paths["climatology"], paths["return_periods"], config["climatology_scale_to_mm"],
        )
        # This is the existing, trusted NumPy mapping used by the research code.
        rows = np.load(paths["neighbourhoods"], allow_pickle=True)
        self.neighbourhoods = Neighbourhoods(rows, self.reader.npoints)
        LOG.info("Loaded %s; %d grid points", config["model_label"], self.reader.npoints)

    def calculate(self, paths):
        c = self.config
        p1, p50, rainfall_total = rainfall_features(
            self.reader.rainfall(paths["rainfall"], c["percentile_count"], c["rainfall_scale_to_mm"]),
            self.threshold1, self.threshold50, c["percentile_count"],
        )
        layers = [self.reader.single(paths[f"swvl{i}"]) for i in (1, 2, 3)]
        saturation = soil_saturation(*layers, self.static["soil_type"])
        low = self.reader.single(paths["lai_low"])
        high = self.reader.single(paths["lai_high"])
        check_range("lai_low", low, 0, np.inf)
        check_range("lai_high", high, 0, np.inf)
        lai = low * self.static["cover_low"] + high * self.static["cover_high"]
        features = dict(zip(FEATURES, (
            p1, self.neighbourhoods.maximum(p1), p50, self.neighbourhoods.maximum(p50),
            saturation, self.static["sdfor"], lai,
        )))
        return predict_day(self.model, features, rainfall_total, self.static["land_sea_mask"], c["batch_size"])

    def manifest(self, paths):
        manifest = dict(self.static_manifest)
        # Fail if static files are replaced during a run; do not mix versions.
        current = input_manifest({key: paths[key] for key in STATIC_INPUTS})
        if any(current[key] != manifest[key] for key in STATIC_INPUTS):
            raise ValueError("A static input changed during the run; restart with consistent inputs")
        manifest.update(input_manifest({key: paths[key] for key in DAILY_INPUTS}))
        return manifest


def hours_since_epoch(day):
    return (day - datetime(1970, 1, 1)).total_seconds() / 3600


def validate_output(path, day, npoints, run_hash, manifest_hash):
    """Read back metadata and data before accepting a file as complete."""
    from netCDF4 import Dataset

    with Dataset(path) as dataset:
        expected = {
            "processing_status": "complete", "run_sha256": run_hash,
            "input_manifest_sha256": manifest_hash,
            "time_coverage_start": day.strftime("%Y-%m-%dT00:00:00Z"),
            "time_coverage_end": (day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z"),
        }
        for name, value in expected.items():
            if getattr(dataset, name, None) != value:
                raise ValueError(f"{path}: {name} differs; use a new destination or --overwrite")
        variable = dataset.variables["poff"]
        # Otherwise netCDF4 would mask out-of-range values before validation.
        variable.set_auto_mask(False)
        if variable.shape != (1, npoints) or variable.units != "%":
            raise ValueError(f"{path}: invalid probability dimensions or units")
        bounds = dataset.variables["time_bounds"][:]
        correct = [[hours_since_epoch(day), hours_since_epoch(day + timedelta(days=1))]]
        if not np.array_equal(bounds, correct):
            raise ValueError(f"{path}: incorrect time bounds")
        if not np.array_equal(dataset.variables["time"][:], [correct[0][1]]):
            raise ValueError(f"{path}: incorrect time coordinate")
        for name in ("latitude", "longitude"):
            coords = dataset.variables[name][:]
            if coords.shape != (npoints,) or not np.isfinite(coords).all():
                raise ValueError(f"{path}: invalid {name} coordinates")
        values = np.ma.filled(variable[:], np.nan)
        check_range("saved probabilities", values, 0, 100)
        if not np.isfinite(values).any():
            raise ValueError(f"{path}: no finite probabilities")


def write_output(path, day, probabilities, latitude, longitude, metadata, overwrite=False):
    """Publish only a fully written, read-back-checked file in the final location."""
    from netCDF4 import Dataset

    path = Path(path)
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite {path}")
    if np.shape(probabilities) != np.shape(latitude) or np.shape(latitude) != np.shape(longitude):
        raise ValueError("Output values and coordinates have different shapes")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".partial", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary)
    try:
        with Dataset(temporary, "w", format="NETCDF4") as dataset:
            dataset.createDimension("time", 1)
            dataset.createDimension("point", len(probabilities))
            dataset.createDimension("bounds", 2)
            time = dataset.createVariable("time", "f8", ("time",))
            time.standard_name = "time"
            time.units = "hours since 1970-01-01 00:00:00"
            time.calendar = "proleptic_gregorian"
            time.bounds = "time_bounds"
            time[:] = [hours_since_epoch(day + timedelta(days=1))]
            bounds = dataset.createVariable("time_bounds", "f8", ("time", "bounds"))
            bounds[:] = [[hours_since_epoch(day), hours_since_epoch(day + timedelta(days=1))]]
            for name, values, units in (
                ("latitude", latitude, "degrees_north"),
                ("longitude", longitude, "degrees_east"),
            ):
                coord = dataset.createVariable(name, "f8", ("point",), zlib=True, complevel=4, fletcher32=True)
                coord.standard_name = name
                coord.units = units
                coord[:] = values
            variable = dataset.createVariable(
                "poff", "f4", ("time", "point"), fill_value=np.float32(np.nan),
                zlib=True, complevel=4, shuffle=True, fletcher32=True,
            )
            variable.long_name = "Probability of at least one flash flood within the grid box over 24 hours"
            variable.units = "%"
            variable.coordinates = "latitude longitude"
            variable.valid_range = np.array([0, 100], dtype=np.float32)
            variable.comment = "Ocean and missing-rainfall points are missing; dry land is zero."
            variable[0, :] = probabilities
            dataset.title = "ERA5-based historical probability of flash floods"
            dataset.grid_description = "Native input grid and point order, without interpolation"
            dataset.time_coverage_start = day.strftime("%Y-%m-%dT00:00:00Z")
            dataset.time_coverage_end = (day + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
            dataset.feature_order = json.dumps(FEATURES)
            dataset.history = datetime.now(timezone.utc).isoformat() + " created by poff.py"
            for key, value in metadata.items():
                dataset.setncattr(key, value)
            dataset.processing_status = "complete"
        validate_output(temporary, day, len(probabilities), metadata["run_sha256"], metadata["input_manifest_sha256"])
        if overwrite:
            os.replace(temporary, path)
        else:
            # Same-filesystem hard link is atomic and cannot clobber another job's output.
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run(config, days, overwrite=False, continue_on_error=False):
    runner = Runner(config, days[0])
    completed = skipped = failed = 0
    for day in days:
        try:
            paths = input_paths(config, day)
            manifest = runner.manifest(paths)
            manifest_hash = json_hash(manifest)
            output = expand_path(config["output"], config["root"], day)
            if output.exists() and not overwrite:
                validate_output(output, day, runner.reader.npoints, runner.run_hash, manifest_hash)
                LOG.info("%s: existing output verified; skipping", day.date())
                skipped += 1
                continue
            LOG.info("%s: calculating predictors and PoFF", day.date())
            probabilities = runner.calculate(paths)
            if runner.manifest(paths) != manifest:
                raise ValueError("An input changed while this day was being processed")
            write_output(
                output, day, probabilities, runner.reader.latitude, runner.reader.longitude,
                {
                    "model_label": config["model_label"], "model_sha256": runner.model_hash,
                    "run_sha256": runner.run_hash, "input_manifest_sha256": manifest_hash,
                    # Keep local paths in memory for restart checks, not in published data.
                    "references": "https://doi.org/10.5194/egusphere-2026-1591",
                    "research_source": "https://github.com/FatimaPillosu/probability_of_flash_flood/tree/17e1b5f3764c67dbc75d22bf57e7a0fa6f5e7b04",
                    **{key: value for key, value in config.get("output_metadata", {}).items()
                       if key in PUBLIC_METADATA_FIELDS},
                }, overwrite=overwrite,
            )
            completed += 1
            LOG.info("%s: saved %s", day.date(), output)
        except Exception:
            failed += 1
            LOG.exception("%s: failed", day.date())
            if not continue_on_error:
                break
    LOG.info("Finished: %d written, %d verified/skipped, %d failed", completed, skipped, failed)
    return 1 if failed else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--start", type=lambda s: datetime.strptime(s, "%Y-%m-%d"), required=True,
                        help="First accumulation START date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--end", type=lambda s: datetime.strptime(s, "%Y-%m-%d"), required=True,
                        help="Last accumulation START date, inclusive (YYYY-MM-DD)")
    parser.add_argument("--check-inputs", action="store_true", help="Check paths only; no model loading or output")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace existing daily outputs")
    parser.add_argument("--continue-on-error", action="store_true", help="Continue after a failed day; still exit non-zero")
    parser.add_argument("--log-file", type=Path, help="Append a log to this file")
    args = parser.parse_args(argv)
    handlers = [logging.StreamHandler()]
    if args.log_file:
        handlers.append(logging.FileHandler(args.log_file))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    try:
        config = load_config(args.config)
        days = list(date_range(args.start, args.end))
        ready = check_input_files(config, days)
        if args.check_inputs:
            return 0 if ready else 1
        if not ready and not args.continue_on_error:
            return 1
        return run(config, days, args.overwrite, args.continue_on_error)
    except Exception:
        LOG.exception("Run could not start")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
