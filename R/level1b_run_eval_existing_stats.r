#!/usr/bin/env Rscript

required_packages <- c("readr", "dplyr", "tidyr", "ggplot2")
missing_packages <- required_packages[!vapply(required_packages, requireNamespace, logical(1), quietly = TRUE)]
if (length(missing_packages) > 0) {
  stop("Missing required R package(s): ", paste(missing_packages, collapse = ", "), call. = FALSE)
}

suppressPackageStartupMessages({
  library(readr)
  library(dplyr)
  library(tidyr)
  library(ggplot2)
})

fail <- function(...) stop(paste0(...), call. = FALSE)

require_env <- function(name) {
  value <- Sys.getenv(name)
  if (!nzchar(value)) fail("Required environment variable is not set: ", name)
  normalizePath(value, mustWork = FALSE)
}

assert_file <- function(path) {
  if (!file.exists(path)) fail("Required input file does not exist: ", path)
  if (file.info(path)$isdir) fail("Required input is a directory, not a file: ", path)
  invisible(path)
}

assert_dir <- function(path) {
  if (!dir.exists(path)) fail("Required directory does not exist: ", path)
  invisible(path)
}

assert_cols <- function(data, required, label) {
  missing <- setdiff(required, names(data))
  if (length(missing) > 0) {
    fail(label, " is missing required column(s): ", paste(missing, collapse = ", "))
  }
  invisible(data)
}

assert_nonempty <- function(data, label) {
  if (nrow(data) == 0) fail(label, " has zero rows.")
  invisible(data)
}

assert_numeric_cols <- function(data, cols, label) {
  for (col in cols) {
    if (!is.numeric(data[[col]])) fail(label, " column is not numeric: ", col)
    if (any(is.na(data[[col]]))) fail(label, " column contains NA: ", col)
  }
  invisible(data)
}

assert_character_cols <- function(data, cols, label) {
  for (col in cols) {
    if (!is.character(data[[col]])) fail(label, " column is not character: ", col)
    if (any(is.na(data[[col]]) | !nzchar(data[[col]]))) fail(label, " column contains empty/NA values: ", col)
  }
  invisible(data)
}

out_root <- require_env("OUT")
eval_dir <- require_env("EVAL")

assert_dir(out_root)
dir.create(eval_dir, recursive = TRUE, showWarnings = FALSE)
assert_dir(eval_dir)

stats_dir <- file.path(out_root, "level1b", "candidate_response_surface")
assert_dir(stats_dir)

input_files <- tibble::tibble(
  input_name = c(
    "run_population_summary",
    "candidate_group_response_summary",
    "ranked_candidate_scales"
  ),
  path = c(
    file.path(stats_dir, "run_population_summary.csv"),
    file.path(stats_dir, "candidate_group_response_summary.csv"),
    file.path(stats_dir, "ranked_candidate_scales.csv")
  )
)

invisible(lapply(input_files$path, assert_file))

run_population <- readr::read_csv(input_files$path[input_files$input_name == "run_population_summary"], show_col_types = FALSE)
candidate_group <- readr::read_csv(input_files$path[input_files$input_name == "candidate_group_response_summary"], show_col_types = FALSE)
ranked_candidates <- readr::read_csv(input_files$path[input_files$input_name == "ranked_candidate_scales"], show_col_types = FALSE)

assert_nonempty(run_population, "run_population_summary.csv")
assert_nonempty(candidate_group, "candidate_group_response_summary.csv")
assert_nonempty(ranked_candidates, "ranked_candidate_scales.csv")

run_required <- c(
  "run_id",
  "candidate_scale_group_id",
  "source_candidate_radius_m",
  "segment_count",
  "segment_density_per_ha",
  "total_labelled_area_m2",
  "area_weighted_q_median",
  "area_weighted_q_q10",
  "area_weighted_q_q90",
  "central_area_share",
  "lower_tail_area_share",
  "upper_tail_area_share",
  "edge_loaded_area_share"
)

group_required <- c(
  "candidate_scale_group_id",
  "run_count",
  "response_center_q",
  "response_spread_q",
  "central_area_share_mean",
  "lower_tail_area_share_mean",
  "upper_tail_area_share_mean",
  "distribution_flutter_score",
  "scale_jump_flag",
  "stability_score",
  "candidate_outcome",
  "medoid_run_id"
)

