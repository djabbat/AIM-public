//! Lightweight Tera-style placeholder renderer.
//!
//! Supports:
//!   `{{var}}`       — substitute scalar.
//!   `{% if x %} … {% endif %}` — gate on truthiness.
//!   `{% for kv in params %} … {{kv.name}} {{kv.value}} … {% endfor %}` — list loop with
//!     dotted-property access for `NameValueList`.
//!   `{% for v in xs %} … {{v}} … {% endfor %}` — plain list loop.
//!
//! Not full Tera; deliberately small (no Cargo dep on `tera`/`handlebars`).

use crate::answer::Answer;
use crate::error::{OnboardError, Result};
use std::collections::BTreeMap;

pub fn render(template: &str, vars: &BTreeMap<String, Answer>) -> Result<String> {
    let mut out = template.to_string();
    out = expand_for(&out, vars)?;
    out = expand_if(&out, vars)?;
    out = expand_simple(&out, vars)?;
    Ok(out)
}

fn expand_simple(s: &str, vars: &BTreeMap<String, Answer>) -> Result<String> {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(start) = rest.find("{{") {
        out.push_str(&rest[..start]);
        let after = &rest[start + 2..];
        let end = match after.find("}}") {
            Some(e) => e,
            None => return Err(OnboardError::Template("unmatched {{".into())),
        };
        let key = after[..end].trim();
        let value = vars
            .get(key)
            .map(|a| a.flat_string())
            .unwrap_or_default();
        out.push_str(&value);
        rest = &after[end + 2..];
    }
    out.push_str(rest);
    Ok(out)
}

fn expand_if(s: &str, vars: &BTreeMap<String, Answer>) -> Result<String> {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(start) = rest.find("{% if ") {
        out.push_str(&rest[..start]);
        let after = &rest[start..];
        let head_end = match after.find(" %}") {
            Some(e) => e,
            None => return Err(OnboardError::Template("unmatched {% if".into())),
        };
        let cond = after[6..head_end].trim().to_string();
        let body_start = head_end + 3;
        let endif = match after[body_start..].find("{% endif %}") {
            Some(e) => e,
            None => return Err(OnboardError::Template("missing {% endif %}".into())),
        };
        let body = &after[body_start..body_start + endif];
        let after_body = &after[body_start + endif + "{% endif %}".len()..];
        let truthy = vars
            .get(cond.as_str())
            .map(|a| a.is_truthy())
            .unwrap_or(false);
        if truthy {
            // Recurse: nested `{% if %}` / `{% for %}` inside body should also expand.
            let nested = expand_for(body, vars)?;
            let nested = expand_if(&nested, vars)?;
            out.push_str(&nested);
        }
        rest = after_body;
    }
    out.push_str(rest);
    Ok(out)
}

fn expand_for(s: &str, vars: &BTreeMap<String, Answer>) -> Result<String> {
    let mut out = String::with_capacity(s.len());
    let mut rest = s;
    while let Some(start) = rest.find("{% for ") {
        out.push_str(&rest[..start]);
        let after = &rest[start..];
        let head_end = match after.find(" %}") {
            Some(e) => e,
            None => return Err(OnboardError::Template("unmatched {% for".into())),
        };
        let head = after[7..head_end].trim().to_string();
        let mut parts = head.splitn(3, ' ');
        let var = parts
            .next()
            .ok_or_else(|| OnboardError::Template("for: missing var".into()))?;
        let kw = parts
            .next()
            .ok_or_else(|| OnboardError::Template("for: missing 'in'".into()))?;
        if kw != "in" {
            return Err(OnboardError::Template(format!(
                "for: expected 'in', got '{kw}'"
            )));
        }
        let coll = parts
            .next()
            .ok_or_else(|| OnboardError::Template("for: missing collection".into()))?
            .trim();

        let body_start = head_end + 3;
        let endfor = match after[body_start..].find("{% endfor %}") {
            Some(e) => e,
            None => return Err(OnboardError::Template("missing {% endfor %}".into())),
        };
        let body = &after[body_start..body_start + endfor];
        let after_body = &after[body_start + endfor + "{% endfor %}".len()..];

        let collection = vars.get(coll);
        let mut rendered_iter = String::new();
        if let Some(c) = collection {
            match c {
                Answer::List(xs) => {
                    for x in xs {
                        let mut local = vars.clone();
                        local.insert(var.to_string(), Answer::Text(x.clone()));
                        let one = expand_simple(body, &local)?;
                        rendered_iter.push_str(&one);
                    }
                }
                Answer::NameValueList(kvs) => {
                    for kv in kvs {
                        let mut local = vars.clone();
                        local.insert(format!("{var}.name"), Answer::Text(kv.name.clone()));
                        local.insert(format!("{var}.value"), Answer::Text(kv.value.clone()));
                        local.insert(var.to_string(), Answer::Text(kv.name.clone()));
                        let one = expand_simple(body, &local)?;
                        rendered_iter.push_str(&one);
                    }
                }
                _ => {}
            }
        }
        out.push_str(&rendered_iter);
        rest = after_body;
    }
    out.push_str(rest);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::answer::*;

    fn vars(pairs: &[(&str, Answer)]) -> BTreeMap<String, Answer> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.clone())).collect()
    }

    #[test]
    fn simple_substitution() {
        let v = vars(&[("name", Answer::Text("World".into()))]);
        assert_eq!(render("Hello {{name}}!", &v).unwrap(), "Hello World!");
    }

    #[test]
    fn if_block_truthy() {
        let v = vars(&[("flag", Answer::Bool(true))]);
        assert_eq!(
            render("a{% if flag %}+yes{% endif %}b", &v).unwrap(),
            "a+yesb"
        );
    }

    #[test]
    fn if_block_falsy_skips() {
        let v = vars(&[("flag", Answer::Bool(false))]);
        assert_eq!(render("a{% if flag %}NO{% endif %}b", &v).unwrap(), "ab");
    }

    #[test]
    fn for_list() {
        let v = vars(&[("xs", Answer::List(vec!["a".into(), "b".into()]))]);
        let out = render("{% for v in xs %}<{{v}}>{% endfor %}", &v).unwrap();
        assert_eq!(out, "<a><b>");
    }

    #[test]
    fn for_namevalue_list() {
        let v = vars(&[(
            "params",
            Answer::NameValueList(vec![
                NameValue {
                    name: "alpha".into(),
                    value: "0.0082".into(),
                },
                NameValue {
                    name: "beta".into(),
                    value: "0.005".into(),
                },
            ]),
        )]);
        let out = render(
            "{% for kv in params %}|{{kv.name}}={{kv.value}}{% endfor %}",
            &v,
        )
        .unwrap();
        assert_eq!(out, "|alpha=0.0082|beta=0.005");
    }
}
