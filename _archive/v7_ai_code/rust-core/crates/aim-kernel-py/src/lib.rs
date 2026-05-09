//! aim-kernel-py — PyO3 bindings for aim-kernel (Phase 2, 2026-05-07).
//!
//! Exposes the pure Rust `aim-kernel` crate as a Python C-extension
//! `aim_kernel`. Backward-compatible with `agents/kernel.py` API so
//! existing 80+ pytest tests + 7 production agents work unchanged via
//! a 5-line shim.

use ::aim_kernel as core;
use pyo3::exceptions::{PyValueError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyDict;
use pythonize::depythonize;

// ── Helpers: dict → Patient / Context via serde ────────────────────────────

fn dict_to_patient(py_obj: &Bound<'_, PyAny>) -> PyResult<core::Patient> {
    if py_obj.is_none() {
        return Ok(core::Patient::new());
    }
    let v: serde_json::Value =
        depythonize(py_obj).map_err(|e| PyValueError::new_err(format!("patient: {e}")))?;
    serde_json::from_value(v).map_err(|e| PyValueError::new_err(format!("patient: {e}")))
}

fn dict_to_context(py_obj: &Bound<'_, PyAny>) -> PyResult<core::Context> {
    if py_obj.is_none() {
        return Ok(core::Context::default());
    }
    let v: serde_json::Value =
        depythonize(py_obj).map_err(|e| PyValueError::new_err(format!("context: {e}")))?;
    serde_json::from_value(v).map_err(|e| PyValueError::new_err(format!("context: {e}")))
}

// ── Decision pyclass ───────────────────────────────────────────────────────

#[pyclass(name = "Decision")]
#[derive(Clone)]
struct PyDecision {
    inner: core::Decision,
}

#[pymethods]
impl PyDecision {
    #[new]
    #[pyo3(signature = (id, description="".to_string(), action_type="".to_string(), payload=None, meta=None))]
    fn new(
        id: String,
        description: String,
        action_type: String,
        payload: Option<Py<PyDict>>,
        meta: Option<Py<PyDict>>,
    ) -> PyResult<Self> {
        Python::with_gil(|py| {
            let payload_v = payload
                .map(|p| {
                    depythonize(&p.into_bound(py).into_any())
                        .map_err(|e| PyValueError::new_err(format!("payload: {e}")))
                })
                .transpose()?
                .unwrap_or_else(|| serde_json::json!({}));
            let meta_v = meta
                .map(|m| {
                    depythonize(&m.into_bound(py).into_any())
                        .map_err(|e| PyValueError::new_err(format!("meta: {e}")))
                })
                .transpose()?
                .unwrap_or_else(|| serde_json::json!({}));
            Ok(Self {
                inner: core::Decision {
                    id,
                    description,
                    action_type,
                    payload: payload_v,
                    meta: meta_v,
                },
            })
        })
    }

    #[getter] fn id(&self) -> String { self.inner.id.clone() }
    #[getter] fn description(&self) -> String { self.inner.description.clone() }
    #[getter] fn action_type(&self) -> String { self.inner.action_type.clone() }
    #[getter]
    fn payload(&self, py: Python<'_>) -> PyResult<PyObject> {
        pythonize::pythonize(py, &self.inner.payload)
            .map(|b| b.unbind().into_any())
            .map_err(|e| PyValueError::new_err(format!("payload: {e}")))
    }
    #[getter]
    fn meta(&self, py: Python<'_>) -> PyResult<PyObject> {
        pythonize::pythonize(py, &self.inner.meta)
            .map(|b| b.unbind().into_any())
            .map_err(|e| PyValueError::new_err(format!("meta: {e}")))
    }

    fn __repr__(&self) -> String {
        format!("Decision(id={:?}, action_type={:?})", self.inner.id, self.inner.action_type)
    }
}

// ── LawsResult / ExtendedLawsResult / ScoringResult / Scored ───────────────

#[pyclass(name = "LawsResult")]
#[derive(Clone)]
struct PyLawsResult {
    inner: core::LawsResult,
}

#[pymethods]
impl PyLawsResult {
    #[new]
    #[pyo3(signature = (L0=true, L1=true, L2=true, L3=true, reasons=None))]
    fn new(L0: bool, L1: bool, L2: bool, L3: bool, reasons: Option<Vec<String>>) -> Self {
        let _ = (L0, L1, L2, L3);
        Self {
            inner: core::LawsResult {
                l0: L0, l1: L1, l2: L2, l3: L3,
                reasons: reasons.unwrap_or_default(),
            },
        }
    }
    #[getter] fn L0(&self) -> bool { self.inner.l0 }
    #[getter] fn L1(&self) -> bool { self.inner.l1 }
    #[getter] fn L2(&self) -> bool { self.inner.l2 }
    #[getter] fn L3(&self) -> bool { self.inner.l3 }
    #[getter] fn reasons(&self) -> Vec<String> { self.inner.reasons.clone() }
    #[getter] fn passed(&self) -> bool { self.inner.passed() }
}

#[pyclass(name = "ExtendedLawsResult")]
#[derive(Clone)]
struct PyExtendedLawsResult {
    inner: core::ExtendedLawsResult,
}

#[pymethods]
impl PyExtendedLawsResult {
    #[getter] fn privacy(&self) -> bool { self.inner.privacy }
    #[getter] fn consent(&self) -> bool { self.inner.consent }
    #[getter] fn verifiability(&self) -> bool { self.inner.verifiability }
    #[getter] fn agency(&self) -> bool { self.inner.agency }
    #[getter] fn reasons(&self) -> Vec<String> { self.inner.reasons.clone() }
    #[getter] fn passed(&self) -> bool { self.inner.passed() }
}

#[pyclass(name = "ScoringResult")]
#[derive(Clone)]
struct PyScoringResult {
    inner: core::ScoringResult,
}

#[pymethods]
impl PyScoringResult {
    #[new]
    #[pyo3(signature = (impedance_before=0.0, impedance_after=0.0, instant_c=0.0,
                         phi_ze=0.0, ethics_ze_learn_cheat=0.0, ethics_autonomy=0.0,
                         ethics_beneficence=0.0, ethics_nonmaleficence=0.0,
                         ethics_justice=0.0, ethics_composite=0.0, utility=0.0))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        impedance_before: f64, impedance_after: f64, instant_c: f64,
        phi_ze: f64, ethics_ze_learn_cheat: f64, ethics_autonomy: f64,
        ethics_beneficence: f64, ethics_nonmaleficence: f64,
        ethics_justice: f64, ethics_composite: f64, utility: f64,
    ) -> Self {
        Self { inner: core::ScoringResult {
            impedance_before, impedance_after, instant_c,
            phi_ze, ethics_ze_learn_cheat, ethics_autonomy,
            ethics_beneficence, ethics_nonmaleficence,
            ethics_justice, ethics_composite, utility,
        }}
    }
    #[getter] fn impedance_before(&self) -> f64 { self.inner.impedance_before }
    #[getter] fn impedance_after(&self) -> f64 { self.inner.impedance_after }
    #[getter] fn instant_c(&self) -> f64 { self.inner.instant_c }
    #[getter] fn phi_ze(&self) -> f64 { self.inner.phi_ze }
    #[getter] fn ethics_ze_learn_cheat(&self) -> f64 { self.inner.ethics_ze_learn_cheat }
    #[getter] fn ethics_autonomy(&self) -> f64 { self.inner.ethics_autonomy }
    #[getter] fn ethics_beneficence(&self) -> f64 { self.inner.ethics_beneficence }
    #[getter] fn ethics_nonmaleficence(&self) -> f64 { self.inner.ethics_nonmaleficence }
    #[getter] fn ethics_justice(&self) -> f64 { self.inner.ethics_justice }
    #[getter] fn ethics_composite(&self) -> f64 { self.inner.ethics_composite }
    #[getter] fn utility(&self) -> f64 { self.inner.utility }

    fn as_dict(&self, py: Python<'_>) -> PyResult<PyObject> {
        pythonize::pythonize(py, &self.inner)
            .map(|b| b.unbind().into_any())
            .map_err(|e| PyValueError::new_err(format!("scoring: {e}")))
    }
}

