#!/usr/bin/env Rscript

# Scientific summary of an existing joint Level-1A/Level-1B sensitivity study.
# This script reads completed workflow artifacts only. It does not run Metashape,
# segmentation, Step 9, Step 10, or any workflow selection logic.

args <- commandArgs(trailingOnly = TRUE)
allow_incomplete <- "--allow-incomplete" %in% args
args <- args[args != "--allow-incomplete"]
if (length(args) < 1L || length(args) > 2L) {
  stop(
    paste(
      "Usage: Rscript R/level1ab_sensitivity_analysis.R",
      "STUDY_ROOT [OUTPUT_DIR] [--allow-incomplete]"
    ),
    call. = FALSE
  )
}
if (!requireNamespace("jsonlite", quietly = TRUE)) {
  stop("Required R package is missing: jsonlite", call. = FALSE)
}

study_root <- normalizePath(args[[1L]], mustWork = TRUE)
analysis_dir <- if (length(args) == 2L) {
  normalizePath(args[[2L]], mustWork = FALSE)
} else {
  file.path(
    study_root,
    if (allow_incomplete) "sensitivity_analysis_incremental" else "sensitivity_analysis"
  )
}
dir.create(analysis_dir, recursive = TRUE, showWarnings = FALSE)

issues <- character()
record_issue <- function(message) {
  issues <<- unique(c(issues, message))
  message(message)
}

read_json_safe <- function(path) {
  if (!file.exists(path) || is.na(file.info(path)$size) || file.info(path)$size == 0) {
    return(NULL)
  }
  tryCatch(
    jsonlite::fromJSON(path, simplifyVector = TRUE),
    error = function(error) {
      record_issue(sprintf("Invalid JSON skipped: %s (%s)", path, error$message))
      NULL
    }
  )
}

write_csv <- function(value, filename) {
  utils::write.csv(
    value,
    file.path(analysis_dir, filename),
    row.names = FALSE,
    na = ""
  )
}

scalar_numeric <- function(value) {
  if (is.null(value) || length(value) == 0L) return(NA_real_)
  suppressWarnings(as.numeric(unlist(value, use.names = FALSE)[[1L]]))
}

scalar_character <- function(value) {
  if (is.null(value) || length(value) == 0L) return(NA_character_)
  as.character(unlist(value, use.names = FALSE)[[1L]])
}

scalar_logical <- function(value) {
  if (is.null(value) || length(value) == 0L) return(NA)
  as.logical(unlist(value, use.names = FALSE)[[1L]])
}

column_numeric <- function(data, name) {
  if (!is.data.frame(data) || !name %in% names(data)) return(rep(NA_real_, nrow(data)))
  suppressWarnings(as.numeric(data[[name]]))
}

column_character <- function(data, name) {
  if (!is.data.frame(data) || !name %in% names(data)) return(rep(NA_character_, nrow(data)))
  as.character(data[[name]])
}

correlation_long <- function(data, columns, method = "spearman") {
  columns <- columns[
    columns %in% names(data) &
      vapply(data[columns], function(x) sum(is.finite(as.numeric(x))) >= 3L, logical(1)) &
      vapply(data[columns], function(x) stats::sd(as.numeric(x), na.rm = TRUE) > 0, logical(1))
  ]
  if (length(columns) < 2L) {
    return(data.frame(
      metric_x = character(), metric_y = character(), n = integer(),
      correlation = numeric(), p_value = numeric(), method = character()
    ))
  }
  rows <- list()
  index <- 1L
  for (i in seq_len(length(columns) - 1L)) {
    for (j in seq.int(i + 1L, length(columns))) {
      x <- suppressWarnings(as.numeric(data[[columns[[i]]]]))
      y <- suppressWarnings(as.numeric(data[[columns[[j]]]]))
      keep <- is.finite(x) & is.finite(y)
      n <- sum(keep)
      if (n < 3L || stats::sd(x[keep]) == 0 || stats::sd(y[keep]) == 0) next
      test <- suppressWarnings(stats::cor.test(x[keep], y[keep], method = method, exact = FALSE))
      rows[[index]] <- data.frame(
        metric_x = columns[[i]],
        metric_y = columns[[j]],
        n = n,
        correlation = unname(test$estimate),
        p_value = test$p.value,
        method = method
      )
      index <- index + 1L
    }
  }
  if (length(rows) == 0L) return(data.frame())
  do.call(rbind, rows)
}

