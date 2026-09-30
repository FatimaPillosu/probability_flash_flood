<p>
  <a href="https://fatimapillosu.github.io/probability_flash_flood/">
    <img src="https://raw.githubusercontent.com/FatimaPillosu/probability_flash_flood/main/poff-logo.png" alt="Probability of Flash Flood (PoFF)" width="640">
  </a>
</p>

# Probability of Flash Flood (PoFF)

Daily, ERA5-based estimates of flash-flood occurrence using a trained XGBoost model.

PoFF estimates the probability of **at least one flash flood within a grid box over a 24-hour period**. This repository provides a standalone Python inference script that calculates seven predictors from ERA5 and ERA5-ecPoint inputs, applies a saved model, and writes daily NetCDF files.

The method is described in [Pillosu et al. (2026), *Outrunning flash floods*](https://doi.org/10.5194/egusphere-2026-1591), currently available as an EGUsphere preprint. The [model card](MODEL_CARD.md) describes the prediction target and model interface.

> **Scope:** this implementation generates historical daily estimates from prepared input files. It does not retrieve or downscale rainfall, train the model, or implement a forecast-cycle interface. Dataset and forecast downloads are not yet published through this repository.

## Website

[Open the Atlas historical archive](https://fatimapillosu.github.io/probability_flash_flood/) to explore maps of the archive: every day from 1950 to 2024, on the native grid. Location profiles and data downloads return when their data are published.

The `main` branch contains both the inference software and the static website source. GitHub Pages publishes the root of the `website` branch. See the [website guide](WEBSITE.md) for local preview, data integration and publication instructions.

## What the probability represents

The output is an occurrence probability in percent, from 0 to 100, for each native input grid box and day. It is not a prediction of water depth, discharge, inundation extent or an individual property's flood probability. The method uses the ERA5 N320 grid, approximately 31 km; the script preserves the input grid and point order.

The seven model inputs, in their required order, are:

| Predictor | Description | Units |
| --- | --- | --- |
| `tp_prob_1` | Probability that 24-hour rainfall meets or exceeds its 1-year return level | % |
| `tp_prob_max_1_adj_gb` | Maximum of that probability over the supplied neighbourhood | % |
| `tp_prob_50` | Probability that 24-hour rainfall meets or exceeds its 50-year return level | % |
| `tp_prob_max_50_adj_gb` | Maximum of that probability over the supplied neighbourhood | % |
| `swvl` | Soil saturation integrated over the upper metre | Fraction |
| `sdfor` | Standard deviation of filtered sub-grid orography | m |
| `lai` | Leaf area index weighted by low/high vegetation cover | m²/m² |

Rainfall exceedance probabilities are calculated from the 1st–99th ERA5-ecPoint percentiles as `100 × count(rainfall >= return level) / 99`. Soil saturation uses layer weights `0.07`, `0.21` and `0.72`, normalisation by soil-type maximum saturation, and an upper bound of one. Vegetation weighting is `lai_low × cover_low + lai_high × cover_high`.

## Requirements

- Python 3.10 or newer on Linux.
- A native [Metview installation](https://metview.readthedocs.io/en/latest/) and its Python interface.
- The packages in [requirements.txt](requirements.txt).
- The trained classifier and the input fields described below.

Use Python, XGBoost, scikit-learn and joblib versions compatible with the saved classifier. The dependency list is not a tested, model-specific environment lock.

Clone the repository, then install the Python packages within that compatible environment:

```bash
git clone https://github.com/FatimaPillosu/probability_flash_flood.git
cd probability_flash_flood
python -m pip install -r requirements.txt
```

Installing the Python `metview` package alone does not install native Metview. Load only trusted model and NumPy mapping files: the current joblib and object-array formats can execute Python code when loaded.

## Configure the inputs

Copy the portable example and edit it for your files:

```bash
cp poff.example.json poff.json
```

`root` defaults to the current working directory. All example paths are illustrative; they may be replaced by your own paths. The model path defaults to `model.joblib`. Keep `model_label` consistent with the selected model, using a public description suitable for inclusion in output metadata.

| Configuration key | Required input |
| --- | --- |
| `model` | Saved XGBoost classifier with the seven-feature interface above |
| `rainfall` | 99 ERA5-ecPoint 24-hour rainfall percentile GRIB fields, 1st through 99th |
| `climatology` | Rainfall return-level GRIB fields from the reference climatology used by the model |
| `return_periods` | NumPy array of return periods, in years, matching the climatology field order; must include 1 and 50 |
| `neighbourhoods` | NumPy mapping with one array of zero-based grid indices per grid point |
| `swvl1`, `swvl2`, `swvl3` | ERA5 volumetric soil water in layers 1–3, in m³/m³, at the start of the day |
| `soil_type` | ERA5 soil-type codes, used to select maximum saturation |
| `sdfor` | Standard deviation of filtered sub-grid orography |
| `land_sea_mask` | Land-sea mask; values greater than zero are treated as land |
| `cover_low`, `cover_high` | Low/high vegetation cover fractions |
| `lai_low`, `lai_high` | Daily climatological low/high vegetation LAI |

Keys other than `model` are inside the configuration's `inputs` object. The rainfall return levels follow the 1991–2020 reference climatology of the research workflow. Plain deterministic ERA5 rainfall is not a substitute for the 99 ERA5-ecPoint percentile fields expected here.

All GRIB inputs must have the same grid and point order. Each soil, vegetation and other static GRIB input contains one field; rainfall and return-level climatology are the multi-field exceptions. The script checks coordinates and does not interpolate. Use the neighbourhood mapping associated with this grid.

Set `rainfall_scale_to_mm` and `climatology_scale_to_mm` to `1` for inputs already in millimetres, or `1000` for inputs in metres. The script uses these explicit conversion settings.

Path templates support `{root}`, `{start:%Y%m%d}` and `{end:%Y%m%d}`, with normal Python date formatting:

- `start` is the beginning of the 24-hour period, at 00 UTC.
- `end` is 00 UTC on the following day.
- Rainfall and soil inputs use the start date. Daily climatological LAI uses the end calendar day, following the research inference convention.

## Run

Check input-file availability without loading the model or creating output:

```bash
python poff.py --config poff.json \
  --start 2020-01-01 --end 2020-12-31 --check-inputs
```

Process a single day:

```bash
python poff.py --config poff.json \
  --start 2020-01-01 --end 2020-01-01
```

Process a year and save a local log:

```bash
python poff.py --config poff.json \
  --start 2020-01-01 --end 2020-12-31 \
  --log-file poff-2020.log
```

Both command-line dates are **inclusive accumulation-start dates**. For example, `--start 2020-12-31 --end 2020-12-31` processes 31 December 00 UTC to 1 January 00 UTC. The example configuration names its output `outputs/2021/poff_20210101_00.nc`.

The script loads the model and static inputs once per invocation, streams the rainfall percentiles, and batches predictions. Set `threads` to the CPU allocation and `batch_size` to suit available memory.

Rerunning the same command verifies and skips matching completed outputs. Changes to the code, model, configuration or recorded input-file identities require a new output destination or explicit `--overwrite`. A failed day stops execution by default. `--continue-on-error` processes later days and still returns a non-zero exit status if any day fails.

## Output

Each NetCDF file contains:

- `poff(time, point)`: probability in percent, stored as 32-bit floating point.
- `latitude(point)` and `longitude(point)`: coordinates in native input order.
- `time`: the end of the accumulation period, with explicit 24-hour `time_bounds`.
- Model, run and input-manifest SHA-256 identifiers, the feature order and scientific reference.
- Public licence and creator attribution supplied in `output_metadata`.

Land points with zero rainfall in every percentile are assigned zero. Ocean points and points missing any rainfall percentile are missing. Missing values in other predictors are passed to the model's learned missing-value handling.

Local configuration contents and input paths are not embedded in the output. The input-manifest hash uses file paths, sizes and modification times internally; it is not a checksum of every GRIB file. Logs remain local and can contain file paths.

The example's `output_metadata` identifies PoFF, its creator and the CC BY 4.0 data licence. These four optional fields (`license`, `creator_name`, `creator_url`, `attribution`) are published verbatim. Keep them suitable for public distribution. If producing a different data product, edit or omit this object to reflect its own rights and attribution; the software does not automatically license third-party outputs.

Files are written to a temporary location and read back before publication. Default publication requires a filesystem supporting hard links. Assign distinct date ranges or output locations to simultaneous processes.

## Verification

The numerical and file-handling tests use synthetic inputs and do not require Metview or the trained classifier:

```bash
python -m pip install pytest
python -B -m pytest -q -p no:cacheprovider test_poff.py
```

They cover predictor calculations, feature order, missing values, calendar boundaries, NetCDF round trips, restart behaviour and output metadata privacy. The input checks validate file availability, field counts and grid coordinates; they do not independently verify rainfall percentile identifiers or temporal GRIB metadata. A model-release validation should compare predictors and probabilities for a reference day against the research implementation.

## Citation

Please cite the method when using the software, trained model or resulting estimates:

Pillosu, F. M., Claire, M., Baugh, C., Pappenberger, F., Prudhome, C., and Cloke, H. L. (2026). *Outrunning flash floods: XGBoost and sparse impact reports deliver global medium-range probabilistic forecasts of flash flood occurrence*. EGUsphere [preprint]. [doi:10.5194/egusphere-2026-1591](https://doi.org/10.5194/egusphere-2026-1591).

Machine-readable citation metadata is provided in [CITATION.cff](CITATION.cff). Also record the exact software release or commit and model SHA-256 used in an analysis. When using a published dataset, cite its own version-specific record as well as the method. No software or dataset DOI has yet been assigned in this package.

## Licence

Copyright 2026 Fatima M. Pillosu.

| Material | Licence |
| --- | --- |
| Python code, tests, example configuration and software documentation | [Apache License 2.0](LICENSE), with attribution in [NOTICE](NOTICE) |
| PoFF historical datasets and forecast products explicitly published under these data terms | [Creative Commons Attribution 4.0 International (CC BY 4.0)](LICENSE-DATA) |

These licences support research, humanitarian and commercial reuse. No individual permission is required for uses permitted by the licences. When redistributing the software, follow Apache 2.0's licence, notice and modification requirements. When sharing the data, retain the required attribution, provide licence information and identify changes. See [data attribution guidance](DATA_ATTRIBUTION.md) for a suggested credit line.

Please cite the paper and the relevant dataset release in scientific work. This is a scholarly request, not an extra restriction on either licence. Third-party software, input data and previously published material retain their respective terms. These licences do not imply endorsement of downstream products.

## Release status

This initial code publication contains the inference script, example configuration, tests and documentation. It does not include the trained model binary. The model release will identify the exact artifact, its checksum, compatible environment versions and reference-day validation results.