#[pyclass(name = "Scored")]
#[derive(Clone)]
struct PyScored {
    inner: core::Scored,
}

#[pymethods]
impl PyScored {
    #[new]
    #[pyo3(signature = (decision, laws, scoring=None, extended=None))]
    fn new(
        decision: PyDecision,
        laws: PyLawsResult,
        scoring: Option<PyScoringResult>,
        extended: Option<PyExtendedLawsResult>,
    ) -> Self {
        Self { inner: core::Scored {
            decision: decision.inner,
            laws: laws.inner,
            scoring: scoring.map(|s| s.inner),
            extended: extended.map(|e| e.inner),
        }}
    }
    #[getter]
    fn decision(&self) -> PyDecision {
        PyDecision { inner: self.inner.decision.clone() }
    }
    #[getter]
    fn laws(&self) -> PyLawsResult {
        PyLawsResult { inner: self.inner.laws.clone() }
    }
    #[getter]
    fn scoring(&self) -> Option<PyScoringResult> {
        self.inner.scoring.clone().map(|s| PyScoringResult { inner: s })
    }
    #[getter]
    fn extended(&self) -> Option<PyExtendedLawsResult> {
        self.inner.extended.clone().map(|e| PyExtendedLawsResult { inner: e })
    }
}

// ── OverrideContext ────────────────────────────────────────────────────────