plot_correlation_heatmap <- function(data, columns, path, title) {
  columns <- columns[
    columns %in% names(data) &
      vapply(data[columns], function(x) sum(is.finite(as.numeric(x))) >= 3L, logical(1)) &
      vapply(data[columns], function(x) stats::sd(as.numeric(x), na.rm = TRUE) > 0, logical(1))
  ]
  grDevices::png(path, width = 1800, height = 1500, res = 180)
  on.exit(grDevices::dev.off(), add = TRUE)
  if (length(columns) < 2L) {
    graphics::plot.new()
    graphics::text(0.5, 0.5, "Insufficient complete numeric fields for correlation")
    return(invisible(NULL))
  }
  matrix_values <- stats::cor(
    as.data.frame(lapply(data[columns], as.numeric)),
    use = "pairwise.complete.obs",
    method = "spearman"
  )
  palette <- grDevices::colorRampPalette(c("#2166ac", "white", "#b2182b"))(101)
  n <- ncol(matrix_values)
  graphics::par(mar = c(10, 10, 4, 2))
  graphics::image(
    seq_len(n), seq_len(n), t(matrix_values[n:1, , drop = FALSE]),
    col = palette, zlim = c(-1, 1), axes = FALSE,
    xlab = "", ylab = "", main = title
  )
  graphics::axis(1, at = seq_len(n), labels = colnames(matrix_values), las = 2, cex.axis = 0.7)
  graphics::axis(2, at = seq_len(n), labels = rev(rownames(matrix_values)), las = 2, cex.axis = 0.7)
  for (row in seq_len(n)) {
    for (column in seq_len(n)) {
      graphics::text(column, n - row + 1, sprintf("%.2f", matrix_values[row, column]), cex = 0.65)
    }
  }
}

numeric_summary <- function(data, group_name) {
  numeric_names <- names(data)[vapply(data, is.numeric, logical(1))]
  rows <- lapply(numeric_names, function(name) {
    values <- data[[name]][is.finite(data[[name]])]
    if (length(values) == 0L) return(NULL)
    mean_value <- mean(values)
    data.frame(
      group = group_name,
      metric = name,
      n = length(values),
      mean = mean_value,
      sd = if (length(values) > 1L) stats::sd(values) else NA_real_,
      cv_percent = if (length(values) > 1L && mean_value != 0) 100 * stats::sd(values) / abs(mean_value) else NA_real_,
      median = stats::median(values),
      mad = stats::mad(values, constant = 1),
      min = min(values),
      max = max(values),
      range = max(values) - min(values)
    )
  })
  rows <- Filter(Negate(is.null), rows)
  if (length(rows) == 0L) return(data.frame())
  do.call(rbind, rows)
}

# ---------------------------------------------------------------------------
# Study design and Level-1A factorial sensitivity
# ---------------------------------------------------------------------------

design_path <- file.path(study_root, "study_design.csv")
if (!file.exists(design_path)) stop("Missing study design: ", design_path, call. = FALSE)
study_design <- utils::read.csv(design_path, stringsAsFactors = FALSE, check.names = FALSE)

level1a_design <- study_design[study_design$workflow == "level1a", , drop = FALSE]
level1a_dirs <- unique(level1a_design$output_dir[nzchar(level1a_design$output_dir)])
if (length(level1a_dirs) != 1L) {
  stop("Expected exactly one Level-1A experiment directory in study_design.csv", call. = FALSE)
}
level1b_design <- unique(study_design[study_design$workflow == "level1b", c(
  "run_id", "source_kind", "source_id", "profile_id", "output_dir", "config_path"
), drop = FALSE])

completion_problems <- character()
level1a_manifest_path <- file.path(level1a_dirs[[1L]], "manifest.csv")
if (!file.exists(level1a_manifest_path)) {
  completion_problems <- c(completion_problems, "Level-1A manifest.csv is missing")
} else {
  level1a_manifest <- utils::read.csv(
    level1a_manifest_path, stringsAsFactors = FALSE, check.names = FALSE
  )
  if (nrow(level1a_manifest) != nrow(level1a_design)) {
    completion_problems <- c(
      completion_problems,
      sprintf(
        "Level-1A manifest has %d rows; %d were planned",
        nrow(level1a_manifest), nrow(level1a_design)
      )
    )
  }
  non_ok <- level1a_manifest$status != "ok"
  if (any(non_ok)) {
    completion_problems <- c(
      completion_problems,
      sprintf("Level-1A has %d manifest rows not in status ok", sum(non_ok))
    )
  }
  missing_orthos <- !file.exists(level1a_manifest$ortho_file) |
    is.na(file.info(level1a_manifest$ortho_file)$size) |
    file.info(level1a_manifest$ortho_file)$size == 0
  if (any(missing_orthos)) {
    completion_problems <- c(
      completion_problems,
      sprintf("Level-1A has %d missing or empty orthomosaics", sum(missing_orthos))
    )
  }
}

