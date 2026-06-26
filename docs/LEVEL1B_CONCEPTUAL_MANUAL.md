# Level-1b conceptual manual

## Methodological aim

Level-1b is a raster-only segmentation-quality workflow for UAV orthomosaics. Its purpose is not to produce a final object layer immediately. Its purpose is to determine which candidate segmentation scales are structurally plausible and stable under local perturbation.

The chain separates three questions that are often mixed together:

1. What pixels are valid observations?
2. What feature/proxy space should segmentation see?
3. Which segmentation parameter region is stable enough to consider later?

The final product is therefore not a single segmentation, but a stability evidence space.

## Valid observation support

The first substantive step is the valid observation mask. Background and footprint values must not enter feature construction or segmentation. For RGB orthomosaics the default invalid tuples are:

```text
(0, 0, 0)
(255, 255, 255)
```

This matters because white footprint/background can otherwise form huge artificial regions and dominate segmentation. The valid mask defines the common support for all later raster products.

## Proxy stack

The default RGB proxy stack is five-band:

```text
VIG
DRY
BRI
TEX_100M
TEX_200M
```

The first three bands are color/index style proxies. The last two are texture/support proxies at approximately 1 m and 2 m structural support. Mask gating is applied so invalid footprint pixels do not drive feature or texture statistics.

## Scaling and PCA

Scaling normalizes the proxy feature stack inside valid support. PCA is retained because the segmentation and ranger derivation should operate in a compact feature space rather than raw, differently scaled proxy bands. PCA is not a final interpretation layer. It is an intermediate feature-space construction.

## Step 6: sampling-regime-adaptive scale distribution

Step 6 is the conceptual core of the current repair.

The old placeholder logic treated `structure_derived_scale_distribution` as another manual radius list. That was wrong. The current logic treats candidate generation as two coupled but distinct scales:

1. The structural/proxy support scale represented in the evidence stack.
2. The image sampling scale represented by GSD.

GSD is used to map physical radius into segmentation pixel parameters. GSD does not justify a longest-possible fine-to-coarse scale series.

## Sentinel vs UAV logic

Sentinel-like data are under-resolved for many ecological structures. With 10 m pixels, fine structures are not visible, so the relevant series tends toward the smallest resolvable scales.

UAV data are often over-resolved. At 1–5 cm GSD, leaves, shadows, small texture and homogeneous surfaces can dominate. The problem is not lack of detail; it is too much detail relative to ecological segment objects. Therefore the Level-1b scale logic must restrict the plausible segment-similarity domain.

## Sampling regimes

Step 6 supports:

```text
auto
undersample
balanced
oversample
```

The automatic regime is based on:

```text
structure_support_to_gsd_ratio = effective_structure_support_max_m / pixel_size_m
```

For the current MOF run:

```text
effective_structure_support_max_m = 2.0 m
pixel_size_m ≈ 0.04998 m
ratio ≈ 40
sampling_regime_resolved = oversample
```

Oversample means the image contains many pixels across the structural support. This is typical for UAV imagery and implies that the upper candidate domain must be constrained.

## Patch-derived radii

Step 6 reads structure/proxy evidence, selects texture/structure bands by default, creates evidence masks, computes connected components and converts patch areas to equivalent radii:

```text
area_m2 = n_px * pixel_size_m²
r_eq = sqrt(area_m2 / π)
```

Candidate radii are quantiles of observed patch radii inside the allowed sampling domain. The candidate radius is then mapped to MeanShift-style parameters:

```text
spatialr_px = max(1, round(radius_m / pixel_size_m))
minsize_px  = max(1, round(π * radius_m² / pixel_size_m²))
```

`ranger` is intentionally not assigned in Step 6.

## Texture support envelope

For the default proxy stack, Step 6 selects `TEX_100M` and `TEX_200M` rather than all bands. The largest inferred structure support is therefore 2 m. In oversample mode, the upper envelope is:

```text
upper_envelope_radius_m = effective_structure_support_max_m * oversample_default_upper_radius_factor
```

With factor 2.5:

```text
2.0 m * 2.5 = 5.0 m
```

The 5 m envelope is not a candidate. It is an interpretation and search boundary. Patch-derived candidate radii above that envelope are dropped, not capped. Large homogeneous patches above this envelope are retained only as diagnostics.

## Extreme homogeneous surfaces

A large fresh asphalt surface can appear as a huge homogeneous patch. That does not imply a meaningful ecological segmentation radius of tens of metres. In oversample mode, such patches are counted as above-envelope/extreme homogeneous surfaces and are excluded from candidate generation.

The bundled MOF Step-6 report shows an example: 135 patches above the 5 m envelope and an `extreme_homogeneous_patch_flag=true`. The largest patch radius was about 75 m, but the largest emitted candidate radius was about 3.87 m.

## Step 7: feature-space ranger

`ranger` is not a manual grid and not derived from spatial radius. Step 7 samples valid complete feature vectors from the feature-space stack and derives distance-scale candidates from k-nearest-neighbor distances. The candidates are assigned to Step-6 spatial candidates in ordered fashion with tail padding.

Conceptually:

```text
feature vectors inside valid support
→ deterministic sample
→ kNN distances in feature space
→ distance quantiles
→ ranger candidates
→ ordered assignment to scale candidates
```

This separates spatial support (`spatialr_px`, `minsize_px`) from feature-space similarity (`ranger`).

## Step 8: local perturbations

Step 8 creates local parameter perturbations around each coupled Step-6/Step-7 candidate. It does not create a global parameter matrix. For each source candidate it keeps a baseline and adds local perturbations in `spatialr_px`, `minsize_px` and `ranger`.

The implemented R-style logic uses adaptive deltas:

```text
dr = max(0.005, 0.10 * ranger)
dm = max(5, round(0.20 * minsize))
ds = 1, except ds = 0 for very small spatialr
```

A deterministic sample of perturbations is used if the local grid is too large.

## Step 9: candidate stability

Step 9 consumes all Step-8 perturbation candidates. For every candidate group it runs the baseline segmentation, then each local perturbation segmentation, and compares each perturbation result against its own baseline using Hoover comparison on raster labels.

The stability logic is deliberately raster-only. It does not vectorize, does not select a final scale, and does not create final objects. It only creates evidence for which candidate regions are stable.

## What Level-1b does not do

Level-1b does not yet:

- select `selected_scale_id`
- perform stable-region interpretation as a final decision
- produce final label rasters for the selected scale
- vectorize segments
- write GPKG or shapefile final products
- run zonal statistics

Those belong after the Level-1b stability evidence is interpreted.