#[pyclass(name = "OverrideContext")]
#[derive(Clone)]
struct PyOverrideContext {
    inner: core::OverrideContext,
}

#[pymethods]
impl PyOverrideContext {
    /// Python signature mirrors `agents/kernel.py:OverrideContext` —
    /// keyword `type=` (not `type_=`). PyO3 uses the Rust raw identifier
    /// `r#type` to express the reserved-ish name.
    #[new]
    #[pyo3(signature = (r#type="none".to_string(), forced_decision_id=None, reason=None))]
    fn new(
        r#type: String,
        forced_decision_id: Option<String>,
        reason: Option<String>,
    ) -> Self {
        let kind = match r#type.as_str() {
            "soft" => core::OverrideKind::Soft,
            "hard" => core::OverrideKind::Hard,
            _ => core::OverrideKind::None,
        };
        Self {
            inner: core::OverrideContext {
                kind,
                forced_decision_id,
                reason,
            },
        }
    }

    #[getter(r#type)]
    fn get_type(&self) -> &str {
        match self.inner.kind {
            core::OverrideKind::None => "none",
            core::OverrideKind::Soft => "soft",
            core::OverrideKind::Hard => "hard",
        }
    }
    #[getter] fn forced_decision_id(&self) -> Option<String> { self.inner.forced_decision_id.clone() }
    #[getter] fn reason(&self) -> Option<String> { self.inner.reason.clone() }
}

// ── KernelWeights ──────────────────────────────────────────────────────────

#[pyclass(name = "KernelWeights")]
#[derive(Clone)]
struct PyKernelWeights {
    inner: core::KernelWeights,
}

#[pymethods]
impl PyKernelWeights {
    #[new]
    #[pyo3(signature = (alpha=None, beta=None, gamma=None))]
    fn new(alpha: Option<f64>, beta: Option<f64>, gamma: Option<f64>) -> Self {
        let mut w = core::KernelWeights::default();
        if let Some(a) = alpha { w.alpha = a; }
        if let Some(b) = beta { w.beta = b; }
        if let Some(g) = gamma { w.gamma = g; }
        Self { inner: w }
    }
    #[getter] fn ALPHA(&self) -> f64 { self.inner.alpha }
    #[getter] fn BETA(&self) -> f64 { self.inner.beta }
    #[getter] fn GAMMA(&self) -> f64 { self.inner.gamma }
    #[getter] fn CLARIFY_IMPEDANCE_THRESHOLD(&self) -> f64 { self.inner.clarify_impedance_threshold }
}

// ── KernelViolation exception ──────────────────────────────────────────────

pyo3::create_exception!(aim_kernel, KernelViolation, PyRuntimeError);

// ── pyfunctions: laws / scoring / decide / format / log ────────────────────

fn pylaws_to_tuple(ok: bool, reason: String) -> (bool, String) { (ok, reason) }

#[pyfunction]
#[pyo3(signature = (decision, patient=None, context=None))]
fn evaluate_l0(
    decision: &PyDecision,
    patient: Option<&Bound<'_, PyAny>>,
    context: Option<&Bound<'_, PyAny>>,
) -> (bool, String) {
    let _ = patient;
    let _ = context;
    let (ok, r) = core::evaluate_l0(&decision.inner);
    pylaws_to_tuple(ok, r)
}