terminal_level1b_statuses <- c(
  "level1b_dumb_chain_complete",
  "step9b_non_adjacent_choice_required"
)
level1b_preflight_status <- character(nrow(level1b_design))
for (index in seq_len(nrow(level1b_design))) {
  report_path <- file.path(
    level1b_design$output_dir[[index]], "level1b_dumb_chain_report.json"
  )
  report <- read_json_safe(report_path)
  status <- if (is.null(report)) {
    if (file.exists(report_path)) "invalid_or_empty_report" else "not_run"
  } else {
    scalar_character(report$status)
  }
  level1b_preflight_status[[index]] <- status
  if (!status %in% terminal_level1b_statuses) {
    completion_problems <- c(
      completion_problems,
      sprintf("Level-1B %s has non-terminal status %s", level1b_design$run_id[[index]], status)
    )
  }
}
study_complete <- length(completion_problems) == 0L
if (!study_complete && !allow_incomplete) {
  stop(
    paste(
      c(
        "Sensitivity study is incomplete; final analysis was not written:",
        paste0("- ", completion_problems),
        paste(
          "Use --allow-incomplete only for a provisional analysis, or resume",
          "the study before running the final analysis."
        )
      ),
      collapse = "\n"
    ),
    call. = FALSE
  )
}
if (!study_complete && allow_incomplete) {
  for (problem in completion_problems) record_issue(problem)
}
write_csv(study_design, "study_design_copy.csv")

level1a_metrics_path <- file.path(level1a_dirs[[1L]], "stability_union", "summary_key_metrics.tsv")
if (!file.exists(level1a_metrics_path)) {
  stop("Missing Level-1A metrics: ", level1a_metrics_path, call. = FALSE)
}
level1a <- utils::read.delim(
  level1a_metrics_path,
  stringsAsFactors = FALSE,
  check.names = FALSE
)

pattern <- "^ds([0-9]+)_fc([0-9]+)k_smooth([0-9]+)_or(.+)$"
matches <- regexec(pattern, level1a$variant_id)
parts <- regmatches(level1a$variant_id, matches)
if (any(lengths(parts) != 5L)) {
  stop("One or more Level-1A variant IDs do not match the active factorial naming contract", call. = FALSE)
}
level1a$align_downscale <- as.numeric(vapply(parts, `[[`, character(1), 2L))
level1a$face_count <- 1000 * as.numeric(vapply(parts, `[[`, character(1), 3L))
level1a$smoothing_iterations <- as.numeric(vapply(parts, `[[`, character(1), 4L))
level1a$ortho_resolution_m <- as.numeric(sub("p", ".", vapply(parts, `[[`, character(1), 5L), fixed = TRUE))
write_csv(level1a, "level1a_variant_metrics.csv")

level1a_metrics <- c(
  "any_support_fraction_grid", "full_support_fraction_grid",
  "variable_support_fraction_grid", "support_persistence_footprint",
  "support_dropout_footprint", "mean_mad_rgb", "p95_mad_rgb",
  "mean_rmse_to_median", "p95_rmse_to_median",
  "stable_fraction_support_rmse", "unstable_fraction_support_rmse"
)
level1a_metrics <- level1a_metrics[level1a_metrics %in% names(level1a)]
factor_names <- c("align_downscale", "face_count", "smoothing_iterations")
metric_direction <- c(
  any_support_fraction_grid = "higher_is_more_support",
  full_support_fraction_grid = "higher_is_more_support",
  variable_support_fraction_grid = "lower_is_more_stable",
  support_persistence_footprint = "higher_is_more_stable",
  support_dropout_footprint = "lower_is_more_stable",
  mean_mad_rgb = "lower_is_more_stable",
  p95_mad_rgb = "lower_is_more_stable",
  mean_rmse_to_median = "lower_is_more_stable",
  p95_rmse_to_median = "lower_is_more_stable",
  stable_fraction_support_rmse = "higher_is_more_stable",
  unstable_fraction_support_rmse = "lower_is_more_stable"
)

