# Copyright 2026 Fatima M. Pillosu
# SPDX-License-Identifier: Apache-2.0
# See LICENSE and NOTICE for licence terms and attribution.
"""Numerical and operational checks; no Metview or production model required."""
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

import poff


def test_soil_layer_weights_and_soil_type_normalisation():
    result = poff.soil_saturation(
        np.array([.1, 1., .1]), np.array([.2, 1., .2]),
        np.array([.3, 1., .3]), np.array([1, 2, 0]),
    )
    assert result[0] == pytest.approx((.007 + .042 + .216) / .403)
    assert result[1] == 1
    assert np.isnan(result[2])


def test_percentile_exceedance_includes_equality_and_preserves_missing():
    fields = [np.array([0., 0., 1.]), np.array([10., 0., np.nan]), np.array([20., 0., 3.])]
    p1, p50, total = poff.rainfall_features(
        iter(fields), np.array([10., 1., 1.]), np.array([20., 2., 2.]), 3,
    )
    np.testing.assert_allclose(p1[:2], [200 / 3, 0])
    np.testing.assert_allclose(p50[:2], [100 / 3, 0])
    np.testing.assert_allclose(total[:2], [30, 0])
    assert np.isnan(p1[2]) and np.isnan(p50[2]) and np.isnan(total[2])


def test_incomplete_percentile_file_fails():
    with pytest.raises(ValueError, match="Expected 99"):
        poff.rainfall_features([np.ones(2)], np.ones(2), np.ones(2))


def test_neighbourhood_maxima_match_reference_loop():
    rows = [np.array([0, 2]), np.array([1]), np.array([0, 1, 2])]
    values = np.array([2., np.nan, 7.])
    actual = poff.Neighbourhoods(rows, 3).maximum(values)
    expected = np.array([np.max(values[row]) for row in rows])
    np.testing.assert_allclose(actual, expected, equal_nan=True)


@pytest.mark.parametrize("rows", [[[0], [], [2]], [[0], [3], [2]], [[0], [1.5], [2]]])
def test_invalid_neighbourhood_mapping_fails(rows):
    with pytest.raises(ValueError):
        poff.Neighbourhoods(rows, 3)


class RecordingModel:
    classes_ = np.array([0, 1])
    n_features_in_ = 7
    feature_names = list(poff.FEATURES)

    def __init__(self):
        self.calls = []

    def get_booster(self):
        return self

    def predict_proba(self, frame):
        self.calls.append(frame.copy())
        # A known synthetic response; this is not a scientific model substitute.
        p = frame["tp_prob_1"].to_numpy() / 100
        return np.column_stack([1 - p, p])


def test_probability_units_masks_batching_and_feature_order():
    model = RecordingModel()
    features = {name: np.arange(6, dtype=float) + 10 for name in poff.FEATURES}
    features["swvl"][3] = np.nan
    rain = np.array([1, 0, 1, 1, np.nan, 1])
    land = np.array([1, 1, 0, .2, 1, 1])
    poff.validate_model(model)
    actual = poff.predict_day(model, features, rain, land, 2)
    np.testing.assert_allclose(actual, [10, 0, np.nan, 13, np.nan, 15], equal_nan=True)
    assert [len(frame) for frame in model.calls] == [2, 1]
    assert all(list(frame.columns) == list(poff.FEATURES) for frame in model.calls)
    assert pd.isna(model.calls[0].iloc[1]["swvl"])


def test_wrong_saved_model_feature_order_fails():
    model = RecordingModel()
    model.feature_names = list(reversed(poff.FEATURES))
    with pytest.raises(ValueError, match="feature order"):
        poff.validate_model(model)


def test_model_cannot_emit_invalid_probabilities():
    model = RecordingModel()
    features = {name: np.array([200.]) for name in poff.FEATURES}
    with pytest.raises(ValueError, match="invalid probabilities"):
        poff.predict_day(model, features, np.ones(1), np.ones(1), 1)


@pytest.mark.parametrize("day,expected", [
    (datetime(2020, 2, 28), "202002/20200228_20200229"),
    (datetime(2020, 2, 29), "202002/20200229_20200301"),
    (datetime(2020, 12, 31), "202012/20201231_20210101"),
])
def test_start_end_templates_handle_calendar_boundaries(day, expected):
    path = poff.expand_path("{start:%Y%m}/{start:%Y%m%d}_{end:%Y%m%d}", "", day)
    assert path.as_posix() == expected


def test_date_range_includes_leap_day_and_end_date():
    days = list(poff.date_range(datetime(2020, 2, 28), datetime(2020, 3, 1)))
    assert len(days) == 3 and days[1].day == 29
    with pytest.raises(ValueError):
        list(poff.date_range(days[-1], days[0]))


