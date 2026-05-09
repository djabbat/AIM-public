//! aim-follow-up-generator — auto-draft polite follow-up emails (E1).
//!
//! Port of `agents/follow_up_generator.py`. Pulls every overdue
//! stakeholder from [`aim_stakeholder_tracker`], renders a polite,
//! short follow-up email per contact. Drafts are returned as data —
//! the host (email_agent in Python; teloxide / Gmail MCP in Rust)
//! decides whether to save them as Gmail DRAFTs.
//!
//! ## Hard rules baked into the templates
//! - Never invent past correspondence. The body references "my last
//!   email on <date>" and we plug `last_contact_at` from the DB.
//! - Always close with the user's name (`AIM_USER_NAME` family) +
//!   a soft re-ping question, never an ultimatum.
//! - Language picker: detect from contact's role/notes/email — KA
//!   for Georgian script or `tsu.ge` domains, RU for Cyrillic +
//!   Tbilisi/Russia hints, EN otherwise.
//! - Subject line: concise, ≤78 chars.

use aim_stakeholder_tracker::Contact;
use chrono::NaiveDate;
use regex::Regex;
use serde::{Deserialize, Serialize};
use std::sync::OnceLock;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Lang {
    En,
    Ru,
    Ka,
}

impl Lang {
    pub fn as_str(self) -> &'static str {
        match self {
            Lang::En => "en",
            Lang::Ru => "ru",
            Lang::Ka => "ka",
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Draft {
    pub contact_name: String,
    pub contact_email: Option<String>,
    pub subject: String,
    pub body: String,
    pub lang: Lang,
    pub days_silent: i64,
}

static RU_HINT: OnceLock<Regex> = OnceLock::new();
static KA_HINT: OnceLock<Regex> = OnceLock::new();

fn ru_hint() -> &'static Regex {
    RU_HINT.get_or_init(|| Regex::new(r"[А-Яа-яЁё]").unwrap())
}
fn ka_hint() -> &'static Regex {
    KA_HINT.get_or_init(|| Regex::new(r"[\u{10A0}-\u{10FF}]").unwrap())
}

pub fn detect_lang(contact: &Contact) -> Lang {
    let blob = format!(
        "{} {} {}",
        contact.role.clone().unwrap_or_default(),
        contact.notes.clone().unwrap_or_default(),
        contact.email.clone().unwrap_or_default()
    );
    let email = contact.email.as_deref().unwrap_or("");
    if ka_hint().is_match(&blob) || email.contains("tsu.ge") {
        return Lang::Ka;
    }
    let notes = contact.notes.as_deref().unwrap_or("");
    let ru_keywords =
        ["Tbilisi", "Тбилиси", "Грузия", "Russia"].iter().any(|s| notes.contains(s));
    if ru_hint().is_match(&blob) || ru_keywords {
        return Lang::Ru;
    }
    Lang::En
}

#[derive(Debug, Clone)]
pub struct UserName {
    pub en: String,
    pub ru: String,
    pub ka: String,
}

impl Default for UserName {
    fn default() -> Self {
        Self::from_env()
    }
}

impl UserName {
    pub fn from_env() -> Self {
        Self {
            en: std::env::var("AIM_USER_NAME").unwrap_or_else(|_| "Jaba Tkemaladze".into()),
            ru: std::env::var("AIM_USER_NAME_RU")
                .unwrap_or_else(|_| "Джаба Ткемаладзе".into()),
            ka: std::env::var("AIM_USER_NAME_KA")
                .unwrap_or_else(|_| "ჯაბა ტყემალაძე".into()),
        }
    }

    pub fn for_lang(&self, lang: Lang) -> &str {
        match lang {
            Lang::En => &self.en,
            Lang::Ru => &self.ru,
            Lang::Ka => &self.ka,
        }
    }
}

fn first_name(full: &str) -> String {
    full.trim()
        .split_whitespace()
        .next()
        .unwrap_or("")
        .to_string()
}