factor_effect_rows <- list()
effect_index <- 1L
for (factor_name in factor_names) {
  factor_levels <- sort(unique(level1a[[factor_name]]))
  if (length(factor_levels) != 2L) next
  other_factors <- setdiff(factor_names, factor_name)
  pairing_key <- interaction(level1a[other_factors], drop = TRUE, lex.order = TRUE)
  for (metric in level1a_metrics) {
    differences <- numeric()
    for (key in levels(pairing_key)) {
      subset <- level1a[pairing_key == key, , drop = FALSE]
      low <- subset[subset[[factor_name]] == factor_levels[[1L]], metric]
      high <- subset[subset[[factor_name]] == factor_levels[[2L]], metric]
      if (length(low) == 1L && length(high) == 1L && is.finite(low) && is.finite(high)) {
        differences <- c(differences, high - low)
      }
    }
    n_pairs <- length(differences)
    effect <- if (n_pairs > 0L) mean(differences) else NA_real_
    sd_pairs <- if (n_pairs > 1L) stats::sd(differences) else NA_real_
    se_pairs <- if (n_pairs > 1L) sd_pairs / sqrt(n_pairs) else NA_real_
    ci_half <- if (n_pairs > 1L) stats::qt(0.975, df = n_pairs - 1L) * se_pairs else NA_real_
    denominator <- mean(abs(level1a[[metric]]), na.rm = TRUE)
    factor_effect_rows[[effect_index]] <- data.frame(
      factor = factor_name,
      low_level = factor_levels[[1L]],
      high_level = factor_levels[[2L]],
      metric = metric,
      metric_direction = unname(metric_direction[[metric]]),
      paired_contrast_count = n_pairs,
      mean_high_minus_low = effect,
      sd_across_balanced_contrasts = sd_pairs,
      se_across_balanced_contrasts = se_pairs,
      ci95_low = effect - ci_half,
      ci95_high = effect + ci_half,
      relative_effect_percent = if (is.finite(denominator) && denominator != 0) 100 * effect / denominator else NA_real_,
      uncertainty_scope = "variation_of_balanced_factor_contrasts_not_independent_scene_error"
    )
    effect_index <- effect_index + 1L
  }
}
level1a_effects <- do.call(rbind, factor_effect_rows)
write_csv(level1a_effects, "level1a_factor_effects.csv")

level1a_cor_spearman <- correlation_long(level1a, level1a_metrics, "spearman")
level1a_cor_pearson <- correlation_long(level1a, level1a_metrics, "pearson")
write_csv(level1a_cor_spearman, "level1a_correlations_spearman.csv")
write_csv(level1a_cor_pearson, "level1a_correlations_pearson.csv")

selected_effect_metrics <- intersect(
  c("mean_mad_rgb", "p95_mad_rgb", "mean_rmse_to_median",
    "p95_rmse_to_median", "stable_fraction_support_rmse",
    "support_dropout_footprint"),
  level1a_metrics
)
grDevices::png(file.path(analysis_dir, "level1a_factor_effects.png"), width = 1800, height = 1200, res = 160)
if (length(selected_effect_metrics) > 0L) {
  graphics::par(mfrow = c(2, 3), mar = c(5, 8, 4, 2))
  for (metric in selected_effect_metrics) {
    data <- level1a_effects[level1a_effects$metric == metric, , drop = FALSE]
    positions <- rev(seq_len(nrow(data)))
    limits <- range(c(data$ci95_low, data$ci95_high, 0), na.rm = TRUE)
    graphics::plot(
      data$mean_high_minus_low, positions,
      xlim = limits, yaxt = "n", ylab = "", xlab = "high - low",
      main = metric, pch = 19
    )
    graphics::axis(2, at = positions, labels = data$factor, las = 2, cex.axis = 0.8)
    graphics::abline(v = 0, lty = 2, col = "grey50")
    graphics::segments(data$ci95_low, positions, data$ci95_high, positions)
  }
} else {
  graphics::plot.new(); graphics::text(0.5, 0.5, "No Level-1A effect metrics available")
}
grDevices::dev.off()

plot_correlation_heatmap(
  level1a, level1a_metrics,
  file.path(analysis_dir, "level1a_metric_correlation.png"),
  "Level-1A Spearman correlations (n = 8 variants)"
)

# ---------------------------------------------------------------------------
# Level-1B status, prescreen, Step-9 evidence, and Step-10 summaries
# ---------------------------------------------------------------------------

profile_rows <- list()
ranked_rows <- list()
alternative_rows <- list()
ranked_index <- 1L
alternative_index <- 1L