def test_grib_grid_check_detects_order_changes_and_accepts_wrapped_longitudes():
    class FakeMetview:
        values = staticmethod(lambda field: field["values"])
        latitudes = staticmethod(lambda field: field["lat"])
        longitudes = staticmethod(lambda field: field["lon"])

    reader = object.__new__(poff.GribReader)
    reader.mv = FakeMetview()
    reader.latitude = np.array([50., 40.])
    reader.longitude = np.array([350., 10.])
    reader.npoints = 2
    field = {"values": [1., 2.], "lat": [50., 40.], "lon": [-10., 10.]}
    np.testing.assert_allclose(reader.values(field, "test"), [1, 2])
    field["lat"] = [40., 50.]
    with pytest.raises(ValueError, match="latitude ordering"):
        reader.values(field, "test")


def test_raw_predictors_flow_into_the_model_in_expected_units():
    runner = object.__new__(poff.Runner)
    runner.config = {"percentile_count": 3, "rainfall_scale_to_mm": 1, "batch_size": 2}
    runner.static = {
        "soil_type": np.array([1, 2]), "cover_low": np.array([.2, .4]),
        "cover_high": np.array([.8, .6]), "sdfor": np.array([20., 50.]),
        "land_sea_mask": np.ones(2),
    }
    runner.threshold1 = np.array([10., 10.])
    runner.threshold50 = np.array([20., 20.])
    runner.neighbourhoods = poff.Neighbourhoods([[0, 1], [1]], 2)
    fields = {"swvl1": np.array([.1, .1]), "swvl2": np.array([.2, .2]),
              "swvl3": np.array([.3, .3]), "lai_low": np.array([2., 3.]),
              "lai_high": np.array([4., 5.])}

    class FakeReader:
        single = staticmethod(lambda path: fields[path])

        @staticmethod
        def rainfall(path, count, scale):
            return iter([np.array([0., 10.]), np.array([10., 20.]), np.array([20., 30.])])

    runner.reader = FakeReader()
    runner.model = RecordingModel()
    result = runner.calculate({key: key for key in poff.DAILY_INPUTS})
    np.testing.assert_allclose(result, [200 / 3, 100], rtol=1e-6)
    frame = runner.model.calls[0]
    np.testing.assert_allclose(frame["swvl"], [.265 / .403, .265 / .439])
    np.testing.assert_allclose(frame["lai"], [3.6, 4.2])
    np.testing.assert_allclose(frame["tp_prob_max_1_adj_gb"], [100, 100])
    np.testing.assert_allclose(frame["tp_prob_50"], [100 / 3, 200 / 3])


def test_preflight_rejects_output_collisions_and_input_overwrites(tmp_path):
    asset = tmp_path / "input.grib"
    asset.write_bytes(b"synthetic fixture")
    config = {"root": str(tmp_path), "model": str(asset),
              "inputs": {key: str(asset) for key in poff.STATIC_INPUTS + poff.DAILY_INPUTS},
              "output": "{root}/same-output"}
    days = [datetime(2020, 1, 1), datetime(2020, 1, 2)]
    with pytest.raises(ValueError, match="multiple days"):
        poff.check_input_files(config, days)
    config["output"] = str(asset)
    with pytest.raises(ValueError, match="overwrite an input"):
        poff.check_input_files(config, days[:1])


def test_manifest_rejects_empty_files_and_records_input_changes(tmp_path):
    asset = tmp_path / "field.grib"
    asset.touch()
    with pytest.raises(ValueError, match="non-empty"):
        poff.input_manifest({"test": asset})
    asset.write_bytes(b"first")
    first = poff.input_manifest({"test": asset})
    asset.write_bytes(b"second-longer")
    second = poff.input_manifest({"test": asset})
    assert poff.json_hash(first) != poff.json_hash(second)


def write_fixture(path):
    day = datetime(2020, 2, 29)
    poff.write_output(
        path, day, np.array([0., 12.5, np.nan], dtype=np.float32),
        np.array([45., 46., 47.]), np.array([350., 10., 11.]),
        {"run_sha256": "run1", "input_manifest_sha256": "inputs1"},
    )
    return day


def test_actual_netcdf_roundtrip_dates_units_coordinates_and_missing_values(tmp_path):
    from netCDF4 import Dataset

    path = tmp_path / "poff.nc"
    day = write_fixture(path)
    poff.validate_output(path, day, 3, "run1", "inputs1")
    with Dataset(path) as dataset:
        assert dataset.variables["poff"].units == "%"
        assert dataset.time_coverage_start == "2020-02-29T00:00:00Z"
        assert dataset.time_coverage_end == "2020-03-01T00:00:00Z"
        np.testing.assert_allclose(dataset.variables["longitude"][:], [350, 10, 11])
        values = np.ma.filled(dataset.variables["poff"][:], np.nan)
        np.testing.assert_allclose(values, [[0, 12.5, np.nan]], equal_nan=True)
    assert not list(tmp_path.glob("*.partial"))


@pytest.mark.parametrize("run_hash,input_hash", [("different", "inputs1"), ("run1", "different")])
def test_resume_rejects_different_model_configuration_or_inputs(tmp_path, run_hash, input_hash):
    path = tmp_path / "poff.nc"
    day = write_fixture(path)
    with pytest.raises(ValueError, match="differs"):
        poff.validate_output(path, day, 3, run_hash, input_hash)


