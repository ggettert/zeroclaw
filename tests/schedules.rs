use chrono::{DateTime, Utc};
use chrono_free_feasibility::{
    candidate_next, localized, normalization::normalize_expression, parse_persisted,
    serde_timestamp,
};
use serde::Deserialize;
use std::str::FromStr;

#[derive(Deserialize)]
struct Case {
    id: String,
    expr: String,
    zone: String,
    from: String,
    baseline: String,
    candidate: String,
}
fn cases() -> Vec<Case> {
    serde_json::from_str(include_str!("../fixtures/schedules.json")).unwrap()
}
fn utc(s: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(s).unwrap().with_timezone(&Utc)
}

// The application entry point creates a FRESH iterator and calls .next() once.
// Do not replace this oracle with .take(n): folds behave differently.
fn old_next(expr: &str, zone: &str, from: &str) -> DateTime<Utc> {
    let schedule = cron::Schedule::from_str(&normalize_expression(expr).unwrap()).unwrap();
    let tz = chrono_tz::Tz::from_str(zone).unwrap();
    schedule
        .after(&utc(from).with_timezone(&tz))
        .next()
        .unwrap()
        .with_timezone(&Utc)
}

#[test]
fn characterize_application_one_shot_scheduler_and_candidate() {
    for c in cases() {
        let old = old_next(&c.expr, &c.zone, &c.from);
        assert_eq!(old, utc(&c.baseline), "source-derived baseline {}", c.id);
        let new =
            candidate_next(&c.expr, Some(&c.zone), parse_persisted(&c.from).unwrap()).unwrap();
        assert_eq!(
            new,
            parse_persisted(&c.candidate).unwrap(),
            "source-derived candidate {}",
            c.id
        );
        eprintln!(
            "{}: old={} candidate={} compatible={}",
            c.id,
            old,
            new,
            c.baseline == c.candidate
        );
        // This test intentionally records mismatches; passing is NOT full parity.
        if c.baseline == c.candidate {
            assert_eq!(serde_timestamp(new), c.baseline);
        }
    }
}

#[test]
fn retained_iterator_fold_is_not_application_repeated_calls() {
    let expr = "0 30 1 * * *";
    let tz = chrono_tz::America::Los_Angeles;
    let start = utc("2024-11-03T07:00:00Z").with_timezone(&tz);
    let schedule = cron::Schedule::from_str(expr).unwrap();
    let actual: Vec<_> = schedule
        .after(&start)
        .take(3)
        .map(|d| d.with_timezone(&Utc))
        .collect();
    assert_eq!(
        actual,
        vec![
            utc("2024-11-03T08:30:00Z"),
            utc("2024-11-03T09:30:00Z"),
            utc("2024-11-04T09:30:00Z")
        ]
    );
    assert_eq!(
        old_next(expr, "America/Los_Angeles", "2024-11-03T08:30:00Z"),
        utc("2024-11-04T09:30:00Z")
    );
}

#[test]
fn named_zone_resolves_both_fold_instants_and_rejects_gap() {
    let zone = jiff::tz::TimeZone::get("America/Los_Angeles").unwrap();
    let fold = zone.to_ambiguous_zoned(jiff::civil::date(2024, 11, 3).at(1, 30, 0, 0));
    assert_eq!(
        fold.clone().earlier().unwrap().timestamp(),
        parse_persisted("2024-11-03T08:30:00Z").unwrap()
    );
    assert_eq!(
        fold.later().unwrap().timestamp(),
        parse_persisted("2024-11-03T09:30:00Z").unwrap()
    );
    assert!(
        zone.to_ambiguous_zoned(jiff::civil::date(2024, 3, 10).at(2, 30, 0, 0))
            .unambiguous()
            .is_err()
    );
    assert!(
        localized(
            parse_persisted("2024-01-01T00:00:00Z").unwrap(),
            Some("No/Such_Zone")
        )
        .is_err()
    );
}

#[test]
fn controlled_system_timezone_matches_named_zone_and_old_local() {
    // Set TZ BEFORE launching this test process; never mutate process-wide env
    // inside a parallel Rust harness. Hosted route supplies this variable.
    assert_eq!(std::env::var("TZ").as_deref(), Ok("America/Los_Angeles"));
    let from = "2024-01-15T16:00:00Z";
    let ts = parse_persisted(from).unwrap();
    assert_eq!(
        candidate_next("0 9 * * *", None, ts).unwrap(),
        candidate_next("0 9 * * *", Some("America/Los_Angeles"), ts).unwrap()
    );
    let old = cron::Schedule::from_str("0 0 9 * * *")
        .unwrap()
        .after(&utc(from).with_timezone(&chrono::Local))
        .next()
        .unwrap()
        .with_timezone(&Utc);
    assert_eq!(old, utc("2024-01-15T17:00:00Z"));
}

#[test]
fn production_normalizer_retains_weekday_contract() {
    for (input, expected) in [
        ("0 9 * * 1-5", "0 0 9 * * 2-6"),
        ("0 10 * * 6-7", "0 0 10 * * 1,7"),
        ("0 10 * * 0-7/2", "0 0 10 * * 1,3,5,7"),
        ("0 0 9 * * 1-5", "0 0 9 * * 1-5"),
    ] {
        assert_eq!(normalize_expression(input).unwrap(), expected);
    }
    assert!(normalize_expression("@daily").is_err());
    assert!(normalize_expression("0 10 * * 6-7/0").is_err());
}

#[test]
fn grammar_surface_probes_do_not_silently_claim_parity() {
    let from = parse_persisted("2026-02-16T00:00:00Z").unwrap();
    // Production normalizer accepts 5/6/7 fields, not @nicknames. Croner has
    // additional grammar; those are decision probes, NOT newly approved syntax.
    for expr in [
        "0 9 * * MON-FRI",
        "0 9 * JAN,MAR MON",
        "0 9 1 * MON",
        "0 0/15 * * * *",
        "0 0 9 ? * MON",
        "0 10 * * 6-7",
        "0 10 * * 0",
        "0 10 * * 7",
        "0 0 0 1 1 * 2101",
        "0 0 L * *",
        "0 0 * * MON#2",
        "@daily",
    ] {
        let baseline = normalize_expression(expr)
            .ok()
            .and_then(|s| cron::Schedule::from_str(&s).ok());
        let candidate = candidate_next(expr, Some("UTC"), from);
        eprintln!(
            "grammar {expr:?}: old_parse={} candidate_result={candidate:?}",
            baseline.is_some()
        );
        if let Some(old) = baseline {
            if let Some(old_next) = old.after(&utc("2026-02-16T00:00:00Z")).next() {
                assert_eq!(
                    candidate.unwrap(),
                    parse_persisted(&old_next.to_rfc3339()).unwrap(),
                    "{expr}"
                );
            }
        }
    }
    // Known source-backed expansion: cron ends at 2100, Croner permits 1..5000.
    assert!(cron::Schedule::from_str("0 0 0 1 1 * 2101").is_err());
    assert!(candidate_next("0 0 0 1 1 * 2101", Some("UTC"), from).is_ok());
}