ranked_required <- c(
  "candidate_scale_group_id",
  "run_count",
  "response_center_q",
  "response_spread_q",
  "central_area_share_mean",
  "lower_tail_area_share_mean",
  "upper_tail_area_share_mean",
  "distribution_flutter_score",
  "scale_jump_flag",
  "stability_score",
  "candidate_outcome",
  "medoid_run_id"
)

assert_cols(run_population, run_required, "run_population_summary.csv")
assert_cols(candidate_group, group_required, "candidate_group_response_summary.csv")
assert_cols(ranked_candidates, ranked_required, "ranked_candidate_scales.csv")

assert_character_cols(run_population, c("run_id", "candidate_scale_group_id"), "run_population_summary.csv")
assert_character_cols(candidate_group, c("candidate_scale_group_id", "candidate_outcome", "medoid_run_id"), "candidate_group_response_summary.csv")
assert_character_cols(ranked_candidates, c("candidate_scale_group_id", "candidate_outcome", "medoid_run_id"), "ranked_candidate_scales.csv")

assert_numeric_cols(
  run_population,
  c(
    "source_candidate_radius_m",
    "segment_count",
    "segment_density_per_ha",
    "total_labelled_area_m2",
    "area_weighted_q_median",
    "area_weighted_q_q10",
    "area_weighted_q_q90",
    "central_area_share",
    "lower_tail_area_share",
    "upper_tail_area_share",
    "edge_loaded_area_share"
  ),
  "run_population_summary.csv"
)

assert_numeric_cols(
  candidate_group,
  c(
    "run_count",
    "response_center_q",
    "response_spread_q",
    "central_area_share_mean",
    "lower_tail_area_share_mean",
    "upper_tail_area_share_mean",
    "distribution_flutter_score",
    "stability_score"
  ),
  "candidate_group_response_summary.csv"
)

assert_numeric_cols(
  ranked_candidates,
  c(
    "run_count",
    "response_center_q",
    "response_spread_q",
    "central_area_share_mean",
    "lower_tail_area_share_mean",
    "upper_tail_area_share_mean",
    "distribution_flutter_score",
    "stability_score"
  ),
  "ranked_candidate_scales.csv"
)

rank_levels <- ranked_candidates$candidate_scale_group_id
if (anyDuplicated(rank_levels)) fail("ranked_candidate_scales.csv contains duplicate candidate_scale_group_id values.")
plot_rank_levels <- rev(rank_levels)

unknown_run_groups <- setdiff(unique(run_population$candidate_scale_group_id), rank_levels)
unknown_group_groups <- setdiff(unique(candidate_group$candidate_scale_group_id), rank_levels)
if (length(unknown_run_groups) > 0) fail("run_population_summary.csv contains group IDs not present in ranked_candidate_scales.csv: ", paste(unknown_run_groups, collapse = ", "))
if (length(unknown_group_groups) > 0) fail("candidate_group_response_summary.csv contains group IDs not present in ranked_candidate_scales.csv: ", paste(unknown_group_groups, collapse = ", "))

input_manifest <- input_files |>
  mutate(
    exists = file.exists(path),
    bytes = file.info(path)$size,
    n_rows = c(nrow(run_population), nrow(candidate_group), nrow(ranked_candidates)),
    n_columns = c(ncol(run_population), ncol(candidate_group), ncol(ranked_candidates))
  )

readr::write_csv(input_manifest, file.path(eval_dir, "00_existing_stats_input_manifest.csv"))

ranked_candidates <- ranked_candidates |>
  mutate(stored_rank = dplyr::row_number())

stored_rank_lookup <- setNames(ranked_candidates$stored_rank, as.character(ranked_candidates$candidate_scale_group_id))

candidate_group_eval <- candidate_group |>
  mutate(stored_rank = unname(stored_rank_lookup[as.character(candidate_scale_group_id)]))

raw_required <- c(
  "edge_loaded_flag",
  "scale_jump_flag",
  "distribution_flutter_flag",
  "spatial_scale_jump_flag",
  "central_area_share_mean",
  "response_spread_q"
)