#[pyfunction]
fn evaluate_l1(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<(bool, String)> {
    let p = dict_to_patient(patient)?;
    let c = dict_to_context(context)?;
    let (ok, r) = core::evaluate_l1(&decision.inner, &p, &c);
    Ok((ok, r))
}

#[pyfunction]
fn evaluate_l2(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<(bool, String)> {
    let c = dict_to_context(context)?;
    Ok(core::evaluate_l2(&decision.inner, &c))
}

#[pyfunction]
fn evaluate_l3(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    _context: &Bound<'_, PyAny>,
) -> PyResult<(bool, String)> {
    Ok(core::evaluate_l3(&decision.inner))
}

#[pyfunction]
fn evaluate_laws(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<PyLawsResult> {
    let p = dict_to_patient(patient)?;
    let c = dict_to_context(context)?;
    Ok(PyLawsResult {
        inner: core::evaluate_laws(&decision.inner, &p, &c),
    })
}

#[pyfunction]
fn evaluate_l_privacy(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<(bool, String)> {
    let c = dict_to_context(context)?;
    Ok(core::evaluate_l_privacy(&decision.inner, &c))
}

#[pyfunction]
fn evaluate_l_consent(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<(bool, String)> {
    let c = dict_to_context(context)?;
    Ok(core::evaluate_l_consent(&decision.inner, &c))
}

#[pyfunction]
fn evaluate_l_verifiability(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    _context: &Bound<'_, PyAny>,
) -> (bool, String) {
    // Pure-Rust: no citation checker bound. Default = pass for non-emit.
    let _ = patient;
    let (ok, r) = core::evaluate_l_verifiability(&decision.inner, None);
    (ok, r)
}

#[pyfunction]
fn evaluate_l_agency(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    context: &Bound<'_, PyAny>,
) -> PyResult<(bool, String)> {
    let p = dict_to_patient(patient)?;
    let c = dict_to_context(context)?;
    Ok(core::evaluate_l_agency(&decision.inner, &p, &c))
}

#[pyfunction]
#[pyo3(signature = (decision, patient=None, context=None))]
fn evaluate_extended(
    decision: &PyDecision,
    patient: Option<&Bound<'_, PyAny>>,
    context: Option<&Bound<'_, PyAny>>,
) -> PyResult<PyExtendedLawsResult> {
    let c = match context {
        Some(c) => dict_to_context(c)?,
        None => core::Context::default(),
    };
    let inner = match patient {
        Some(p) => {
            let p = dict_to_patient(p)?;
            core::evaluate_extended_with_patient(&decision.inner, &p, &c, None)
        }
        None => core::evaluate_extended(&decision.inner, &c, None),
    };
    Ok(PyExtendedLawsResult { inner })
}

#[pyfunction]
#[pyo3(signature = (patient_id, agent, decision_type, alternatives, chosen, r#override, session_id=None))]
#[allow(clippy::too_many_arguments)]
fn log_decision(
    patient_id: String,
    agent: String,
    decision_type: String,
    alternatives: Vec<Py<PyScored>>,
    chosen: Option<PyScored>,
    r#override: PyOverrideContext,
    session_id: Option<String>,
    py: Python<'_>,
) -> PyResult<()> {
    let alts: Vec<core::Scored> = alternatives
        .iter()
        .map(|s| s.borrow(py).inner.clone())
        .collect();
    let chosen_inner = chosen
        .map(|s| s.inner)
        .or_else(|| alts.first().cloned())
        .ok_or_else(|| PyValueError::new_err("log_decision: no chosen and no alternatives"))?;
    let result = core::DecideResult {
        chosen: chosen_inner,
        alternatives: alts,
    };
    let db = std::env::var("AIM_DB_PATH")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            std::path::PathBuf::from(home).join(".cache/aim/aim.db")
        });
    let pdir = std::env::var("AIM_PATIENTS_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            std::path::PathBuf::from(home)
                .join("Desktop/LongevityCommon/AIM/Patients")
        });
    core::log_decision(
        &db,
        &pdir,
        &patient_id,
        &agent,
        &decision_type,
        &result,
        &r#override.inner,
        session_id.as_deref(),
    )
    .map_err(|e| PyRuntimeError::new_err(e.to_string()))
}

// Impedance + scoring

#[pyfunction]
#[pyo3(signature = (patient, context=None))]
fn impedance_checklist(
    patient: &Bound<'_, PyAny>,
    context: Option<&Bound<'_, PyAny>>,
) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    let _ = context; // context not used by checklist (parity with Python)
    Ok(core::impedance_checklist(&p))
}

#[pyfunction]
#[pyo3(signature = (patient, context=None, llm_caller=None))]
fn impedance(
    patient: &Bound<'_, PyAny>,
    context: Option<&Bound<'_, PyAny>>,
    llm_caller: Option<PyObject>,
) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    let _ = context;
    let _ = llm_caller; // PyO3 callback wired in Phase 2.5; for now checklist-only
    Ok(core::impedance(&p))
}

