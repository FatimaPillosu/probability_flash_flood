# Probability of Flash Flood — Atlas

<p><img src="https://raw.githubusercontent.com/FatimaPillosu/probability_flash_flood/main/poff-logo.png" alt="Probability of Flash Flood (PoFF)" width="640"></p>

A static, map-led explorer of the historical PoFF archive. The page shows the
days that `data/manifest.json` lists, on the native grid of the archive: every
day from 1 January 1950 to 31 December 2024, except July 1979. Location
profiles, climatology and data downloads return when their data are published.

## Run locally

From this directory:

```sh
python -m http.server 8765
```

Open http://localhost:8765. No package installation or build is required.
The page must be served: a browser does not read the data from a page opened
as a file. The `data/` directory is published on the `website` branch only;
to preview from `main`, make it with `poff_web.py` or copy it from that branch.

## Files

- `index.html`: semantic page structure and metadata.
- `poff-logo.png`: approved teal logo, shared with the scientific repository.
- `atlas.css`: Atlas layout, responsive styles and appearance.
- `atlas.js`: archive reader, map, place lookup, charts, statistics, state
  persistence and exports.
- `d3.min.js`: locally bundled D3 7.9.0.
- `world.json`: coastlines, country boundaries and lakes from Natural Earth.
- `data/manifest.json`: the published years, their days, encoding and provenance.
- `data/grid.json`: the reduced Gaussian grid of the fields.
- `data/land.bin`: one bit per grid point, set where the archive has values.
- `data/maps/YYYY.bin`: one file per year with, for every day, the points at or
  above 1% and their values, and the land points without a value that day.
  Days are the start of their 24-hour period.
- `.nojekyll`: serves the files directly on GitHub Pages.
- `LICENSE`, `LICENSE-DATA`, `THIRD_PARTY_NOTICES.md`: licensing and attribution.

All URLs are relative, so the site works at a GitHub Pages project URL. The
page requests its own files only. External links open the paper or a Google
search; user selections are stored only in the visitor's browser.

## Implemented experience

- A global map of the daily probability, in the paper's intervals and colours.
- Any day of the archive: date, year and day slider, and a year player.
- Pan by dragging; zoom with the buttons, or with Ctrl or ⌘ and the wheel.
- Place name or latitude/longitude selection, which brings the place into view.
- The value of a grid box after a map click, with the centre of the box.
- Paper-backed skill information, and the credit of the data.
- Google media searches with date-window controls.
- PNG map download, with date, legend and credit.

A year is read as one file of about 3 MB when it is first shown; its days
then change instantly. The location profile, the monthly and annual
climatology and the CSV and NetCDF downloads are in the code but hidden: they
need daily series and a reference period, which the manifest does not list yet.

## The map and the data

The fields are on the ERA5 N320 reduced Gaussian grid, about 31 km. The map
is a plate carrée. Each pixel takes the colour of the grid box that contains
it: values are not interpolated, and the value shown after a click is the
value of that box.

Only values at or above 1%, the lowest interval of the map, are published,
rounded to 0.1 percentage points; below 1% the map is white and a click
reads "< 1%". The full-precision fields are the GRIB archive. Hatched land
has no value in the archive. The field stops at the coastline, so the sea
part of a coastal grid box is not coloured. Lakes are drawn as water where
the archive has no value.

The built-in gazetteer contains a small city list, including two
disambiguated Valencias; it is not a global geocoder. Coordinates work
everywhere.

## Add days to the archive

`poff_web.py`, kept with the ecFlow suite that computes the archive and not
in this repository, converts its GRIB outputs:

```sh
python3 suite/bin/poff_web.py publish --config suite/build/poff.json --site data
python3 suite/bin/poff_web.py check --config suite/build/poff.json --site data --sample 5
```

`publish` checks each GRIB file against its provenance record, writes the
file of each year whose outputs changed, and lists the years in the manifest.
It refuses outputs of another model or run. `check` compares the published
files with the manifest and with the GRIB outputs, all days or a sample per
year. The page needs no change when days or years are added.

The 75 years take about 220 MB. GitHub Pages limits a site to 1 GB.

`world.json` is made from Natural Earth 5.1.2:

```sh
python3 suite/bin/poff_web.py geography --version 5.1.2 \
    --countries ne_50m_admin_0_countries.geojson --lakes ne_50m_lakes.geojson world.json
```

## Test

The tests of the converter are kept with it. The last of them opens the page
in Chrome, selects 240 points through the coordinate form, and compares the
grid box, value, text and colour that the page shows with the GRIB output
read by ecCodes.

## Publication

The `main` branch contains the inference software and the static website source.
GitHub Pages publishes the root of the `website` branch. Merging into `main`
does not deploy changes to the live site.

To publish a website update, commit the reviewed static files listed above to
`website`, retaining that branch's website README and explicit file allowlist.
`data/` is in that branch's allowlist, not in this one: the maps are published
output, not source, and would weigh on every clone of the software. Keep
scientific inputs, credentials and private workflow files out of the
publication branch. The page is marked `noindex` and labelled Preview while
the site is incomplete; remove both when a validated archive is connected.

## Licences

Website code: Apache-2.0. Probability data: CC BY 4.0.
The data are derived from ERA5 and ERA5-ecPoint, and contain modified
Copernicus Climate Change Service information.
Third-party components retain their own terms; see THIRD_PARTY_NOTICES.md.
Research: https://doi.org/10.5194/egusphere-2026-1591.
