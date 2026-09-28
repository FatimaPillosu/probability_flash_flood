# PoFF model card

## Purpose

Estimate the probability of at least one flash flood within a native grid box
over a 24-hour period. The standalone driver produces historical estimates
using ERA5 and ERA5-ecPoint predictors. It applies a saved XGBoost classifier
without fitting or updating it.

Scientific reference: [Pillosu et al. (2026), EGUsphere preprint](https://doi.org/10.5194/egusphere-2026-1591).
The [research repository](https://github.com/FatimaPillosu/probability_of_flash_flood)
contains the original experiments; this package's numerical conventions follow
commit `17e1b5f3764c67dbc75d22bf57e7a0fa6f5e7b04`.

## Scientific context

The study relates flash-flood impact reports to rainfall, soil wetness, terrain
and vegetation predictors. Its regional development uses the contiguous United
States (CONUS); the paper also investigates spatial transfer. Results and
limitations should be read in that context. The reference method uses the ERA5
N320 grid, approximately 31 km, and 24-hour periods from 00 UTC to 00 UTC.

The example configuration selects the full-CONUS XGBoost variant labelled
binary cross-entropy (BCE), tuned using ROC-AUC. This label describes the
intended variant; it does not independently authenticate the contents of a
model file. Release metadata must identify the exact bundled estimator.

## Input and output contract

Feature order:

```text
tp_prob_1
tp_prob_max_1_adj_gb
tp_prob_50
tp_prob_max_50_adj_gb
swvl
sdfor
lai
```

The four rainfall probabilities use percent; soil saturation uses a fraction.
Feature calculations and required raw inputs are documented in the
[README](README.md). The classifier must expose `predict_proba`, with class
labels `[0, 1]` and seven input features. Where saved feature names exist, the
driver verifies their order.

The model returns a probability from zero to one for class 1. The script
multiplies it by 100 for output. Dry land is assigned zero outside the model;
ocean and incomplete rainfall inputs are marked missing. Other missing
predictors retain the estimator's own missing-value handling.

## Interpretation

These are model estimates of occurrence, not observed flood records or
predictions of inundation depth. Reporting practices and spatial coverage of
the training labels affect their interpretation. The native grid does not
resolve individual properties or drainage structures. Domain-specific skill
claims should be supported by the corresponding validation in the paper.

The historical driver has no forecast-initialisation or lead-time interface.
Publishing forecasts will require explicit cycle, valid-time and lead-time
handling and validation for the intended forecast inputs.

## Model release record

This code publication does not include the model binary or its public release
record. The model release must record the exact model
filename and SHA-256, model variant, compatible Python/XGBoost/scikit-learn/
joblib versions, training and evaluation periods, and reference-day comparison
results. These values should come from the selected estimator and its training
record rather than being inferred from a filename.

The inference software is licensed under [Apache 2.0](LICENSE). The exact
model artifact's licence and notices will be recorded with the artifact before
publication; this code publication contains no model binary. PoFF data and forecast
products explicitly released under the project's data terms use
[CC BY 4.0](LICENSE-DATA), with [attribution guidance](DATA_ATTRIBUTION.md).

The current loader accepts joblib. For a future portable release, XGBoost also
supports native JSON/UBJSON model files; exporting the same fitted model in its
compatible environment and verifying identical predictions would avoid
retraining. See [XGBoost model IO](https://xgboost.readthedocs.io/en/stable/tutorials/saving_model.html).
