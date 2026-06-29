args <- commandArgs(trailingOnly = TRUE)

selected_segments_gpkg <- args[[1]]
value_raster_path <- args[[2]]
valid_mask_path <- args[[3]]
stats_csv <- args[[4]]
summary_json <- args[[5]]
selected_candidate_id <- args[[6]]
selected_source <- args[[7]]
selected_representative_id <- args[[8]]

selected_segments <- sf::st_read(
  selected_segments_gpkg,
  layer = "selected_segments",
  quiet = TRUE
)
value_raster <- terra::rast(value_raster_path)

raster_names <- names(value_raster)
names_unsuitable <-
  length(raster_names) != terra::nlyr(value_raster) ||
  any(is.na(raster_names)) ||
  any(!nzchar(raster_names)) ||
  anyDuplicated(raster_names) > 0L ||
  any(make.names(raster_names, unique = FALSE) != raster_names) ||
  any(grepl("^lyr\\.?[0-9]+$", raster_names))
if (names_unsuitable) {
  names(value_raster) <- sprintf("band_%03d", seq_len(terra::nlyr(value_raster)))
}

extracted_stats <- exactextractr::exact_extract(
  value_raster,
  selected_segments,
  fun = c(
    "count",
    "mean",
    "median",
    "min",
    "max",
    "stdev",
    "variance",
    "quantile"
  ),
  quantiles = c(0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95),
  append_cols = "segment_id",
  force_df = TRUE,
  progress = FALSE
)

statistic_columns <- setdiff(names(extracted_stats), "segment_id")
output_table <- data.frame(
  segment_id = extracted_stats[["segment_id"]],
  selected_candidate_id = rep(selected_candidate_id, nrow(extracted_stats)),
  selected_source = rep(selected_source, nrow(extracted_stats)),
  selected_representative_id = rep(
    selected_representative_id,
    nrow(extracted_stats)
  ),
  extracted_stats[statistic_columns],
  check.names = FALSE
)
utils::write.csv(output_table, stats_csv, row.names = FALSE, na = "")

provenance_columns <- c(
  "segment_id",
  "selected_candidate_id",
  "selected_source",
  "selected_representative_id"
)
numeric_statistic_columns <- names(output_table)[
  vapply(output_table, is.numeric, logical(1)) &
    !(names(output_table) %in% provenance_columns)
]
numeric_column_summary <- lapply(
  numeric_statistic_columns,
  function(column_name) {
    values <- output_table[[column_name]]
    values <- values[!is.na(values)]
    list(
      n_non_na = length(values),
      mean = if (length(values) > 0L) mean(values) else NA_real_,
      median = if (length(values) > 0L) stats::median(values) else NA_real_,
      min = if (length(values) > 0L) min(values) else NA_real_,
      max = if (length(values) > 0L) max(values) else NA_real_
    )
  }
)
names(numeric_column_summary) <- numeric_statistic_columns

summary_object <- list(
  status = "step10_part5_exactextractr_segment_stats_ready",
  selected_candidate_id = selected_candidate_id,
  selected_source = selected_source,
  selected_representative_id = selected_representative_id,
  input_selected_segments_gpkg = selected_segments_gpkg,
  input_value_raster = value_raster_path,
  input_valid_mask = valid_mask_path,
  stats_csv = stats_csv,
  segment_count = nrow(output_table),
  band_count = terra::nlyr(value_raster),
  stats_column_count = length(numeric_statistic_columns),
  stats_columns = numeric_statistic_columns,
  summary_fields_present = c("n_non_na", "mean", "median", "min", "max"),
  numeric_column_summary = numeric_column_summary
)
jsonlite::write_json(
  summary_object,
  summary_json,
  pretty = TRUE,
  auto_unbox = TRUE,
  na = "null"
)