#[pyfunction]
fn expected_impedance_after(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    Ok(core::expected_impedance_after(&decision.inner, &p))
}

#[pyfunction]
fn instant_c(decision: &PyDecision, patient: &Bound<'_, PyAny>) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    Ok(core::instant_c(&decision.inner, &p))
}

#[pyfunction]
fn phi_ze_path_integral(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    Ok(core::phi_ze_path_integral(&decision.inner, &p))
}

#[pyfunction]
fn ethics_ze_score(decision: &PyDecision, patient: &Bound<'_, PyAny>) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    Ok(core::ethics_ze_score(&decision.inner, &p))
}

#[pyfunction]
fn ethics_autonomy(decision: &PyDecision, patient: &Bound<'_, PyAny>) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    Ok(core::ethics_autonomy(&decision.inner, &p))
}

#[pyfunction]
fn ethics_beneficence(decision: &PyDecision, patient: &Bound<'_, PyAny>) -> PyResult<f64> {
    let p = dict_to_patient(patient)?;
    Ok(core::ethics_beneficence(&decision.inner, &p))
}

#[pyfunction]
fn ethics_nonmaleficence(decision: &PyDecision) -> f64 {
    core::ethics_nonmaleficence(&decision.inner)
}

#[pyfunction]
fn ethics_justice(decision: &PyDecision) -> f64 {
    core::ethics_justice(&decision.inner)
}

#[pyfunction]
fn ethics_composite(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    py: Python<'_>,
) -> PyResult<(f64, PyObject)> {
    let p = dict_to_patient(patient)?;
    let w = core::KernelWeights::default();
    let (composite, parts) = core::ethics_composite(&decision.inner, &p, &w);
    let dict = PyDict::new(py);
    dict.set_item("ze_learn_cheat", parts.ze_learn_cheat)?;
    dict.set_item("autonomy", parts.autonomy)?;
    dict.set_item("beneficence", parts.beneficence)?;
    dict.set_item("nonmaleficence", parts.nonmaleficence)?;
    dict.set_item("justice", parts.justice)?;
    Ok((composite, dict.unbind().into_any()))
}

#[pyfunction]
fn score_decision(
    decision: &PyDecision,
    patient: &Bound<'_, PyAny>,
    _context: &Bound<'_, PyAny>,
) -> PyResult<PyScoringResult> {
    let p = dict_to_patient(patient)?;
    let w = core::KernelWeights::default();
    Ok(PyScoringResult {
        inner: core::score_decision(&decision.inner, &p, &w),
    })
}

#[pyfunction]
#[pyo3(signature = (alternatives, patient, context=None, r#override=None,
                     agent="unknown".to_string(), patient_id="".to_string(),
                     session_id=None, decision_type="triage".to_string()))]