for (row_index in seq_len(nrow(level1b_design))) {
  design_row <- level1b_design[row_index, , drop = FALSE]
  run_root <- design_row$output_dir[[1L]]
  chain <- read_json_safe(file.path(run_root, "level1b_dumb_chain_report.json"))
  chain_status <- if (is.null(chain)) {
    if (file.exists(file.path(run_root, "level1b_dumb_chain_report.json"))) "invalid_or_empty_report" else "not_run"
  } else scalar_character(chain$status)

  prescreen <- read_json_safe(file.path(
    run_root, "level1b", "candidate_pre_screening", "candidate_pre_screening_report.json"
  ))
  variogram <- read_json_safe(file.path(
    run_root, "level1b", "candidate_pre_screening", "variogram_diagnostics.json"
  ))
  ranked <- read_json_safe(file.path(
    run_root, "level1b", "candidate_response_surface", "ranked_candidate_scales.json"
  ))
  alternatives <- read_json_safe(file.path(
    run_root, "level1b", "local_transition_refinement", "step9b_supported_scale_alternatives.json"
  ))
  quality <- read_json_safe(file.path(
    run_root, "level1b", "step10_materialization", "quality", "ortho_segmentation_quality_info.json"
  ))

  selected_knn_k <- NA_real_
  selected_ranger <- NA_real_
  if (!is.null(prescreen) && !is.null(prescreen$ranger_diagnostics)) {
    selected_knn_k <- scalar_numeric(prescreen$ranger_diagnostics$selected_knn_k)
    curve <- prescreen$ranger_diagnostics$hsm_ranger_curve
    if (is.data.frame(curve) && nrow(curve) > 0L) {
      matched <- curve[suppressWarnings(as.numeric(curve$knn_k)) == selected_knn_k, , drop = FALSE]
      if (nrow(matched) > 0L) selected_ranger <- scalar_numeric(matched$ranger[[1L]])
    }
  }

  top <- NULL
  second <- NULL
  if (is.data.frame(ranked) && nrow(ranked) > 0L) {
    candidate_table <- data.frame(
      run_id = design_row$run_id[[1L]],
      source_kind = design_row$source_kind[[1L]],
      source_id = design_row$source_id[[1L]],
      profile_id = design_row$profile_id[[1L]],
      rank = seq_len(nrow(ranked)),
      candidate_scale_group_id = column_character(ranked, "candidate_scale_group_id"),
      radius_m = column_numeric(ranked, "scale_coordinate_value"),
      stability_score_raw = column_numeric(ranked, "stability_score_raw"),
      stability_score = column_numeric(ranked, "stability_score"),
      boundary_support_score_raw = column_numeric(ranked, "boundary_support_score_raw"),
      ensemble_boundary_agreement = column_numeric(ranked, "ensemble_boundary_agreement"),
      seed_realization_boundary_agreement = column_numeric(ranked, "seed_realization_boundary_agreement"),
      ranger_boundary_agreement = column_numeric(ranked, "ranger_boundary_agreement"),
      radius_boundary_agreement = column_numeric(ranked, "radius_boundary_agreement"),
      response_center_q = column_numeric(ranked, "response_center_q"),
      response_spread_q = column_numeric(ranked, "response_spread_q"),
      central_area_share_mean = column_numeric(ranked, "central_area_share_mean"),
      lower_tail_area_share_mean = column_numeric(ranked, "lower_tail_area_share_mean"),
      upper_tail_area_share_mean = column_numeric(ranked, "upper_tail_area_share_mean"),
      run_count = column_numeric(ranked, "run_count"),
      candidate_outcome = column_character(ranked, "candidate_outcome"),
      stringsAsFactors = FALSE
    )
    ranked_rows[[ranked_index]] <- candidate_table
    ranked_index <- ranked_index + 1L
    top <- candidate_table[1L, , drop = FALSE]
    if (nrow(candidate_table) >= 2L) second <- candidate_table[2L, , drop = FALSE]
  }

  if (is.data.frame(alternatives) && nrow(alternatives) > 0L) {
    alternative_rows[[alternative_index]] <- data.frame(
      run_id = design_row$run_id[[1L]],
      source_kind = design_row$source_kind[[1L]],
      source_id = design_row$source_id[[1L]],
      profile_id = design_row$profile_id[[1L]],
      rank = column_numeric(alternatives, "rank"),
      candidate_scale_group_id = column_character(alternatives, "candidate_scale_group_id"),
      radius_m = column_numeric(alternatives, "scale_coordinate_value"),
      stability_score_raw = column_numeric(alternatives, "stability_score_raw"),
      stringsAsFactors = FALSE
    )
    alternative_index <- alternative_index + 1L
  }

  radius_domain <- if (!is.null(prescreen)) suppressWarnings(as.numeric(unlist(prescreen$radius_domain_m))) else numeric()
  selected_fields <- if (!is.null(quality)) quality$selected_run_fields else NULL
  segment_summary <- if (!is.null(quality)) quality$segment_stats_summary else NULL

  profile_rows[[row_index]] <- data.frame(
    run_id = design_row$run_id[[1L]],
    source_kind = design_row$source_kind[[1L]],
    source_id = design_row$source_id[[1L]],
    profile_id = design_row$profile_id[[1L]],
    status = chain_status,
    branch = if (is.null(chain)) NA_character_ else scalar_character(chain$branch),
    prescreen_status = if (is.null(prescreen)) NA_character_ else scalar_character(prescreen$status),
    candidate_count = if (is.null(prescreen)) NA_real_ else scalar_numeric(prescreen$candidate_count),
    scale_family_count = if (is.null(prescreen)) NA_real_ else scalar_numeric(prescreen$scale_family_count),
    stable_crossing_count = if (is.null(prescreen)) NA_real_ else scalar_numeric(prescreen$stable_crossing_count),
    valid_vector_count = if (is.null(prescreen)) NA_real_ else scalar_numeric(prescreen$valid_vector_count),
    radius_domain_min_m = if (length(radius_domain) >= 1L) radius_domain[[1L]] else NA_real_,
    radius_domain_max_m = if (length(radius_domain) >= 2L) radius_domain[[2L]] else NA_real_,
    selected_knn_k = selected_knn_k,
    selected_scene_ranger = selected_ranger,
    variogram_sill = if (is.null(variogram)) NA_real_ else scalar_numeric(variogram$sill),
    variogram_knee_radius_m = if (is.null(variogram)) NA_real_ else scalar_numeric(variogram$knee_radius_m),
    variogram_tail_relative_span = if (is.null(variogram)) NA_real_ else scalar_numeric(variogram$tail_relative_span),
    directional_range_ratio = if (is.null(variogram)) NA_real_ else scalar_numeric(variogram$directional_range_ratio),
    directional_anisotropy_present = if (is.null(variogram)) NA else scalar_logical(variogram$directional_anisotropy_present),
    top_candidate_id = if (is.null(top)) NA_character_ else top$candidate_scale_group_id,
    top_radius_m = if (is.null(top)) NA_real_ else top$radius_m,
    top_stability_score_raw = if (is.null(top)) NA_real_ else top$stability_score_raw,
    second_radius_m = if (is.null(second)) NA_real_ else second$radius_m,
    second_stability_score_raw = if (is.null(second)) NA_real_ else second$stability_score_raw,
    top_two_score_gap = if (is.null(top) || is.null(second)) NA_real_ else top$stability_score_raw - second$stability_score_raw,
    supported_alternative_count = if (is.data.frame(alternatives)) nrow(alternatives) else 0L,
    selected_candidate_id = if (is.null(quality)) NA_character_ else scalar_character(quality$selected_candidate_id),
    selected_representative_id = if (is.null(quality)) NA_character_ else scalar_character(quality$selected_representative_id),
    segment_count = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$segment_count),
    segment_density_per_ha = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$segment_density_per_ha),
    total_labelled_area_m2 = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$total_labelled_area_m2),
    mean_area_m2 = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$mean_area_m2),
    median_area_m2 = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$median_area_m2),
    q10_area_m2 = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$q10_area_m2),
    q90_area_m2 = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$q90_area_m2),
    central_area_share = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$central_area_share),
    lower_tail_area_share = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$lower_tail_area_share),
    upper_tail_area_share = if (is.null(selected_fields)) NA_real_ else scalar_numeric(selected_fields$upper_tail_area_share),
    exactextractr_segment_count = if (is.null(segment_summary)) NA_real_ else scalar_numeric(segment_summary$segment_count),
    exactextractr_band_count = if (is.null(segment_summary)) NA_real_ else scalar_numeric(segment_summary$band_count),
    stringsAsFactors = FALSE
  )
}