def test_corrupt_probability_is_not_hidden_by_netcdf_valid_range_mask(tmp_path):
    from netCDF4 import Dataset

    path = tmp_path / "poff.nc"
    day = write_fixture(path)
    with Dataset(path, "r+") as dataset:
        dataset.variables["poff"][0, 0] = 101
    with pytest.raises(ValueError, match="outside"):
        poff.validate_output(path, day, 3, "run1", "inputs1")


def test_failed_output_validation_preserves_existing_file_and_removes_partial(tmp_path, monkeypatch):
    path = tmp_path / "poff.nc"
    day = write_fixture(path)
    original = path.read_bytes()

    def fail(*args):
        raise ValueError("simulated validation failure")

    monkeypatch.setattr(poff, "validate_output", fail)
    with pytest.raises(ValueError, match="simulated"):
        poff.write_output(path, day, np.zeros(3), np.zeros(3), np.zeros(3),
                          {"run_sha256": "run1", "input_manifest_sha256": "inputs1"}, overwrite=True)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.partial"))


def test_writer_refuses_implicit_overwrite(tmp_path):
    path = tmp_path / "poff.nc"
    write_fixture(path)
    with pytest.raises(FileExistsError):
        write_fixture(path)


def test_multiday_run_resumes_and_continues_after_a_failed_day(tmp_path, monkeypatch):
    from types import SimpleNamespace

    config = {"root": str(tmp_path), "inputs": {"rainfall": "{start:%Y%m%d}"},
              "output": "{root}/poff_{end:%Y%m%d}.nc", "model_label": "synthetic test"}
    days = list(poff.date_range(datetime(2020, 2, 28), datetime(2020, 3, 1)))
    attempted = []
    failures = {"20200229"}

    class FakeRunner:
        def __init__(self, config, first_day):
            self.run_hash, self.model_hash = "run1", "model1"
            self.reader = SimpleNamespace(npoints=2, latitude=np.array([45., 46.]), longitude=np.array([10., 11.]))

        def manifest(self, paths):
            return {"rainfall": str(paths["rainfall"])}

        def calculate(self, paths):
            name = str(paths["rainfall"])
            attempted.append(name)
            if name in failures:
                raise ValueError("simulated daily failure")
            return np.array([0., 12.])

    monkeypatch.setattr(poff, "Runner", FakeRunner)
    assert poff.run(config, days, continue_on_error=True) == 1
    assert len(list(tmp_path.glob("poff_*.nc"))) == 2
    failures.clear()
    attempted.clear()
    assert poff.run(config, days) == 0
    assert attempted == ["20200229"]
    assert len(list(tmp_path.glob("poff_*.nc"))) == 3


def test_generated_output_does_not_disclose_local_paths_or_configuration(tmp_path, monkeypatch):
    from netCDF4 import Dataset
    from types import SimpleNamespace

    day = datetime(2020, 1, 1)
    private_marker = "private-run-location-8139"
    config = {
        "root": str(tmp_path / private_marker), "model_label": "reference model",
        "inputs": {"rainfall": "{root}/rainfall.grib"},
        "output": str(tmp_path / "public.nc"),
        "private_setting": "internal-setting-8139",
        "output_metadata": {
            "license": "https://creativecommons.org/licenses/by/4.0/",
            "creator_name": "Fatima M. Pillosu",
            "creator_url": "https://orcid.org/0000-0001-8127-0990",
            "attribution": "Fatima M. Pillosu / PoFF; Pillosu et al. (2026).",
        },
    }

    class FakeRunner:
        def __init__(self, config, first_day):
            self.run_hash, self.model_hash = "run1", "model1"
            self.reader = SimpleNamespace(
                npoints=2, latitude=np.array([45., 46.]), longitude=np.array([10., 11.]),
            )

        def manifest(self, paths):
            return {"rainfall": {"path": str(paths["rainfall"]), "size_bytes": 1, "mtime_ns": 1}}

        def calculate(self, paths):
            return np.array([0., 12.])

    monkeypatch.setattr(poff, "Runner", FakeRunner)
    assert poff.run(config, [day]) == 0
    with Dataset(tmp_path / "public.nc") as dataset:
        attributes = {name: dataset.getncattr(name) for name in dataset.ncattrs()}
        assert "configuration" not in attributes
        assert "input_manifest" not in attributes
        assert private_marker not in str(attributes)
        assert config["private_setting"] not in str(attributes)
        assert str(tmp_path) not in str(attributes)
        assert len(dataset.input_manifest_sha256) == 64
        assert dataset.references == "https://doi.org/10.5194/egusphere-2026-1591"
        for key, value in config["output_metadata"].items():
            assert dataset.getncattr(key) == value
    assert poff.run(config, [day]) == 0


def test_publication_metadata_cannot_inject_private_configuration_or_run_identity(tmp_path):
    import json
    from pathlib import Path

    config = json.loads(Path(__file__).with_name("poff.example.json").read_text(encoding="utf-8"))
    config["output_metadata"]["configuration"] = "private run settings"
    config["output_metadata"]["run_sha256"] = "replacement identity"
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported fields"):
        poff.load_config(path)
