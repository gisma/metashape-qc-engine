# Extract a Balanced Geotagged UAV Image Grid

## Purpose

`scripts/extract_geotagged_image_chunk.py` creates a balanced block of geotagged UAV images around one EPSG:4326 coordinate. The result is an ordinary image directory usable by Metashape, ODM, or another photogrammetry workflow.

The tool does not run photogrammetry or inspect image content. It reconstructs acquisition missions, battery sorties, and flight lines from numeric DJI EXIF/XMP metadata read by ExifTool.

## Why the selection uses a grid

Selecting exactly 50 nearest camera centres does not guarantee a useful photogrammetric core. A complete rectangular factorization of 50 is typically 5×10, which leaves a long block and a narrow interior after outer rows and columns are treated as edge support.

The active selection contract therefore uses explicit flight-grid dimensions. The recommended approximately 50-image block is:

```text
7 flight lines × 7 images per line = 49 images
```

## Required metadata

Every selectable image must provide:

- `GPSLatitude`
- `GPSLongitude`
- `DateTimeOriginal`
- `FlightYawDegree`

`GPSAltitude` is recorded when available but is not required for line detection.

ExifTool must be available:

```bash
exiftool -ver
```

The input directory is searched recursively for:

```text
jpg, jpeg, tif, tiff, dng
```

Images missing required metadata are excluded and listed in `extraction_report.json`. There is no filename or image-content fallback.

## Selection method

1. Read all supported files recursively with one ExifTool call.
2. Sort images by `DateTimeOriginal`.
3. Split temporally separate acquisition missions using `--mission-gap-seconds`.
4. Within a mission, record battery sorties using `--sortie-gap-seconds`.
5. Estimate the reciprocal flight axis from `FlightYawDegree`; headings 0° and 180° represent one axis.
6. Convert WGS84 coordinates to local east/north metres around the target.
7. Project positions into along-track and cross-track coordinates.
8. Detect chronological flight lines from axis-consistent yaw, direction reversals, and capture gaps.
9. For each line, choose the centered consecutive image window requested by `--images-per-line`.
10. Choose the centered consecutive block requested by `--grid-lines`.
11. Copy the complete grid and record the mission, sortie, source-line, and grid positions.

Battery changes do not automatically imply different acquisition missions. Adjacent sorties can contribute different lines to one block when they belong to the same temporally connected mission. The sortie index remains explicit for every selected image.

## Command

Run from the repository root:

```bash
python scripts/extract_geotagged_image_chunk.py \
  --image-dir /home/creu/passport/MOF/MOF/07-Juni-2024/rgb \
  --lat 50.84095 \
  --lon 8.67705 \
  --grid-lines 7 \
  --images-per-line 7 \
  --sortie-gap-seconds 300 \
  --mission-gap-seconds 3600 \
  --max-distance-m 500 \
  --out-dir /home/creu/tmp/sensi-img/8_67705_50_84095_grid7x7
```

Latitude precedes longitude. Coordinates must be decimal degrees in EPSG:4326.

## Arguments

| Argument | Meaning |
|---|---|
| `--image-dir` | Directory searched recursively |
| `--lat`, `--lon` | Target coordinate in EPSG:4326 |
| `--grid-lines` | Number of cross-track flight lines |
| `--images-per-line` | Consecutive centered images selected on each line |
| `--out-dir` | New or empty output directory |
| `--sortie-gap-seconds` | Time gap identifying battery/sortie boundaries; default 300 s |
| `--mission-gap-seconds` | Larger gap separating acquisition missions; default 3600 s |
| `--line-yaw-tolerance-deg` | Allowed yaw deviation from the dominant flight axis; default 20° |
| `--max-distance-m` | Optional radial eligibility limit around the target |
| `--exiftool` | ExifTool executable name or path |

`mission_gap_seconds` must exceed `sortie_gap_seconds`.

## Output

```text
<out-dir>/
├── images/
│   ├── L01_I01_<original-name>
│   ├── L01_I02_<original-name>
│   ├── ...
│   └── L07_I07_<original-name>
├── selected_images.csv
└── extraction_report.json
```

Images are copied with `shutil.copy2()`. The prefix identifies output line and image position while preserving the original filename and metadata.

### `selected_images.csv`

Important fields are:

- `grid_line_rank`
- `image_rank_on_line`
- `source_sortie_index`
- `source_line_index`
- source and copied paths
- capture time and flight yaw
- latitude, longitude, altitude
- east/north and along-/cross-track coordinates
- radial distance to the requested centre

### `extraction_report.json`

The report includes:

- selected 7×7 grid dimensions and image count;
- selected mission time range;
- sortie indices contributing to the block;
- estimated flight-axis bearing;
- detected and eligible line counts;
- along- and cross-track block-centre offsets;
- farthest selected camera distance;
- excluded files and metadata reasons;
- all input/output paths and method parameters.

Inspect the result:

```bash
OUT=/home/creu/tmp/sensi-img/8_67705_50_84095_grid7x7
jq . "$OUT/extraction_report.json"
column -s, -t < "$OUT/selected_images.csv" | less -S
find "$OUT/images" -maxdepth 1 -type f | wc -l
```

The last command should return `49` for a 7×7 block.

## Failure behavior

The command exits nonzero when:

- ExifTool is unavailable;
- required metadata are absent from too many images;
- no acquisition mission contains the requested complete grid;
- fewer than the requested images exist on enough lines within `max_distance_m`;
- mission/sortie gap parameters are inconsistent;
- the output directory is nonempty;
- ExifTool or file copying fails.

The tool does not fill an incomplete line with images from an unrelated mission.

## Use in the sensitivity study

Set the generated `images/` directory as `level1a.image_dir` in a copy of the sensitivity YAML. Assign each spatial chunk a separate study ID, product ID, and output root:

```yaml
study:
  id: "mof_8_67705_50_84095"
  output_root: "/home/creu/tmp/level1ab_sensitivity/mof_8_67705_50_84095"

level1a:
  image_dir: "/home/creu/tmp/sensi-img/8_67705_50_84095_grid7x7/images"
  product_id: "mof_8_67705_50_84095"
```

Then run:

```bash
bash scripts/run_level1ab_sensitivity.sh /path/to/study.yaml plan
bash scripts/run_level1ab_sensitivity.sh /path/to/study.yaml all
```

The current meta-runner accepts one image directory per YAML. Use one YAML and output root per spatial chunk.

## Interpretation boundary

A balanced 7×7 camera grid provides a more symmetric interior than a 5×10 or irregular nearest-image subset. It does not guarantee successful alignment, uniform ground footprint, or independent observations. Level-1A must still verify alignment, support, and orthomosaic edges.

Chunks from one mission are spatial subsamples, not independent flights. Nearby chunks can share images; overlap must be recorded when estimating uncertainty across chunks.