level1b_profiles <- do.call(rbind, profile_rows)
level1b_ranked <- if (length(ranked_rows) > 0L) do.call(rbind, ranked_rows) else data.frame()
level1b_alternatives <- if (length(alternative_rows) > 0L) do.call(rbind, alternative_rows) else data.frame()
write_csv(level1b_profiles, "level1b_profile_summary.csv")
write_csv(level1b_ranked, "level1b_step9_ranked_candidates.csv")
write_csv(level1b_alternatives, "level1b_step9b_supported_alternatives.csv")

status_counts <- as.data.frame(table(level1b_profiles$source_kind, level1b_profiles$status), stringsAsFactors = FALSE)
names(status_counts) <- c("source_kind", "status", "count")
status_counts <- status_counts[status_counts$count > 0L, , drop = FALSE]
write_csv(status_counts, "level1b_status_counts.csv")

selected_product_profiles <- level1b_profiles[level1b_profiles$source_kind == "selected_product", , drop = FALSE]
propagation_profiles <- level1b_profiles[level1b_profiles$source_kind == "level1a_variant", , drop = FALSE]
profile_numeric <- numeric_summary(selected_product_profiles, "selected_product_profiles")
propagation_numeric <- numeric_summary(propagation_profiles, "level1a_variant_propagation")
level1b_numeric_summary <- rbind(profile_numeric, propagation_numeric)
write_csv(level1b_numeric_summary, "level1b_numeric_sensitivity_summary.csv")