fn fmt_topic(contact: &Contact, max_chars: usize) -> String {
    let note = contact.notes.as_deref().unwrap_or("").trim();
    if !note.is_empty() {
        // First phrase / sentence — split on .;\n
        let first = note
            .split(|c: char| matches!(c, '.' | ';' | '\n'))
            .next()
            .unwrap_or("");
        let first = first.trim().trim_start_matches(|c: char| {
            matches!(c, '*' | '•' | '—' | '-' | ' ')
        });
        if !first.is_empty() {
            return first.chars().take(max_chars).collect();
        }
    }
    let role = contact.role.as_deref().unwrap_or("").trim();
    if !role.is_empty() {
        return role.chars().take(max_chars).collect();
    }
    String::new()
}

fn default_topic(lang: Lang) -> &'static str {
    match lang {
        Lang::En => "the project we discussed",
        Lang::Ru => "обсуждаемый проект",
        Lang::Ka => "საერთო პროექტი",
    }
}

fn template(lang: Lang) -> (&'static str, &'static str) {
    match lang {
        Lang::En => (
            "Quick follow-up — {topic}",
            "Dear {first_name},\n\n\
             Hope you're well. I wanted to gently check in on my last \
             email from {last_contact} about {topic}; I haven't heard \
             back yet ({days} days), so I want to make sure it didn't \
             land in spam or fall through.\n\n\
             If you need more time, please just say so — happy to wait. \
             And if it's easier to chat briefly, let me know a slot that \
             works for you.\n\nBest,\n{user_name}",
        ),
        Lang::Ru => (
            "Небольшое напоминание — {topic}",
            "Уважаемый(ая) {first_name},\n\n\
             Надеюсь, всё хорошо. Хотел вежливо напомнить о письме \
             от {last_contact} по теме «{topic}»; пока не получил \
             ответа ({days} дн.), хочу убедиться, что письмо не \
             попало в спам.\n\n\
             Если нужно больше времени — напишите, пожалуйста, я подожду. \
             Если удобнее коротко обсудить голосом, скажите слот.\n\n\
             С уважением,\n{user_name}",
        ),
        Lang::Ka => (
            "მოკლე შეხსენება — {topic}",
            "ძვირფასო {first_name},\n\n\
             ვიმედოვნებ, ყველაფერი კარგად არის. მინდა თავაზიანად \
             შეგახსენოთ ჩემი წერილის შესახებ {last_contact} თარიღით — \
             თემაზე «{topic}»; ჯერ პასუხი არ მიმიღია ({days} დღე), \
             მინდა დავრწმუნდე, რომ წერილი სპამში არ მოხვდა.\n\n\
             თუ მეტი დრო გჭირდებათ — გთხოვთ მაცნობოთ, ველოდები. \
             თუ უფრო მოსახერხებელია ხანმოკლე ზარი, მითხარით ხელსაყრელი დრო.\n\n\
             პატივისცემით,\n{user_name}",
        ),
    }
}

fn render(template: &str, vars: &[(&str, &str)]) -> String {
    let mut out = template.to_string();
    for (k, v) in vars {
        out = out.replace(&format!("{{{k}}}"), v);
    }
    out
}

/// Build a [`Draft`] for one overdue contact. Returns `None` when no
/// email address is set (we never draft to a name-only contact).
pub fn generate(
    contact: &Contact,
    today: NaiveDate,
    user_name: &UserName,
) -> Option<Draft> {
    if contact.email.as_deref().filter(|s| !s.is_empty()).is_none() {
        return None;
    }
    let lang = detect_lang(contact);
    let (subj_tpl, body_tpl) = template(lang);
    let topic_buf = fmt_topic(contact, 60);
    let topic: &str = if topic_buf.is_empty() {
        default_topic(lang)
    } else {
        &topic_buf
    };
    let last_contact = contact
        .last_contact_at
        .as_deref()
        .unwrap_or(match lang {
            Lang::En => "the past few weeks",
            Lang::Ru => "последних недель",
            Lang::Ka => "ბოლო კვირების",
        });
    let last_contact_short: String = last_contact.chars().take(10).collect();
    let first = first_name(&contact.name);
    let days = contact.days_silent(today).unwrap_or(0).max(0);
    let days_str = days.to_string();
    let user = user_name.for_lang(lang).to_string();

    let subject_full = render(subj_tpl, &[("topic", topic)]);
    let subject: String = subject_full.chars().take(78).collect();
    let body = render(
        body_tpl,
        &[
            ("first_name", &first),
            ("last_contact", &last_contact_short),
            ("topic", topic),
            ("days", &days_str),
            ("user_name", &user),
        ],
    );

    Some(Draft {
        contact_name: contact.name.clone(),
        contact_email: contact.email.clone(),
        subject,
        body,
        lang,
        days_silent: days,
    })
}

