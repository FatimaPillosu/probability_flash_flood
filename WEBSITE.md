# Probability of Flash Flood — Atlas

<p><img src="https://raw.githubusercontent.com/FatimaPillosu/probability_flash_flood/main/poff-logo.png" alt="Probability of Flash Flood (PoFF)" width="640"></p>

A static, map-led archive explorer for PoFF. This first release uses a
deterministic synthetic dataset to demonstrate the interface. It is not model
output or observed historical flood occurrence. The interface uses a discreet
Demonstration notice; downloaded files retain demonstration provenance.

## Run locally

From this directory:

```sh
python -m http.server 8765
```

Open http://localhost:8765. No package installation or build is required.

## Files

- `index.html`: semantic page structure and metadata.
- `poff-logo.png`: approved teal logo, shared with the scientific repository.
- `atlas.css`: Atlas layout, responsive styles and appearance.
- `atlas.js`: data generation, map projection, place lookup, charts, statistics,
  context overlays, state persistence and exports.
- `d3.min.js`: locally bundled D3 7.9.0.
- `.nojekyll`: serves the files directly on GitHub Pages.
- `LICENSE`, `LICENSE-DATA`, `THIRD_PARTY_NOTICES.md`: licensing and attribution.

All asset URLs are relative, so the site works at a GitHub Pages project URL.
It makes no data-service requests. External links open the paper or a Google
search; user selections are stored only in the visitor's browser.

## Implemented experience

- Daily probability maps and a year player for 2018–2020.
- Monthly and annual reference maps for 1991–2020.
- Name suggestions with region/country; latitude/longitude selection.
- Map values shown only after a map click.
- Requested point and sampled grid centre, daily series, thresholds,
  monthly/year means, peaks, exceedance counts, coverage and anomalies.
- Paper-backed skill information and selected-data quality.
- Google media searches with date-window controls.
- Demonstration population, settlement, infrastructure and economic overlays.
- PNG map, daily CSV/NetCDF and annual/monthly statistics CSV downloads.

The reference averages all calendar days across thirty separately generated
years, rather than relabelling a single-year average. Anomalies are percentage
point differences. Missing coverage is distinct from a zero probability.

## Scope of the data

Probability coverage is an illustrative 0.25-degree Iberian grid. The built-in
gazetteer contains a small city list, including two disambiguated Valencias;
it is not a global geocoder. The exposure overlays are generated interface
examples, not GHSL, OSM or measured GDP data. Asset positions are illustrative
and must not be used to locate actual facilities. The skill panel reports the
paper's evidence without inventing numerical verification curves.

## Connect production data

Replace the generated `cells` and calendar series in `atlas.js` with a versioned
catalogue/data adapter. Preserve native grid identifiers and requested/sampled
coordinates. Deliver map tiles separately from numerical point series; never
infer values from map colours. Keep the probability palette and documented UTC
accumulation bounds. Supply real baseline coverage, missing-value masks,
provenance and verification tables. Replace the small gazetteer and generated
context overlays with appropriately licensed sources.

Full global archives should be served from separate HTTPS storage. GitHub Pages
hosts the interface. Arbitrary large NetCDF subsets would need prepared chunks
or an external service; selected-point exports can be made in the browser.

## Publication

The `main` branch contains the inference software and the static website source.
GitHub Pages publishes the root of the `website` branch. Merging into `main`
does not deploy changes to the live site.

To publish a website update, commit the reviewed static files listed above to
`website`, retaining that branch's website README and explicit file allowlist.
Keep scientific inputs, credentials and private workflow files out of the
publication branch. The page is marked `noindex` while it remains a
demonstration; remove that tag when a validated production archive is connected.

## Licences

Website code: Apache-2.0. Generated demonstration data: CC BY 4.0.
Third-party components retain their own terms; see THIRD_PARTY_NOTICES.md.
Research: https://doi.org/10.5194/egusphere-2026-1591.