baseline_change_rows <- list()
baseline <- selected_product_profiles[selected_product_profiles$profile_id == "baseline", , drop = FALSE]
if (nrow(baseline) == 1L) {
  numeric_names <- names(selected_product_profiles)[vapply(selected_product_profiles, is.numeric, logical(1))]
  change_index <- 1L
  for (row_index in seq_len(nrow(selected_product_profiles))) {
    for (metric in numeric_names) {
      reference <- baseline[[metric]][[1L]]
      value <- selected_product_profiles[[metric]][[row_index]]
      if (!is.finite(reference) || !is.finite(value)) next
      baseline_change_rows[[change_index]] <- data.frame(
        profile_id = selected_product_profiles$profile_id[[row_index]],
        metric = metric,
        baseline_value = reference,
        profile_value = value,
        absolute_change = value - reference,
        relative_change_percent = if (reference != 0) 100 * (value - reference) / abs(reference) else NA_real_
      )
      change_index <- change_index + 1L
    }
  }
}
baseline_changes <- if (length(baseline_change_rows) > 0L) do.call(rbind, baseline_change_rows) else data.frame()
write_csv(baseline_changes, "level1b_changes_from_baseline.csv")

level1b_correlation_fields <- c(
  "candidate_count", "stable_crossing_count", "selected_scene_ranger",
  "variogram_knee_radius_m", "directional_range_ratio", "top_radius_m",
  "top_stability_score_raw", "top_two_score_gap", "segment_count",
  "segment_density_per_ha", "median_area_m2", "central_area_share"
)
level1b_correlations <- correlation_long(
  selected_product_profiles,
  level1b_correlation_fields,
  "spearman"
)
write_csv(level1b_correlations, "level1b_profile_correlations_spearman.csv")

# Status plot.
grDevices::png(file.path(analysis_dir, "level1b_status_by_run.png"), width = 1800, height = 1000, res = 170)
status_factor <- factor(level1b_profiles$status)
status_palette <- grDevices::rainbow(max(1L, nlevels(status_factor)), s = 0.55, v = 0.8)
graphics::par(mar = c(12, 5, 4, 2))
graphics::barplot(
  rep(1, nrow(level1b_profiles)),
  names.arg = level1b_profiles$run_id,
  col = status_palette[status_factor], las = 2,
  ylab = "run present", main = "Level-1B run status"
)
graphics::legend("topright", legend = levels(status_factor), fill = status_palette, cex = 0.8)
grDevices::dev.off()

# Step-9 candidate curves by selected-product profile.
grDevices::png(file.path(analysis_dir, "level1b_step9_candidate_curves.png"), width = 1800, height = 1200, res = 170)
curve_data <- level1b_ranked[
  nrow(level1b_ranked) > 0L & level1b_ranked$source_kind == "selected_product" &
    is.finite(level1b_ranked$radius_m) & is.finite(level1b_ranked$stability_score_raw),
  , drop = FALSE
]
if (nrow(curve_data) > 0L) {
  profile_ids <- unique(curve_data$profile_id)
  colours <- setNames(grDevices::rainbow(length(profile_ids), s = 0.65, v = 0.75), profile_ids)
  graphics::plot(
    range(curve_data$radius_m), range(curve_data$stability_score_raw),
    type = "n", xlab = "scene-adaptive candidate radius (m)",
    ylab = "Step-9a stability_score_raw",
    main = "Level-1B Step-9a response by parameter profile"
  )
  for (profile_id in profile_ids) {
    data <- curve_data[curve_data$profile_id == profile_id, , drop = FALSE]
    data <- data[order(data$radius_m), , drop = FALSE]
    graphics::lines(data$radius_m, data$stability_score_raw, type = "b", pch = 19, col = colours[[profile_id]])
  }
  graphics::legend("bottomright", legend = profile_ids, col = colours, lty = 1, pch = 19, cex = 0.75)
} else {
  graphics::plot.new(); graphics::text(0.5, 0.5, "No complete Step-9a candidate curves available")
}
grDevices::dev.off()

