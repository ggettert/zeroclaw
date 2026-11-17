// Verbatim normalization functions from zeroclaw cda933e6b9937deacbcc0d4d2cd7f1ae5bb4500e.
// Original project license MIT OR Apache-2.0; no scheduler engine copied.
use anyhow::{Context, Result};

pub fn normalize_expression(expression: &str) -> Result<String> {
    let expression = expression.trim();
    let field_count = expression.split_whitespace().count();

    match field_count {
        // standard crontab syntax: minute hour day month weekday
        // Normalize weekday field from standard crontab semantics (0/7=Sun, 1=Mon, …, 6=Sat)
        // to cron-crate semantics (1=Sun, 2=Mon, …, 7=Sat).
        5 => {
            let mut fields: Vec<&str> = expression.split_whitespace().collect();
            let weekday = fields[4];
            let normalized_weekday = normalize_weekday_field(weekday)?;
            fields[4] = &normalized_weekday;
            Ok(format!(
                "0 {} {} {} {} {}",
                fields[0], fields[1], fields[2], fields[3], fields[4]
            ))
        }
        // crate-native syntax includes seconds (+ optional year)
        6 | 7 => Ok(expression.to_string()),
        _ => anyhow::bail!(
            "Invalid cron expression: {expression} (expected 5, 6, or 7 fields, got {field_count})"
        ),
    }
}

/// Translate a single numeric weekday value from standard crontab semantics
/// (0 or 7 = Sunday, 1 = Monday, …, 6 = Saturday) to cron-crate semantics
/// (1 = Sunday, 2 = Monday, …, 7 = Saturday).
fn translate_weekday_value(val: u8) -> Result<u8> {
    match val {
        0 | 7 => Ok(1), // Sunday
        1..=6 => Ok(val + 1),
        _ => anyhow::bail!("Invalid weekday value: {val} (expected 0-7)"),
    }
}

/// Enumerate the standard-crontab weekday values covered by `start-end`.
fn standard_weekday_range_values(start: u8, end: u8) -> Vec<u8> {
    // Enumerate the standard weekday values covered by the range, wrapping
    // around the week (Sun=0..=6=Sat) when `end < start` (e.g. `5-0`).
    let mut standard_days: Vec<u8> = Vec::new();
    let mut day = start;
    loop {
        standard_days.push(day);
        if day == end {
            break;
        }
        // Step through the 0..=7 numbering used by standard crontab, treating 7
        // as the Sunday alias so that a `…-7` endpoint terminates the loop.
        day = if day >= 7 { 0 } else { day + 1 };
    }

    standard_days
}

fn translated_weekday_list(mut standard_days: Vec<u8>) -> Result<String> {
    let mut translated: Vec<u8> = standard_days
        .drain(..)
        .map(translate_weekday_value)
        .collect::<Result<Vec<u8>>>()?;
    translated.sort_unstable();
    translated.dedup();

    Ok(translated
        .into_iter()
        .map(|v| v.to_string())
        .collect::<Vec<_>>()
        .join(","))
}

fn expand_weekday_range(start: u8, end: u8) -> Result<String> {
    translated_weekday_list(standard_weekday_range_values(start, end))
}

fn expand_stepped_weekday_range(start: u8, end: u8, step: u8) -> Result<String> {
    if step == 0 {
        anyhow::bail!("Invalid weekday step: 0");
    }

    let standard_days = standard_weekday_range_values(start, end)
        .into_iter()
        .step_by(step as usize)
        .collect();

    translated_weekday_list(standard_days)
}

/// Normalize the weekday field of a 5-field cron expression from standard
/// crontab numbering to cron-crate numbering. Passes through `*`, named days
/// (e.g. `MON`, `MON-FRI`), and already-valid tokens unchanged.
fn normalize_weekday_field(field: &str) -> Result<String> {
    // Asterisk and wildcard variants pass through unchanged.
    if field == "*" || field == "?" {
        return Ok(field.to_string());
    }

    // If the field contains any alphabetic character it uses named days
    // (e.g. MON-FRI) which the cron crate handles natively.
    if field.chars().any(|c| c.is_ascii_alphabetic()) {
        return Ok(field.to_string());
    }

    // The field may be a comma-separated list of items, where each item is
    // either a single value, a range (start-end), or a range/value with a
    // step (/N).
    let parts: Vec<&str> = field.split(',').collect();
    let mut result_parts = Vec::with_capacity(parts.len());

    for part in parts {
        // Split off optional step suffix first (e.g. "1-5/2" → "1-5" + "2").
        let (range_part, step) = if let Some((r, s)) = part.split_once('/') {
            (r, Some(s))
        } else {
            (part, None)
        };

        let (translated, expanded_step_applied) =
            if let Some((start_s, end_s)) = range_part.split_once('-') {
                let start: u8 = start_s
                    .parse()
                    .with_context(|| format!("Invalid weekday in range: {start_s}"))?;
                let end: u8 = end_s
                    .parse()
                    .with_context(|| format!("Invalid weekday in range: {end_s}"))?;
                let new_start = translate_weekday_value(start)?;
                let new_end = translate_weekday_value(end)?;
                if new_start < new_end || (new_start == new_end && start == end) {
                    (format!("{new_start}-{new_end}"), false)
                } else {
                    if let Some(s) = step {
                        let step: u8 = s
                            .parse()
                            .with_context(|| format!("Invalid weekday step: {s}"))?;
                        (expand_stepped_weekday_range(start, end, step)?, true)
                    } else {
                        (expand_weekday_range(start, end)?, false)
                    }
                }
            } else if range_part == "*" {
                ("*".to_string(), false)
            } else {
                let val: u8 = range_part
                    .parse()
                    .with_context(|| format!("Invalid weekday value: {range_part}"))?;
                (translate_weekday_value(val)?.to_string(), false)
            };

        if let Some(s) = step.filter(|_| !expanded_step_applied) {
            result_parts.push(format!("{translated}/{s}"));
        } else {
            result_parts.push(translated);
        }
    }

    Ok(result_parts.join(","))
}
