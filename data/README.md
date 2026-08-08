# GB electricity-region boundaries

`gb-electricity-regions.geojson` is an offline WGS84 GeoJSON snapshot of
Northern Powergrid Open Data's **All DNO Licence Area Boundaries** dataset.

* Dataset page: <https://northernpowergrid.opendatasoft.com/explore/dataset/all_dno_boundaries/>
* GeoJSON export: <https://northernpowergrid.opendatasoft.com/api/explore/v2.1/catalog/datasets/all_dno_boundaries/exports/geojson>
* Snapshot obtained: 2026-08-02
* Source properties retained: `longname` (the DNO licence-area name)
* Modifications: exported as WGS84 GeoJSON; no geometry simplification was
  applied. The application maps the retained names to its `_A`–`_P` Octopus
  codes in `src/region_location.py`; it makes no network request at runtime.

Data licence: [Northern Powergrid Open Data Licence v1.0](https://northernpowergrid.opendatasoft.com/p/opendatalicence/).
The complete licence text is bundled in
`NORTHERN_POWERGRID_OPEN_DATA_LICENCE_v1.0.txt` and installed with the app.

Required attribution: “Supported by Northern Powergrid Open Data”

The application source code is licensed under GNU General Public License v3.
The GeoJSON data in this directory remains available under the Northern
Powergrid Open Data Licence v1.0 and is not relicensed under GPLv3. Northern
Powergrid does not endorse this application.