plot_correlation_heatmap(
  selected_product_profiles,
  level1b_correlation_fields,
  file.path(analysis_dir, "level1b_profile_correlation.png"),
  "Level-1B profile Spearman correlations (descriptive)"
)

# ---------------------------------------------------------------------------
# Human-readable report and session record
# ---------------------------------------------------------------------------

best_lines <- character()
for (metric in intersect(c(
  "mean_mad_rgb", "p95_mad_rgb", "mean_rmse_to_median",
  "p95_rmse_to_median", "stable_fraction_support_rmse"
), names(level1a))) {
  direction <- metric_direction[[metric]]
  index <- if (startsWith(direction, "lower")) which.min(level1a[[metric]]) else which.max(level1a[[metric]])
  best_lines <- c(best_lines, sprintf(
    "- `%s`: `%s` (%g; %s)", metric, level1a$variant_id[[index]], level1a[[metric]][[index]], direction
  ))
}

status_lines <- if (nrow(status_counts) > 0L) {
  apply(status_counts, 1, function(row) sprintf("- `%s` / `%s`: %s", row[[1L]], row[[2L]], row[[3L]]))
} else "- No Level-1B statuses available."

report_lines <- c(
  "# Level-1A / Level-1B Sensitivity Analysis",
  "",
  sprintf("Study root: `%s`", study_root),
  sprintf("Generated: `%s`", format(Sys.time(), tz = "UTC", usetz = TRUE)),
  sprintf("Analysis mode: `%s`", if (allow_incomplete) "incremental_preview" else "complete_study"),
  "",
  "## Completeness",
  "",
  sprintf("- Study completion contract satisfied: %s", study_complete),
  sprintf("- Level-1A planned/completed runs: %d/%d", nrow(level1a_design), if (exists("level1a_manifest")) sum(level1a_manifest$status == "ok") else 0L),
  sprintf("- Level-1A variants with summary metrics: %d", nrow(level1a)),
  sprintf("- Planned Level-1B runs: %d", nrow(level1b_profiles)),
  sprintf("- Terminal Level-1B runs: %d", sum(level1b_profiles$status %in% terminal_level1b_statuses)),
  sprintf("- Level-1B runs with Step-9a ranked evidence: %d", length(unique(level1b_ranked$run_id))),
  sprintf("- Level-1B runs with Step-10 quality evidence: %d", sum(is.finite(level1b_profiles$segment_count))),
  "",
  "## Level-1A metric extrema",
  "",
  best_lines,
  "",
  "## Level-1B status counts",
  "",
  status_lines,
  "",
  "## Statistical interpretation",
  "",
  "- Level-1A factor effects are balanced high-minus-low contrasts across the other factor settings.",
  "- Their SD, SE, and 95% interval describe variation among those balanced contrasts. They are not independent-scene sampling errors.",
  "- Pearson and Spearman p-values are exploratory because Level-1A has only eight designed variants and Level-1B has at most seven selected-product profiles.",
  "- Level-1B profile summaries are one-at-a-time sensitivity comparisons, not random replicates and not an inferential population sample.",
  "- `step9b_non_adjacent_choice_required` is retained as scale-ambiguity evidence, not converted into a selected segmentation.",
  "- exactextractr and quality JSON values are evidence fields; this analysis does not assign a final quality class.",
  "- The four Level-1A-variant propagation runs are reported separately from the seven Level-1B parameter profiles.",
  "",
  "## Principal outputs",
  "",
  "- `level1a_factor_effects.csv`",
  "- `level1a_correlations_spearman.csv`",
  "- `level1a_factor_effects.png`",
  "- `level1a_metric_correlation.png`",
  "- `level1b_profile_summary.csv`",
  "- `level1b_step9_ranked_candidates.csv`",
  "- `level1b_step9b_supported_alternatives.csv`",
  "- `level1b_numeric_sensitivity_summary.csv`",
  "- `level1b_changes_from_baseline.csv`",
  "- `level1b_step9_candidate_curves.png`",
  "- `level1b_status_by_run.png`",
  "",
  "## Read warnings",
  "",
  if (length(issues) == 0L) "- None." else paste0("- ", issues)
)
writeLines(report_lines, file.path(analysis_dir, "sensitivity_analysis_report.md"))
writeLines(capture.output(sessionInfo()), file.path(analysis_dir, "r_session_info.txt"))

cat(sprintf("WROTE %s\n", analysis_dir))