/// Generate drafts for every overdue contact in the supplied list.
pub fn generate_all(
    contacts: &[Contact],
    today: NaiveDate,
    user_name: &UserName,
) -> Vec<Draft> {
    contacts
        .iter()
        .filter_map(|c| generate(c, today, user_name))
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn contact_with(
        name: &str,
        email: Option<&str>,
        role: Option<&str>,
        notes: Option<&str>,
        last_contact: Option<&str>,
        expected_response: Option<&str>,
    ) -> Contact {
        Contact {
            id: 1,
            name: name.into(),
            email: email.map(String::from),
            role: role.map(String::from),
            project: None,
            last_contact_at: last_contact.map(String::from),
            awaiting_reply: true,
            expected_response_by: expected_response.map(String::from),
            notes: notes.map(String::from),
        }
    }

    fn user() -> UserName {
        UserName {
            en: "Jaba Tkemaladze".into(),
            ru: "Джаба Ткемаладзе".into(),
            ka: "ჯაბა ტყემალაძე".into(),
        }
    }

    #[test]
    fn detect_lang_en_default() {
        let c = contact_with("Geiger", Some("g@ulm.de"), Some("Co-PI"), None, None, None);
        assert_eq!(detect_lang(&c), Lang::En);
    }

    #[test]
    fn detect_lang_ka_via_tsu_domain() {
        let c = contact_with(
            "Dzidziguri",
            Some("diana.dzidziguri@tsu.ge"),
            Some("PhD director"),
            None,
            None,
            None,
        );
        assert_eq!(detect_lang(&c), Lang::Ka);
    }

    #[test]
    fn detect_lang_ka_via_georgian_text() {
        let c = contact_with(
            "Aleksandre",
            Some("a@example.com"),
            Some("ფაკულტეტი"),
            None,
            None,
            None,
        );
        assert_eq!(detect_lang(&c), Lang::Ka);
    }

    #[test]
    fn detect_lang_ru_via_cyrillic_role() {
        let c = contact_with("Лежава", Some("l@y.com"), Some("Co-PI Тбилиси"), None, None, None);
        assert_eq!(detect_lang(&c), Lang::Ru);
    }

    #[test]
    fn detect_lang_ru_via_tbilisi_keyword() {
        let c = contact_with("Smith", Some("s@x.com"), Some("PI"), Some("Tbilisi node"), None, None);
        assert_eq!(detect_lang(&c), Lang::Ru);
    }

    #[test]
    fn no_email_returns_none() {
        let c = contact_with("Anonymous", None, None, None, None, None);
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        assert!(generate(&c, today, &user()).is_none());
    }

    #[test]
    fn generate_en_basic() {
        let c = contact_with(
            "Hartmut Geiger",
            Some("g@ulm.de"),
            Some("Co-PI Phase B"),
            Some("LoS signed"),
            Some("2026-04-23"),
            Some("2026-04-30"),
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 7).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert_eq!(d.lang, Lang::En);
        assert_eq!(d.contact_email.as_deref(), Some("g@ulm.de"));
        assert!(d.subject.contains("LoS signed"));
        assert!(d.body.contains("Hartmut"));
        assert!(d.body.contains("2026-04-23"));
        assert!(d.body.contains("Jaba Tkemaladze"));
        assert!(d.body.contains("14 days") || d.body.contains("(14"));
    }

    #[test]
    fn generate_ru_basic() {
        let c = contact_with(
            "Ivan Petrov",
            Some("ip@example.ru"),
            Some("Co-PI Тбилиси"),
            Some("обсуждение бюджета"),
            Some("2026-04-25"),
            Some("2026-05-01"),
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert_eq!(d.lang, Lang::Ru);
        assert!(d.subject.contains("обсуждение бюджета"));
        assert!(d.body.contains("Ivan"));
        assert!(d.body.contains("Джаба Ткемаладзе"));
    }

    #[test]
    fn generate_ka_via_tsu_domain() {
        let c = contact_with(
            "Diana",
            Some("diana@tsu.ge"),
            Some("PhD director"),
            None,
            Some("2026-04-29"),
            Some("2026-05-04"),
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 11).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert_eq!(d.lang, Lang::Ka);
        assert!(d.body.contains("ჯაბა ტყემალაძე"));
    }

    #[test]
    fn topic_falls_back_to_role_when_no_notes() {
        let c = contact_with(
            "Geiger",
            Some("g@ulm.de"),
            Some("Co-PI Phase B"),
            None,
            Some("2026-04-23"),
            Some("2026-04-30"),
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert!(d.subject.contains("Co-PI Phase B"));
    }

    #[test]
    fn topic_uses_default_when_no_notes_no_role() {
        let c = contact_with("Geiger", Some("g@ulm.de"), None, None, None, None);
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert!(d.subject.contains("the project we discussed"));
    }

    #[test]
    fn first_name_extracts_token() {
        assert_eq!(first_name("Hartmut Geiger"), "Hartmut");
        assert_eq!(first_name("  Diana  Dzidziguri  "), "Diana");
        assert_eq!(first_name(""), "");
    }

    #[test]
    fn topic_truncates_at_max_chars() {
        let long_note = "x".repeat(200);
        let c = contact_with(
            "X",
            Some("x@x.com"),
            Some("role"),
            Some(&long_note),
            None,
            None,
        );
        let topic = fmt_topic(&c, 60);
        assert_eq!(topic.chars().count(), 60);
    }

    #[test]
    fn topic_strips_bullet_prefixes() {
        let c = contact_with(
            "X",
            Some("x@x.com"),
            None,
            Some("• weekly sync"),
            None,
            None,
        );
        let topic = fmt_topic(&c, 60);
        assert_eq!(topic, "weekly sync");
    }

    #[test]
    fn subject_capped_at_78_chars() {
        let long_topic = "y".repeat(200);
        let c = contact_with(
            "X",
            Some("x@x.com"),
            None,
            Some(&long_topic),
            None,
            None,
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert!(d.subject.chars().count() <= 78);
    }

    #[test]
    fn days_silent_clamped_to_zero_when_negative() {
        let c = contact_with(
            "X",
            Some("x@x.com"),
            Some("role"),
            None,
            Some("2027-01-01"),
            Some("2026-05-01"),
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert_eq!(d.days_silent, 0);
    }

    #[test]
    fn last_contact_short_truncates_iso_datetime() {
        let c = contact_with(
            "X",
            Some("x@x.com"),
            None,
            Some("budget"),
            Some("2026-04-23T09:00:00"),
            None,
        );
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let d = generate(&c, today, &user()).unwrap();
        assert!(d.body.contains("2026-04-23"));
        assert!(!d.body.contains("T09:00:00"));
    }

    #[test]
    fn generate_all_filters_email_less_contacts() {
        let cs = vec![
            contact_with("WithMail", Some("a@x.com"), Some("role"), None, None, None),
            contact_with("NoMail", None, Some("role"), None, None, None),
        ];
        let today = NaiveDate::from_ymd_opt(2026, 5, 4).unwrap();
        let drafts = generate_all(&cs, today, &user());
        assert_eq!(drafts.len(), 1);
        assert_eq!(drafts[0].contact_name, "WithMail");
    }

    #[test]
    fn user_name_picks_per_lang() {
        let u = user();
        assert_eq!(u.for_lang(Lang::En), "Jaba Tkemaladze");
        assert_eq!(u.for_lang(Lang::Ru), "Джаба Ткемаладзе");
        assert_eq!(u.for_lang(Lang::Ka), "ჯაბა ტყემალაძე");
    }
}
