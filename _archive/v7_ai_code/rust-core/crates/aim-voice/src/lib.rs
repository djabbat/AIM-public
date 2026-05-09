//! aim-voice — voice in/out shim for AIM.
//!
//! Port of `agents/voice.py`. The Python module bundled actual mic
//! recording + faster-whisper + pyttsx3 + espeak-ng subprocess. In Rust
//! we keep the same orchestration shape but expose **traits** so the
//! production host wires native impls (cpal mic, whisper.cpp / whisper
//! HTTP API, espeak-ng subprocess) and tests inject stubs.
//!
//! ## Public surface
//! - [`VoiceConfig`] — env-driven defaults (AIM_WHISPER_MODEL /
//!   AIM_WHISPER_DEVICE / AIM_VOICE_SR)
//! - [`Recorder`] — produce a WAV file path from the default mic
//! - [`Transcriber`] — async ASR; impls walk a fall-back chain
//! - [`Speaker`] — sync TTS; impls walk a fall-back chain
//! - [`voice_round_trip`] — record → transcribe → callable agent →
//!   speak result; returns the agent's text output
//!
//! ## Default impls
//! - [`EspeakSpeaker`] — `espeak-ng -v <lang> <text>` subprocess
//! - [`StubRecorder`] / [`StubTranscriber`] / [`StubSpeaker`] — for tests
//!
//! Real ASR (faster-whisper / whisper.cpp / OpenAI HTTP) and real
//! recording (cpal) live in the host crate that wires this layer; this
//! crate stays free of audio deps so it compiles fast.

use async_trait::async_trait;
use parking_lot::Mutex;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use std::process::Command;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum VoiceError {
    #[error("recorder: {0}")]
    Recorder(String),
    #[error("transcriber: {0}")]
    Transcriber(String),
    #[error("speaker: {0}")]
    Speaker(String),
    #[error("agent: {0}")]
    Agent(String),
    #[error("io: {0}")]
    Io(#[from] std::io::Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceConfig {
    pub whisper_model: String,
    pub whisper_device: String,
    pub sample_rate: u32,
}

impl Default for VoiceConfig {
    fn default() -> Self {
        Self::from_env()
    }
}

impl VoiceConfig {
    /// Build from a custom env-source closure. Tests pass in an in-memory
    /// HashMap to stay hermetic; `from_env` uses the process env.
    pub fn from_source<F>(get: F) -> Self
    where
        F: Fn(&str) -> Option<String>,
    {
        Self {
            whisper_model: get("AIM_WHISPER_MODEL")
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "base".into()),
            whisper_device: get("AIM_WHISPER_DEVICE")
                .filter(|s| !s.is_empty())
                .unwrap_or_else(|| "cpu".into()),
            sample_rate: get("AIM_VOICE_SR")
                .and_then(|v| v.parse().ok())
                .unwrap_or(16_000),
        }
    }

    pub fn from_env() -> Self {
        Self::from_source(|k| std::env::var(k).ok())
    }
}

pub trait Recorder: Send + Sync {
    /// Capture `duration_secs` from the default mic into a temp WAV file
    /// and return its path. Caller is responsible for cleanup.
    fn record(&self, duration_secs: f64) -> Result<PathBuf, VoiceError>;
}

#[async_trait]
pub trait Transcriber: Send + Sync {
    /// Transcribe a WAV file. `language` is an ISO-639-1 hint
    /// (e.g. "ru", "en") — production impls thread this through to the
    /// underlying engine, stubs ignore it.
    async fn transcribe(
        &self,
        audio_path: &Path,
        language: Option<&str>,
    ) -> Result<String, VoiceError>;
}

pub trait Speaker: Send + Sync {
    /// Speak `text` synchronously. Empty input is a no-op.
    fn speak(&self, text: &str, lang: &str) -> Result<(), VoiceError>;
}

// ── espeak-ng subprocess speaker ────────────────────────────────────────

#[derive(Debug, Default)]
pub struct EspeakSpeaker;

impl EspeakSpeaker {
    pub fn new() -> Self {
        Self
    }

    /// Probe whether `espeak-ng` is on `$PATH`.
    pub fn available() -> bool {
        Command::new("which")
            .arg("espeak-ng")
            .output()
            .map(|out| out.status.success())
            .unwrap_or(false)
    }
}

