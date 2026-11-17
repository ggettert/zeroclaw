//! Isolated feasibility code, not a production API or approved cron replacement.
use anyhow::{Context, Result, bail};
use croner::parser::{CronParser, Seconds, Year};
use jiff::{
    Timestamp, Zoned,
    fmt::temporal::DateTimePrinter,
    tz::{Offset, TimeZone},
};

pub mod normalization;

/// Only the RFC3339 subset with a four-digit year and no leap second is
/// supported here. Reject unsupported historical forms rather than silently
/// normalizing leap seconds or accepting Temporal zone annotations.
pub fn parse_persisted(raw: &str) -> Result<Timestamp> {
    let b = raw.as_bytes();
    if !raw.is_ascii()
        || b.len() < 20
        || !b[..4].iter().all(u8::is_ascii_digit)
        || b[4] != b'-'
        || b[7] != b'-'
        || b[10] != b'T'
        || b[13] != b':'
        || b[16] != b':'
        || &b[17..19] == b"60"
        || raw.contains('[')
        || raw.contains(']')
    {
        bail!("outside prototype RFC3339 compatibility envelope");
    }
    let suffix = &raw[19..];
    let offset = if let Some(fraction) = suffix.strip_prefix('.') {
        let digits = fraction.bytes().take_while(u8::is_ascii_digit).count();
        if !(1..=9).contains(&digits) {
            bail!("fraction must contain 1..=9 digits");
        }
        &fraction[digits..]
    } else {
        suffix
    };
    let numeric = offset.as_bytes();
    if offset != "Z"
        && !(numeric.len() == 6
            && matches!(numeric[0], b'+' | b'-')
            && numeric[3] == b':'
            && numeric[1..3].iter().all(u8::is_ascii_digit)
            && numeric[4..6].iter().all(u8::is_ascii_digit))
    {
        bail!("timestamp requires RFC3339 Z or minute-precision numeric offset");
    }
    let ts: Timestamp = raw.parse().context("invalid historical timestamp")?;
    // Ensure UTC conversion did not leave the supported four-digit year range.
    let utc = DateTimePrinter::new().timestamp_to_string(&ts);
    if !utc.as_bytes()[..4].iter().all(u8::is_ascii_digit) {
        bail!("UTC year outside prototype compatibility envelope");
    }
    Ok(ts)
}

fn auto_si(ts: Timestamp) -> u8 {
    // Euclidean fraction is necessary before 1970: Jiff's subsec accessor is signed.
    let n = ts.as_nanosecond().rem_euclid(1_000_000_000);
    if n == 0 {
        0
    } else if n % 1_000_000 == 0 {
        3
    } else if n % 1_000 == 0 {
        6
    } else {
        9
    }
}

/// Match chrono DateTime<Utc>::to_rfc3339(): AutoSi and +00:00.
pub fn persisted(ts: Timestamp) -> String {
    DateTimePrinter::new()
        .precision(Some(auto_si(ts)))
        .timestamp_with_offset_to_string(&ts, Offset::UTC)
}

/// Match chrono DateTime<Utc> serde value (caller provides JSON string quoting).
pub fn serde_timestamp(ts: Timestamp) -> String {
    DateTimePrinter::new()
        .precision(Some(auto_si(ts)))
        .timestamp_to_string(&ts)
}

/// Match zeroclaw-log's RFC3339 Millis/use_z=true boundary (truncate, not round).
pub fn log_timestamp(ts: Timestamp) -> String {
    DateTimePrinter::new()
        .precision(Some(3))
        .timestamp_to_string(&ts)
}

/// Named zones use bundled tzdb. None explicitly discovers the system zone;
/// lookup failure is an error, NOT a silent UTC fallback. Platform parity pending.
pub fn localized(ts: Timestamp, name: Option<&str>) -> Result<Zoned> {
    let zone = match name {
        Some(name) => TimeZone::get(name).context("invalid IANA timezone")?,
        None => TimeZone::try_system().context("system timezone unavailable")?,
    };
    Ok(ts.to_zoned(zone))
}

fn candidate_cron(expr: &str) -> Result<croner::Cron> {
    let normalized = normalization::normalize_expression(expr)?;
    let cron = CronParser::builder()
        .seconds(Seconds::Required)
        .year(Year::Optional)
        .alternative_weekdays(true)
        .dom_and_dow(true)
        .sloppy_ranges(true)
        .build()
        .parse(&normalized)
        .context("candidate cron parse")?;
    Ok(cron)
}

/// Unadapted Croner comparison, retained to demonstrate the spring-gap mismatch.
pub fn raw_candidate_next(expr: &str, zone: Option<&str>, from: Timestamp) -> Result<Timestamp> {
    let cron = candidate_cron(expr)?;
    Ok(cron
        .find_next_occurrence(&localized(from, zone)?, false)?
        .timestamp())
}

/// Skip nonexistent wall-time occurrences, as cron 0.15 does. Croner fold
/// semantics are deliberately retained; this is not a full compatibility claim.
pub fn candidate_next(expr: &str, zone: Option<&str>, from: Timestamp) -> Result<Timestamp> {
    let cron = candidate_cron(expr)?;
    let mut cursor = localized(from, zone)?;
    loop {
        let next = cron.find_next_occurrence(&cursor, false)?;
        if cron.is_time_matching(&next)? {
            return Ok(next.timestamp());
        }
        // Croner 4.0.3 can return a nonmatching wall time only when it carries a
        // fixed-time occurrence across a gap to its first real instant. Reject
        // that synthetic occurrence, not the entire transition day. A genuine
        // boundary match (e.g. 03:00) is accepted above, including wildcard jobs.
        // Resume exclusively at the rejected instant: no real scheduled time
        // lies in the gap, and the boundary itself did not match. No date/offset
        // assumptions, scanning, or arbitrary retry budget are needed.
        if next.timestamp() <= cursor.timestamp() {
            bail!("candidate gap search did not advance");
        }
        cursor = next;
    }
}

/// Elapsed Every semantics, not calendar arithmetic. Original At simply returns
/// its instant; validation that it is future remains a separate application gate.
pub fn every(from: Timestamp, milliseconds: u64) -> Result<Timestamp> {
    if milliseconds == 0 {
        bail!("every_ms must be > 0");
    }
    let ms = i64::try_from(milliseconds).context("every_ms too large")?;
    Ok(from.checked_add(std::time::Duration::from_millis(ms as u64))?)
}
