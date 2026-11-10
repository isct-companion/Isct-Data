# Campus map export

[README](../README.md) · [データ仕様と収録範囲](data.md) · [保守コマンド](maintenance.md)

The Isct Companion app draws the Ookayama and Suzukakedai campus maps (buildings, floors, rooms, entrances,
elevators, restrooms, AEDs and lounges) from one file: `campus-map/v1/campus-map.json.gz`, format version 1.
This page is its contract. Schema: [`schema/campus-map-v1.schema.json`](../schema/campus-map-v1.schema.json).
Validator: `scripts/validate_campus_map.py`, run by `scripts/validate_datasets.py` in CI.

## Where the data comes from

The file is built in a private repository of the `isct-companion` organisation, which holds the baseline floor
geometry, the official source files it was refined from (accessibility maps, room tables, evacuation plans),
the maintained correction layer and the tools. That material stays private because the baseline geometry's
provenance and licence are not confirmed. The owner allowed publication of this export on 2026-11-10; only the
finished export is public.

A change arrives here as a pull request that replaces the file and refreshes its index entry. No automated
workflow writes it, and the automated publication paths cannot reach `campus-map/`.

## Index entry

`index.json` has one top-level key beside `academicYears` and `admissionYears`:

```json
"campusMap": { "1": { "source": "campus-map/v1/campus-map.json.gz", "hash": "<sha256 hex of the .gz bytes>", "ts": "<UTC RFC 3339>" } }
```

The key is the format version as a string. The entry has exactly `source`, `hash` and `ts`, like every other
indexed source. Unlike the JSON datasets, whose hash is taken over canonical JSON, `hash` is the SHA-256 of
the gzip file's bytes. `scripts/update_subscription_index.py` writes the hash and timestamp.

## Versioning

A later format gets a new key and a new directory (`campus-map/v2/`); `v1` stays, frozen, for the app releases
that read it. The app reads only its own version key and never reads another format.

## The file

gzip of one UTF-8 JSON object, with deterministic bytes: sorted features, gzip mtime 0, no timestamps inside.
Keys are camelCase. Coordinates are WGS84 `[lng, lat]` with at most 7 decimals. Ids are stable: an id never
changes meaning, and a feature that is gone takes its id with it. The compressed size is about 0.5 MB; the
decompressed JSON stays under 16 MB (16,000,000 bytes).

```json
{
  "formatVersion": 1,
  "attribution": ["© OpenStreetMap contributors (ODbL)"],
  "buildings": [
    {
      "id": "uuid",
      "campus": "ookayama",
      "name": { "ja": "西9号館", "en": "West Bldg. 9" },
      "codes": ["W9"],
      "center": [139.68, 35.60],
      "footprint": [[[[139.68, 35.60], "..."]]],
      "levels": [
        { "id": "uuid", "ordinal": 0, "name": "1F", "outline": [[[[139.68, 35.60], "..."]]] }
      ],
      "entrances": [
        { "id": "uuid", "point": [139.68, 35.60], "name": { "ja": "玄関1" }, "levelId": "uuid" }
      ]
    }
  ],
  "units": [
    { "id": "uuid", "levelId": "uuid", "category": "classroom", "roomId": "uuid", "label": "W9-202",
      "center": [139.68, 35.60], "polygon": [[[139.68, 35.60], "..."]] }
  ],
  "amenities": [
    { "id": "uuid", "levelId": "uuid", "category": "elevator", "point": [139.68, 35.60] }
  ],
  "linework": [
    { "levelId": "uuid", "tone": "wall", "widthM": 0.15, "lines": [[[139.68, 35.60], "..."]] }
  ],
  "rooms": [
    { "id": "uuid", "code": "W9-202", "buildingId": "uuid", "unitIds": ["uuid"] }
  ],
  "aliases": { "W9-202": ["uuid"], "M112": ["uuid", "uuid"] }
}
```

### Field rules

- `buildings`: every building with a footprint. `campus` is `ookayama` or `suzukakedai`. `name.ja` always,
  `name.en` when known. `codes` are the distinct building prefixes of its rooms' codes (the part before the
  last `-`), sorted; may be empty. `footprint` and `outline` are GeoJSON MultiPolygon coordinates. `levels` are
  sorted by `ordinal` ascending (B1 = -1, 1F = 0) and may be empty. `entrances` may be empty: a building whose
  doors are not known has none, and the app falls back to `center`. `entrances[].name` and `levelId` may be `null`.
- `units`: `category` is one of `classroom room corridor elevator_lobby restroom stairs lounge porch`
  (`room` is a room with no known name; `porch` is outdoors). `polygon` is GeoJSON Polygon coordinates (one outer
  ring, then holes). A unit drawn as several parts becomes one unit per part, the later ids suffixed `#2`, `#3`.
  `roomId` links to `rooms[].id` or is `null`. `label` is the room code for a unit with a room, else the unit's
  own name, else `null`.
- `amenities`: `category` is one of `elevator stairs restroom restroom.male restroom.female restroom.wheelchair
  aed lounge lounge.women lounge.international rest_room calm_down study_room`. `restroom` means the gender is not
  confirmed; `restroom.male` and `restroom.female` are confirmed by an official page; `restroom.wheelchair` is a
  multipurpose restroom (多目的トイレ). A fact known only from text, with no position, is not in the file.
- `linework`: the floor's line drawing. `tone` is `wall` for black strokes, `detail` for the gray `#a8a8a8`
  ones. `widthM` is the stroke width in metres (`0` is a hairline). `lines` is MultiLineString coordinates.
- `rooms`: every current room whose building is in `buildings`. `unitIds` may be empty: the room is known to be
  in that building but has no drawn shape yet.
- `aliases`: normalised spelling to room ids, sorted by key. A spelling that fits several rooms lists them all
  (`M112` is M-112 and the old name of MI1-105); the app must not pick one. Every room's own `code` is a key.
  Old room names stay aliases.
- **Alias normalisation**, applied to the keys here and by the app to a room string before lookup: Unicode NFKC,
  then remove every whitespace character, then uppercase.
- Nothing else: no provenance, capacity, equipment or coverage notes, and no `x_` fields.

## Validation

`scripts/validate_campus_map.py` checks, for every `campusMap` entry: the file exists at
`campus-map/v<version>/campus-map.json.gz` and nothing else is in `campus-map/`; `hash` matches the file's bytes;
the decompressed size is under 16,000,000 bytes; the schema, `formatVersion` equal to the key; every `levelId`,
`buildingId`, `roomId`, `unitIds` entry and alias target resolves; a unit's room lists the unit and the other way
round; ids are unique; every coordinate lies in its campus's box and has at most 7 decimals; every ring is closed;
levels are sorted by ordinal, `codes` match the rooms, alias keys are normalised and every room code is an alias.

## Attribution

Building outlines that come from OpenStreetMap are © OpenStreetMap contributors, available under the Open
Database License (ODbL). The `attribution` array lists what the app must show with the map.