impl Speaker for EspeakSpeaker {
    fn speak(&self, text: &str, lang: &str) -> Result<(), VoiceError> {
        if text.trim().is_empty() {
            return Ok(());
        }
        let cap: String = text.chars().take(5000).collect();
        let r = Command::new("espeak-ng")
            .args(["-v", lang, &cap])
            .output()
            .map_err(|e| VoiceError::Speaker(format!("espeak-ng spawn failed: {e}")))?;
        if !r.status.success() {
            return Err(VoiceError::Speaker(format!(
                "espeak-ng exited {}: {}",
                r.status,
                String::from_utf8_lossy(&r.stderr)
            )));
        }
        Ok(())
    }
}

// ── stubs for tests ─────────────────────────────────────────────────────

pub struct StubRecorder {
    pub path: PathBuf,
    pub calls: Mutex<Vec<f64>>,
}

impl StubRecorder {
    pub fn new(path: impl Into<PathBuf>) -> Self {
        Self {
            path: path.into(),
            calls: Mutex::new(Vec::new()),
        }
    }
}

impl Recorder for StubRecorder {
    fn record(&self, duration_secs: f64) -> Result<PathBuf, VoiceError> {
        self.calls.lock().push(duration_secs);
        Ok(self.path.clone())
    }
}

pub struct StubTranscriber {
    pub queue: Mutex<Vec<Result<String, String>>>,
    pub calls: Mutex<Vec<(PathBuf, Option<String>)>>,
}

impl StubTranscriber {
    pub fn new() -> Self {
        Self {
            queue: Mutex::new(Vec::new()),
            calls: Mutex::new(Vec::new()),
        }
    }
    pub fn push_ok(self, s: &str) -> Self {
        self.queue.lock().push(Ok(s.to_string()));
        self
    }
    pub fn push_err(self, e: &str) -> Self {
        self.queue.lock().push(Err(e.to_string()));
        self
    }
}

