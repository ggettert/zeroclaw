use chrono::{DateTime, SecondsFormat, Utc};
use chrono_free_feasibility::{every, log_timestamp, parse_persisted, persisted, serde_timestamp};
use serde::Deserialize;

#[derive(Deserialize)]
struct Case {
    id: String,
    input: String,
    persisted: String,
    serde: String,
    log: String,
}
fn cases() -> Vec<Case> {
    serde_json::from_str(include_str!("../fixtures/timestamps.json")).unwrap()
}

#[test]
fn historical_bytes_match_pinned_chrono_oracle() {
    for c in cases() {
        let old = DateTime::parse_from_rfc3339(&c.input)
            .unwrap()
            .with_timezone(&Utc);
        let new = parse_persisted(&c.input).unwrap();
        // Establish the frozen golden against the old implementation first.
        assert_eq!(old.to_rfc3339(), c.persisted, "old store {}", c.id);
        assert_eq!(
            serde_json::to_value(old).unwrap(),
            c.serde,
            "old serde {}",
            c.id
        );
        assert_eq!(
            old.to_rfc3339_opts(SecondsFormat::Millis, true),
            c.log,
            "old log {}",
            c.id
        );
        assert_eq!(persisted(new), c.persisted, "new store {}", c.id);
        assert_eq!(serde_timestamp(new), c.serde, "new serde {}", c.id);
        assert_eq!(log_timestamp(new), c.log, "new log {}", c.id);
        assert_eq!(parse_persisted(&c.persisted).unwrap(), new);
        assert_eq!(parse_persisted(&c.serde).unwrap(), new);
    }
}

#[test]
fn at_json_boundary_preserves_timestamp_value() {
    #[derive(serde::Serialize)]
    #[serde(tag = "kind", rename_all = "lowercase")]
    enum OldSchedule {
        At { at: DateTime<Utc> },
    }
    for c in cases() {
        let at = DateTime::parse_from_rfc3339(&c.input)
            .unwrap()
            .with_timezone(&Utc);
        let old = serde_json::to_string(&OldSchedule::At { at }).unwrap();
        let new = format!(
            "{{\"kind\":\"at\",\"at\":{}}}",
            serde_json::to_string(&serde_timestamp(parse_persisted(&c.input).unwrap())).unwrap()
        );
        assert_eq!(new, old);
    }
}

#[test]
fn mixed_old_new_text_sort_and_due_predicate_are_unchanged() {
    // Same strings imply identical SQLite BINARY ordering and <= predicates.
    // This is not a database integration test and does NOT claim AutoSi sorts
    // chronologically for every mixed-precision history.
    let rows = cases();
    let old: Vec<_> = rows
        .iter()
        .map(|c| {
            DateTime::parse_from_rfc3339(&c.input)
                .unwrap()
                .with_timezone(&Utc)
                .to_rfc3339()
        })
        .collect();
    let mixed: Vec<_> = rows
        .iter()
        .enumerate()
        .map(|(i, c)| {
            if i % 2 == 0 {
                old[i].clone()
            } else {
                persisted(parse_persisted(&c.input).unwrap())
            }
        })
        .collect();
    for now in &old {
        let mut old_due: Vec<_> = old.iter().filter(|s| *s <= now).cloned().collect();
        let mut mixed_due: Vec<_> = mixed.iter().filter(|s| *s <= now).cloned().collect();
        old_due.sort();
        mixed_due.sort();
        assert_eq!(old_due, mixed_due);
    }
}

#[test]
fn unsupported_forms_are_explicit_not_silently_normalized() {
    for raw in [
        "2016-12-31T23:59:60Z",
        "+010000-01-01T00:00:00Z",
        "2024-01-01T00:00:00Z[UTC]",
        "junk",
        "2024-01-01T00:00:00.1234567890Z",
        "2024-01-01T00:00:00+0000",
        "2024-01-01T00:00:0éZ",
    ] {
        assert!(parse_persisted(raw).is_err(), "{raw}");
    }
}

#[test]
fn elapsed_every_checks_zero_integer_and_timestamp_overflow() {
    let from = parse_persisted("2024-03-10T09:30:00Z").unwrap();
    assert_eq!(
        serde_timestamp(every(from, 3_600_000).unwrap()),
        "2024-03-10T10:30:00Z"
    );
    assert!(every(from, 0).is_err());
    assert!(every(from, u64::MAX).is_err());
    assert!(every(jiff::Timestamp::MAX, 1).is_err());
}
