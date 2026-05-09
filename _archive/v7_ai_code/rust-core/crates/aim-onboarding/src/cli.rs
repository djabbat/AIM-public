//! Terminal interview loop. Plain stdin/stdout — no rustyline dep, keeps the
//! crate light. Suitable for `aim-onboard` and for shelling out from Phoenix.

use crate::answer::*;
use crate::error::Result;
use crate::session::Session;
use crate::template::{Question, QuestionType};
use std::io::{BufRead, Write};

pub fn run<R: BufRead, W: Write>(
    session: &mut Session,
    input: &mut R,
    output: &mut W,
) -> Result<()> {
    writeln!(output, "=== {} ===", session.template.title)?;
    if !session.template.intent.is_empty() {
        writeln!(output, "{}\n", session.template.intent)?;
    }

    let questions = session.template.questions.clone();
    for q in &questions {
        if !session.should_ask(q) {
            continue;
        }
        let answer = ask(q, input, output)?;
        Session::validate_answer(q, &answer)?;
        session.answers.set(q.id.clone(), answer);
    }
    Ok(())
}

fn ask<R: BufRead, W: Write>(q: &Question, input: &mut R, output: &mut W) -> Result<Answer> {
    let suffix = if q.required {
        " *"
    } else if q.optional {
        " (опц.)"
    } else {
        ""
    };

    match q.kind {
        QuestionType::Text => {
            write!(output, "? {}{}: ", q.prompt, suffix)?;
            output.flush()?;
            if q.multiline {
                let lines = read_multiline(input)?;
                Ok(Answer::Text(lines.join("\n")))
            } else {
                let s = read_line(input)?;
                if s.is_empty() {
                    Ok(if let Some(d) = &q.default {
                        Answer::Text(d.clone())
                    } else {
                        Answer::Empty
                    })
                } else {
                    Ok(Answer::Text(s))
                }
            }
        }
        QuestionType::Choice => {
            writeln!(output, "? {}{}", q.prompt, suffix)?;
            for (i, opt) in q.options.iter().enumerate() {
                writeln!(output, "  {}) {}", i + 1, opt)?;
            }
            write!(output, "  > ")?;
            output.flush()?;
            let s = read_line(input)?;
            if s.is_empty() {
                return Ok(Answer::Empty);
            }
            let idx: usize = s.parse().unwrap_or(0);
            if (1..=q.options.len()).contains(&idx) {
                Ok(Answer::Text(q.options[idx - 1].clone()))
            } else if q.options.contains(&s) {
                Ok(Answer::Text(s))
            } else {
                Ok(Answer::Text(s))
            }
        }
        QuestionType::MultiChoice => {
            writeln!(output, "? {}{} (через пробел)", q.prompt, suffix)?;
            for (i, opt) in q.options.iter().enumerate() {
                writeln!(output, "  {}) {}", i + 1, opt)?;
            }
            write!(output, "  > ")?;
            output.flush()?;
            let s = read_line(input)?;
            if s.is_empty() {
                return Ok(Answer::Empty);
            }
            let mut chosen = Vec::new();
            for tok in s.split_whitespace() {
                if let Ok(idx) = tok.parse::<usize>() {
                    if (1..=q.options.len()).contains(&idx) {
                        chosen.push(q.options[idx - 1].clone());
                    }
                } else if q.options.iter().any(|o| o == tok) {
                    chosen.push(tok.to_string());
                }
            }
            Ok(Answer::List(chosen))
        }
        QuestionType::List => {
            writeln!(output, "? {}{} (по строке, пустая — конец)", q.prompt, suffix)?;
            let lines = read_multiline(input)?;
            if lines.is_empty() {
                Ok(Answer::Empty)
            } else if lines.iter().any(|l| l.contains('=')) {
                let kvs = lines
                    .into_iter()
                    .filter_map(|l| {
                        let (n, v) = l.split_once('=')?;
                        Some(NameValue {
                            name: n.trim().to_string(),
                            value: v.trim().to_string(),
                        })
                    })
                    .collect();
                Ok(Answer::NameValueList(kvs))
            } else {
                Ok(Answer::List(lines))
            }
        }
        QuestionType::Number => {
            write!(output, "? {}{}: ", q.prompt, suffix)?;
            output.flush()?;
            let s = read_line(input)?;
            if s.is_empty() {
                Ok(Answer::Empty)
            } else {
                let n: f64 = s
                    .parse()
                    .map_err(|_| crate::error::OnboardError::Validation(format!("`{s}` is not a number")))?;
                Ok(Answer::Number(n))
            }
        }
        QuestionType::Bool => {
            write!(output, "? {}{} [y/N]: ", q.prompt, suffix)?;
            output.flush()?;
            let s = read_line(input)?;
            Ok(Answer::Bool(matches!(s.to_lowercase().as_str(), "y" | "yes" | "да" | "д" | "1")))
        }
        QuestionType::Date => {
            write!(output, "? {}{} (YYYY-MM-DD): ", q.prompt, suffix)?;
            output.flush()?;
            let s = read_line(input)?;
            Ok(Answer::Text(s))
        }
    }
}

fn read_line<R: BufRead>(input: &mut R) -> Result<String> {
    let mut s = String::new();
    input.read_line(&mut s)?;
    Ok(s.trim_end_matches(['\r', '\n']).to_string())
}

fn read_multiline<R: BufRead>(input: &mut R) -> Result<Vec<String>> {
    let mut lines = Vec::new();
    loop {
        let mut s = String::new();
        if input.read_line(&mut s)? == 0 {
            break;
        }
        let line = s.trim_end_matches(['\r', '\n']).to_string();
        if line.is_empty() {
            break;
        }
        lines.push(line);
    }
    Ok(lines)
}