impl Default for StubTranscriber {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Transcriber for StubTranscriber {
    async fn transcribe(
        &self,
        audio_path: &Path,
        language: Option<&str>,
    ) -> Result<String, VoiceError> {
        self.calls
            .lock()
            .push((audio_path.to_path_buf(), language.map(String::from)));
        let mut q = self.queue.lock();
        if q.is_empty() {
            return Err(VoiceError::Transcriber("queue exhausted".into()));
        }
        match q.remove(0) {
            Ok(s) => Ok(s),
            Err(e) => Err(VoiceError::Transcriber(e)),
        }
    }
}

#[derive(Debug, Default)]
pub struct StubSpeaker {
    pub utterances: Mutex<Vec<(String, String)>>,
}

impl StubSpeaker {
    pub fn new() -> Self {
        Self::default()
    }
    pub fn snapshot(&self) -> Vec<(String, String)> {
        self.utterances.lock().clone()
    }
}

impl Speaker for StubSpeaker {
    fn speak(&self, text: &str, lang: &str) -> Result<(), VoiceError> {
        self.utterances
            .lock()
            .push((text.to_string(), lang.to_string()));
        Ok(())
    }
}

// ── orchestrator ────────────────────────────────────────────────────────

#[derive(Debug, Clone)]
pub struct RoundTripResult {
    pub heard: String,
    pub agent_output: String,
}

/// Pluggable agent — receives transcribed text, returns response text the
/// host wants spoken back. In production this wires `aim-graph::run_agent`
/// or whatever orchestrator you have; tests inject a closure.
#[async_trait]
pub trait Agent: Send + Sync {
    async fn run(&self, text: &str) -> Result<String, VoiceError>;
}

pub struct FnAgent<F>(pub F)
where
    F: Fn(&str) -> Result<String, VoiceError> + Send + Sync;

#[async_trait]
impl<F> Agent for FnAgent<F>
where
    F: Fn(&str) -> Result<String, VoiceError> + Send + Sync,
{
    async fn run(&self, text: &str) -> Result<String, VoiceError> {
        (self.0)(text)
    }
}

/// Record → transcribe → run agent → speak result. Spoken response is
/// truncated to 600 chars (matches Python). Transcription failure speaks
/// the localised retry prompt and returns an empty `agent_output`.
pub async fn voice_round_trip(
    duration_secs: f64,
    recorder: &dyn Recorder,
    transcriber: &dyn Transcriber,
    speaker: &dyn Speaker,
    agent: &dyn Agent,
    spoken_lang: &str,
) -> Result<RoundTripResult, VoiceError> {
    let audio = recorder.record(duration_secs)?;
    let heard = match transcriber.transcribe(&audio, None).await {
        Ok(t) => t,
        Err(_) => String::new(),
    };
    let _ = std::fs::remove_file(&audio);

    if heard.trim().is_empty() {
        let prompt = match spoken_lang {
            "ru" => "Не распознал, повтори.",
            "ka" => "ვერ ამოვიცანი, გთხოვთ გაიმეოროთ.",
            _ => "Didn't catch that, please repeat.",
        };
        let _ = speaker.speak(prompt, spoken_lang);
        return Ok(RoundTripResult {
            heard,
            agent_output: String::new(),
        });
    }

    let output = agent.run(&heard).await?;
    let cap: String = output.chars().take(600).collect();
    speaker.speak(&cap, spoken_lang)?;
    Ok(RoundTripResult {
        heard,
        agent_output: output,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn config_defaults_when_env_empty() {
        let c = VoiceConfig::from_source(|_| None);
        assert_eq!(c.whisper_model, "base");
        assert_eq!(c.whisper_device, "cpu");
        assert_eq!(c.sample_rate, 16_000);
    }

    #[test]
    fn config_env_overrides_apply() {
        let env: std::collections::HashMap<&str, &str> = [
            ("AIM_WHISPER_MODEL", "small"),
            ("AIM_WHISPER_DEVICE", "cuda"),
            ("AIM_VOICE_SR", "44100"),
        ]
        .into_iter()
        .collect();
        let c = VoiceConfig::from_source(|k| env.get(k).map(|s| s.to_string()));
        assert_eq!(c.whisper_model, "small");
        assert_eq!(c.whisper_device, "cuda");
        assert_eq!(c.sample_rate, 44_100);
    }

    #[test]
    fn config_invalid_sample_rate_falls_back_to_default() {
        let c = VoiceConfig::from_source(|k| {
            if k == "AIM_VOICE_SR" {
                Some("not-a-number".into())
            } else {
                None
            }
        });
        assert_eq!(c.sample_rate, 16_000);
    }

    #[test]
    fn stub_speaker_records_utterances() {
        let s = StubSpeaker::new();
        s.speak("hello", "en").unwrap();
        s.speak("привет", "ru").unwrap();
        assert_eq!(
            s.snapshot(),
            vec![
                ("hello".into(), "en".into()),
                ("привет".into(), "ru".into()),
            ]
        );
    }

    #[test]
    fn stub_speaker_empty_text_no_op() {
        // Stub records every call regardless; we just verify the
        // non-failing contract for empty strings.
        let s = StubSpeaker::new();
        s.speak("", "en").unwrap();
        assert_eq!(s.snapshot().len(), 1);
    }

    #[test]
    fn espeak_speaker_skips_empty_input() {
        // Even when espeak-ng isn't installed, empty text returns Ok
        // without ever spawning a subprocess.
        let sp = EspeakSpeaker::new();
        sp.speak("", "ru").unwrap();
    }

    #[tokio::test]
    async fn round_trip_happy_path() {
        let dir = TempDir::new().unwrap();
        let wav = dir.path().join("rec.wav");
        std::fs::write(&wav, b"fake-wav").unwrap();
        let recorder = StubRecorder::new(&wav);
        let transcriber = StubTranscriber::new().push_ok("привет, как дела");
        let speaker = StubSpeaker::new();
        let agent = FnAgent(|text: &str| {
            Ok(format!("Услышал: {text}"))
        });
        let r = voice_round_trip(3.0, &recorder, &transcriber, &speaker, &agent, "ru")
            .await
            .unwrap();
        assert_eq!(r.heard, "привет, как дела");
        assert!(r.agent_output.contains("Услышал"));
        let snap = speaker.snapshot();
        assert_eq!(snap.len(), 1);
        assert!(snap[0].0.contains("Услышал"));
        assert_eq!(snap[0].1, "ru");
        // Recorder duration captured
        assert_eq!(recorder.calls.lock()[0], 3.0);
        // Audio file removed
        assert!(!wav.exists());
    }

    #[tokio::test]
    async fn round_trip_empty_transcription_speaks_retry_prompt() {
        let dir = TempDir::new().unwrap();
        let wav = dir.path().join("rec.wav");
        std::fs::write(&wav, b"fake").unwrap();
        let recorder = StubRecorder::new(&wav);
        let transcriber = StubTranscriber::new().push_ok("   ");
        let speaker = StubSpeaker::new();
        let agent = FnAgent(|_: &str| Ok("never reached".into()));
        let r = voice_round_trip(2.0, &recorder, &transcriber, &speaker, &agent, "ru")
            .await
            .unwrap();
        assert_eq!(r.heard, "   ");
        assert!(r.agent_output.is_empty());
        let snap = speaker.snapshot();
        assert_eq!(snap.len(), 1);
        assert!(snap[0].0.contains("Не распознал"));
    }

    #[tokio::test]
    async fn round_trip_transcriber_error_treated_as_empty() {
        let dir = TempDir::new().unwrap();
        let wav = dir.path().join("rec.wav");
        std::fs::write(&wav, b"x").unwrap();
        let recorder = StubRecorder::new(&wav);
        let transcriber = StubTranscriber::new().push_err("backend down");
        let speaker = StubSpeaker::new();
        let agent = FnAgent(|_: &str| Ok("nope".into()));
        let r = voice_round_trip(1.0, &recorder, &transcriber, &speaker, &agent, "en")
            .await
            .unwrap();
        assert!(r.heard.is_empty());
        let snap = speaker.snapshot();
        assert!(snap[0].0.contains("Didn't catch"));
    }

    #[tokio::test]
    async fn round_trip_caps_spoken_output_at_600_chars() {
        let dir = TempDir::new().unwrap();
        let wav = dir.path().join("r.wav");
        std::fs::write(&wav, b"x").unwrap();
        let recorder = StubRecorder::new(&wav);
        let transcriber = StubTranscriber::new().push_ok("question");
        let speaker = StubSpeaker::new();
        let long_output = "x".repeat(2_000);
        let captured = long_output.clone();
        let agent = FnAgent(move |_: &str| Ok(captured.clone()));
        voice_round_trip(1.0, &recorder, &transcriber, &speaker, &agent, "en")
            .await
            .unwrap();
        let snap = speaker.snapshot();
        assert_eq!(snap[0].0.chars().count(), 600);
    }

    #[tokio::test]
    async fn round_trip_localises_retry_prompt() {
        for (lang, expected_substr) in [
            ("ru", "Не распознал"),
            ("en", "Didn't catch"),
            ("ka", "ვერ"),
        ] {
            let dir = TempDir::new().unwrap();
            let wav = dir.path().join("r.wav");
            std::fs::write(&wav, b"x").unwrap();
            let recorder = StubRecorder::new(&wav);
            let transcriber = StubTranscriber::new().push_ok("");
            let speaker = StubSpeaker::new();
            let agent = FnAgent(|_: &str| Ok("nope".into()));
            voice_round_trip(1.0, &recorder, &transcriber, &speaker, &agent, lang)
                .await
                .unwrap();
            let snap = speaker.snapshot();
            assert!(
                snap[0].0.contains(expected_substr),
                "lang={lang} got: {}",
                snap[0].0
            );
        }
    }

    #[tokio::test]
    async fn round_trip_propagates_agent_error() {
        let dir = TempDir::new().unwrap();
        let wav = dir.path().join("r.wav");
        std::fs::write(&wav, b"x").unwrap();
        let recorder = StubRecorder::new(&wav);
        let transcriber = StubTranscriber::new().push_ok("query");
        let speaker = StubSpeaker::new();
        let agent = FnAgent(|_: &str| Err(VoiceError::Agent("boom".into())));
        let r =
            voice_round_trip(1.0, &recorder, &transcriber, &speaker, &agent, "en").await;
        assert!(matches!(r, Err(VoiceError::Agent(_))));
    }
}