if ("stability_score_raw" %in% names(candidate_group_eval)) {
  candidate_group_eval <- candidate_group_eval |>
    mutate(stability_score_raw = as.numeric(stability_score_raw))
} else {
  assert_cols(candidate_group_eval, raw_required, "candidate_group_response_summary.csv")
  candidate_group_eval <- candidate_group_eval |>
    mutate(
      stability_score_raw = 1.0 -
        0.35 * as.numeric(edge_loaded_flag) -
        0.35 * as.numeric(scale_jump_flag) -
        0.20 * as.numeric(distribution_flutter_flag) -
        0.20 * as.numeric(spatial_scale_jump_flag) +
        0.50 * as.numeric(central_area_share_mean) -
        0.10 * as.numeric(response_spread_q)
    )
}

computed_clamp <- pmax(0.0, pmin(1.0, candidate_group_eval$stability_score_raw))
if ("stability_score" %in% names(candidate_group_eval)) {
  candidate_group_eval <- candidate_group_eval |>
    mutate(
      score_clamp_delta = stability_score - computed_clamp,
      score_clamp_check = abs(score_clamp_delta) <= 1e-9
    )
} else {
  candidate_group_eval <- candidate_group_eval |>
    mutate(
      stability_score = computed_clamp,
      score_clamp_delta = NA_real_,
      score_clamp_check = NA
    )
}

true_ranked_candidates <- candidate_group_eval |>
  arrange(desc(stability_score_raw), desc(stability_score), candidate_scale_group_id) |>
  mutate(eval_rank = dplyr::row_number())

true_rank_levels <- as.character(true_ranked_candidates$candidate_scale_group_id)
eval_rank_lookup <- setNames(true_ranked_candidates$eval_rank, true_rank_levels)

true_ranked_candidates <- true_ranked_candidates |>
  mutate(
    candidate_scale_group_id = factor(candidate_scale_group_id, levels = true_rank_levels)
  )

run_population_eval <- run_population |>
  mutate(
    eval_rank = unname(eval_rank_lookup[as.character(candidate_scale_group_id)]),
    candidate_scale_group_id = factor(candidate_scale_group_id, levels = true_rank_levels)
  ) |>
  arrange(eval_rank, run_id)

candidate_group_eval <- candidate_group_eval |>
  mutate(
    eval_rank = unname(eval_rank_lookup[as.character(candidate_scale_group_id)]),
    candidate_scale_group_id = factor(candidate_scale_group_id, levels = true_rank_levels)
  ) |>
  arrange(eval_rank)

ranked_used <- true_ranked_candidates |>
  select(all_of(ranked_required))

ranked_true_ranking <- true_ranked_candidates |>
  select(
    candidate_scale_group_id,
    stored_rank,
    eval_rank,
    stability_score_raw,
    stability_score,
    score_clamp_check,
    score_clamp_delta,
    response_center_q,
    response_spread_q,
    central_area_share_mean,
    upper_tail_area_share_mean,
    candidate_outcome
  )

stored_order <- as.character(ranked_candidates$candidate_scale_group_id)
true_order <- as.character(true_ranked_candidates$candidate_scale_group_id)
stored_order_matches_eval <- identical(stored_order, true_order)
stored_order_mismatch_count <- sum(stored_order != true_order)

run_used <- run_population_eval |>
  select(all_of(run_required))

group_used <- candidate_group_eval |>
  select(all_of(group_required))

readr::write_csv(run_used, file.path(eval_dir, "01_run_population_existing_stats_used.csv"))
readr::write_csv(group_used, file.path(eval_dir, "02_candidate_group_existing_stats_used.csv"))
readr::write_csv(ranked_used, file.path(eval_dir, "03_ranked_candidate_existing_stats_used.csv"))
readr::write_csv(ranked_true_ranking, file.path(eval_dir, "ranked_candidate_true_ranking.csv"))

p1 <- ggplot(run_used, aes(x = candidate_scale_group_id, y = area_weighted_q_median)) +
  geom_hline(yintercept = c(0.5, 1, 2), linetype = "dashed") +
  geom_point() +
  coord_flip() +
  labs(
    title = "Existing Step-9 run statistic: area-weighted q median",
    x = "candidate scale group, ranked order",
    y = "area_weighted_q_median"
  )

ggsave(file.path(eval_dir, "01_run_area_weighted_q_median.png"), p1, width = 9, height = 5, dpi = 180)