#[allow(clippy::too_many_arguments)]
fn decide(
    alternatives: Vec<Py<PyDecision>>,
    patient: &Bound<'_, PyAny>,
    context: Option<&Bound<'_, PyAny>>,
    r#override: Option<PyOverrideContext>,
    agent: String,
    patient_id: String,
    session_id: Option<String>,
    decision_type: String,
    py: Python<'_>,
) -> PyResult<PyScored> {
    let p = dict_to_patient(patient)?;
    let c = match context {
        Some(c) => dict_to_context(c)?,
        None => core::Context::default(),
    };
    let ov = r#override.map(|o| o.inner).unwrap_or_default();
    let weights = core::KernelWeights::default();
    let alts: Vec<core::Decision> = alternatives
        .iter()
        .map(|d| d.borrow(py).inner.clone())
        .collect();
    let result = core::decide(&alts, &p, &c, &ov, &weights)
        .map_err(|e| KernelViolation::new_err(e.to_string()))?;

    // Phase 1 keeps decide() pure (no logging) — call log_decision separately
    // when we want side-effects. For Python parity, fire the log here too.
    let db = std::env::var("AIM_DB_PATH")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            std::path::PathBuf::from(home).join(".cache/aim/aim.db")
        });
    let pdir = std::env::var("AIM_PATIENTS_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            let home = std::env::var("HOME").unwrap_or_default();
            std::path::PathBuf::from(home)
                .join("Desktop/LongevityCommon/AIM/Patients")
        });
    // Best-effort logging — failures log to stderr but don't fail decide()
    if let Err(e) = core::log_decision(
        &db,
        &pdir,
        &patient_id,
        &agent,
        &decision_type,
        &result,
        &ov,
        session_id.as_deref(),
    ) {
        eprintln!("aim_kernel.decide: log_decision failed: {e}");
    }
    let _ = decision_type; // silence unused-on-some-paths

    Ok(PyScored { inner: result.chosen })
}

// Format

#[pyfunction]
#[pyo3(signature = (scored, lang="ru".to_string()))]
fn format_compact(scored: &PyScored, lang: String) -> String {
    core::format_compact(&scored.inner, &lang)
}

#[pyfunction]
#[pyo3(signature = (scored, lang="ru".to_string()))]
fn format_verbose(scored: &PyScored, lang: String) -> String {
    core::format_verbose(&scored.inner, &lang)
}

#[pyfunction]
#[pyo3(signature = (patient, context=None))]
fn needs_clarification(
    patient: &Bound<'_, PyAny>,
    context: Option<&Bound<'_, PyAny>>,
) -> PyResult<bool> {
    let p = dict_to_patient(patient)?;
    let _ = context;
    let w = core::KernelWeights::default();
    Ok(core::needs_clarification(&p, &w))
}

// ── module init ───────────────────────────────────────────────────────────

#[pymodule]
fn aim_kernel(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyDecision>()?;
    m.add_class::<PyLawsResult>()?;
    m.add_class::<PyExtendedLawsResult>()?;
    m.add_class::<PyScoringResult>()?;
    m.add_class::<PyScored>()?;
    m.add_class::<PyOverrideContext>()?;
    m.add_class::<PyKernelWeights>()?;
    m.add("KernelViolation", m.py().get_type::<KernelViolation>())?;

    m.add_function(wrap_pyfunction!(evaluate_l0, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l1, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l2, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l3, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_laws, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l_privacy, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l_consent, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l_verifiability, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_l_agency, m)?)?;
    m.add_function(wrap_pyfunction!(evaluate_extended, m)?)?;

    m.add_function(wrap_pyfunction!(impedance_checklist, m)?)?;
    m.add_function(wrap_pyfunction!(impedance, m)?)?;
    m.add_function(wrap_pyfunction!(expected_impedance_after, m)?)?;
    m.add_function(wrap_pyfunction!(instant_c, m)?)?;
    m.add_function(wrap_pyfunction!(phi_ze_path_integral, m)?)?;
    m.add_function(wrap_pyfunction!(ethics_ze_score, m)?)?;
    m.add_function(wrap_pyfunction!(ethics_autonomy, m)?)?;
    m.add_function(wrap_pyfunction!(ethics_beneficence, m)?)?;
    m.add_function(wrap_pyfunction!(ethics_nonmaleficence, m)?)?;
    m.add_function(wrap_pyfunction!(ethics_justice, m)?)?;
    m.add_function(wrap_pyfunction!(ethics_composite, m)?)?;
    m.add_function(wrap_pyfunction!(score_decision, m)?)?;
    m.add_function(wrap_pyfunction!(decide, m)?)?;
    m.add_function(wrap_pyfunction!(format_compact, m)?)?;
    m.add_function(wrap_pyfunction!(format_verbose, m)?)?;
    m.add_function(wrap_pyfunction!(needs_clarification, m)?)?;
    m.add_function(wrap_pyfunction!(log_decision, m)?)?;
    Ok(())
}