run_tail <- run_used |>
  select(candidate_scale_group_id, run_id, lower_tail_area_share, central_area_share, upper_tail_area_share) |>
  pivot_longer(
    cols = c(lower_tail_area_share, central_area_share, upper_tail_area_share),
    names_to = "area_share_class",
    values_to = "area_share"
  )

p2 <- ggplot(run_tail, aes(x = candidate_scale_group_id, y = area_share, group = run_id)) +
  geom_point() +
  facet_wrap(~area_share_class, ncol = 1) +
  coord_flip() +
  labs(
    title = "Existing Step-9 run statistic: lower / central / upper area share",
    x = "candidate scale group, ranked order",
    y = "area share"
  )

ggsave(file.path(eval_dir, "02_run_tail_central_area_shares.png"), p2, width = 9, height = 8, dpi = 180)

group_tail <- group_used |>
  select(candidate_scale_group_id, lower_tail_area_share_mean, central_area_share_mean, upper_tail_area_share_mean) |>
  pivot_longer(
    cols = c(lower_tail_area_share_mean, central_area_share_mean, upper_tail_area_share_mean),
    names_to = "area_share_mean_class",
    values_to = "area_share_mean"
  )

p3 <- ggplot(group_tail, aes(x = candidate_scale_group_id, y = area_share_mean, fill = area_share_mean_class)) +
  geom_col(position = "dodge") +
  coord_flip() +
  labs(
    title = "Existing Step-9 candidate-group statistic: mean area shares",
    x = "candidate scale group, ranked order",
    y = "mean area share"
  )

ggsave(file.path(eval_dir, "03_group_mean_area_shares.png"), p3, width = 10, height = 5, dpi = 180)

p4 <- ggplot(ranked_used, aes(x = candidate_scale_group_id, y = stability_score)) +
  geom_col() +
  coord_flip() +
  labs(
    title = "Existing Step-9 ranked candidate scales",
    x = "candidate scale group, ranked order",
    y = "stability_score"
  )

ggsave(file.path(eval_dir, "04_ranked_candidate_stability_score.png"), p4, width = 9, height = 5, dpi = 180)

p5 <- ggplot(group_used, aes(x = response_center_q, y = response_spread_q, label = candidate_scale_group_id)) +
  geom_vline(xintercept = c(0.5, 1, 2), linetype = "dashed") +
  geom_point() +
  labs(
    title = "Existing Step-9 candidate-group statistic: response center and spread",
    x = "response_center_q",
    y = "response_spread_q"
  )

ggsave(file.path(eval_dir, "05_group_response_center_spread.png"), p5, width = 7, height = 5, dpi = 180)

report_lines <- c(
  "Level-1b existing Step-9 statistics evaluation",
  "",
  paste0("OUT: ", out_root),
  paste0("EVAL: ", eval_dir),
  paste0("Stats directory: ", stats_dir),
  "",
  "Inputs read:",
  paste0("- ", input_manifest$input_name, ": ", input_manifest$path, " [rows=", input_manifest$n_rows, ", columns=", input_manifest$n_columns, "]"),
  "",
  "No label raster was read.",
  "No terra/raster/exactextractr segment statistic was computed.",
  "No scale IDs, radii, label paths, or missing inputs were guessed or substituted.",
  "",
  "Outputs written:",
  "- 00_existing_stats_input_manifest.csv",
  "- 01_run_population_existing_stats_used.csv",
  "- 02_candidate_group_existing_stats_used.csv",
  "- 03_ranked_candidate_existing_stats_used.csv",
  "- ranked_candidate_true_ranking.csv",
  "- 01_run_area_weighted_q_median.png",
  "- 02_run_tail_central_area_shares.png",
  "- 03_group_mean_area_shares.png",
  "- 04_ranked_candidate_stability_score.png",
  "- 05_group_response_center_spread.png",
  "",
  paste0("Stored ranked_candidate_scales.csv order matches true ranking: ", stored_order_matches_eval),
  paste0("Stored ranking mismatch count: ", stored_order_mismatch_count)
)

writeLines(report_lines, con = file.path(eval_dir, "level1b_existing_stats_eval_report.txt"))
cat(paste(report_lines, collapse = "\n"), "\n")
