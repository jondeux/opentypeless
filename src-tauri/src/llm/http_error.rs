//! Classifies HTTP failures from BYOK LLM and speech providers (OpenRouter first).
//!
//! OpenRouter reports errors as `{"error":{"code":<int>,"message":"..."}}` with the
//! HTTP status equal to `code`; OpenAI-style providers use the same envelope. The
//! classification is by status plus a few message markers, so it also helps other
//! OpenAI-compatible providers. User-facing text lives in the frontend locales; this
//! module only picks a stable code and extracts the provider's own message.
//!
//! Nothing here sees request headers, so API keys cannot leak through it.

use crate::error::AppError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LlmFailure {
    InvalidKey,
    NoCredit,
    UnknownModel,
    RateLimited,
    ModelUnavailable,
    Moderated,
    Other,
}

impl LlmFailure {
    /// Code for LLM polish, Ask and the LLM connection test. `None` keeps the generic `llm_failed`.
    pub fn llm_code(self) -> Option<&'static str> {
        match self {
            LlmFailure::InvalidKey => Some("llm_invalid_key"),
            LlmFailure::NoCredit => Some("llm_no_credit"),
            LlmFailure::UnknownModel => Some("llm_unknown_model"),
            LlmFailure::RateLimited => Some("llm_rate_limited"),
            LlmFailure::ModelUnavailable => Some("llm_model_unavailable"),
            LlmFailure::Moderated => Some("llm_moderated"),
            LlmFailure::Other => None,
        }
    }

    /// Code for speech-to-text. `None` keeps the generic `stt_failed`.
    pub fn stt_code(self) -> Option<&'static str> {
        match self {
            LlmFailure::InvalidKey => Some("stt_invalid_key"),
            LlmFailure::NoCredit => Some("stt_no_credit"),
            LlmFailure::UnknownModel => Some("stt_unknown_model"),
            LlmFailure::RateLimited => Some("stt_rate_limited"),
            _ => None,
        }
    }
}

fn contains_any(haystack: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| haystack.contains(needle))
}

/// Picks the failure kind from the HTTP status and the provider's error body.
pub fn classify(status: u16, body: &str) -> LlmFailure {
    let message = provider_message(body)
        .unwrap_or_default()
        .to_ascii_lowercase();
    let body_lower = body.to_ascii_lowercase();

    // Some providers (OpenAI) send "out of credit" as 429 with an insufficient_quota code.
    if contains_any(
        &body_lower,
        &[
            "insufficient_quota",
            "exceeded your current quota",
            "insufficient credits",
            "insufficient credit",
            "out of credits",
        ],
    ) {
        return LlmFailure::NoCredit;
    }

    match status {
        401 => LlmFailure::InvalidKey,
        402 => LlmFailure::NoCredit,
        403 => {
            if contains_any(&message, &["moderation", "flagged", "guardrail", "policy"]) {
                LlmFailure::Moderated
            } else {
                LlmFailure::InvalidKey
            }
        }
        404 => LlmFailure::UnknownModel,
        400 => {
            if contains_any(
                &message,
                &[
                    "not a valid model",
                    "invalid model",
                    "unknown model",
                    "model not found",
                    "does not exist",
                    "no such model",
                    "model_not_found",
                ],
            ) {
                LlmFailure::UnknownModel
            } else {
                LlmFailure::Other
            }
        }
        429 => LlmFailure::RateLimited,
        502 | 503 => LlmFailure::ModelUnavailable,
        _ => LlmFailure::Other,
    }
}

fn truncate(text: &str, max_chars: usize) -> String {
    text.chars().take(max_chars).collect()
}

/// The provider's own error text (`error.message`, `message` or `detail`), capped at 200 chars.
pub fn provider_message(body: &str) -> Option<String> {
    let value: serde_json::Value = serde_json::from_str(body).ok()?;
    let candidate = value["error"]["message"]
        .as_str()
        .or_else(|| value["error"].as_str())
        .or_else(|| value["message"].as_str())
        .or_else(|| value["detail"].as_str())?
        .trim();
    (!candidate.is_empty()).then(|| truncate(candidate, 200))
}

/// Provider message when the body is an error envelope, otherwise the raw body, capped.
pub fn details_for(body: &str) -> String {
    provider_message(body).unwrap_or_else(|| truncate(body.trim(), 200))
}

/// Message for surfaces that show a plain string (Ask, connection tests):
/// `[llm_no_credit] <provider message>`. The frontend turns the bracketed code into
/// actionable text. Unclassified failures keep the legacy `<label> (<status>): <details>` form.
pub fn coded_message(label: &str, status: u16, body: &str, stt: bool) -> String {
    classified_message(status, body, stt)
        .unwrap_or_else(|| format!("{label} ({status}): {}", details_for(body)))
}

/// `[code] <provider message>` when the failure is a known kind, otherwise `None`.
pub fn classified_message(status: u16, body: &str, stt: bool) -> Option<String> {
    let kind = classify(status, body);
    let code = if stt {
        kind.stt_code()
    } else {
        kind.llm_code()
    }?;
    Some(format!("[{code}] {}", details_for(body)))
}

/// Turns an error object found inside a 200 response (OpenRouter mid-stream errors) into an
/// `AppError`. `raw` is the JSON of the `error` object, or any other text.
pub fn app_error_from_stream_error(raw: &str) -> AppError {
    let value: serde_json::Value = match serde_json::from_str(raw) {
        Ok(value) => value,
        Err(_) => return AppError::Config(raw.to_string()),
    };
    let status = value["code"]
        .as_u64()
        .and_then(|code| u16::try_from(code).ok())
        .or_else(|| {
            value["code"]
                .as_str()
                .and_then(|code| code.parse::<u16>().ok())
        });
    match status {
        Some(status) => AppError::Api {
            status,
            body: serde_json::json!({ "error": value }).to_string(),
        },
        None => AppError::Config(raw.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const OR_BAD_KEY: &str = r#"{"error":{"message":"No auth credentials found","code":401}}"#;
    const OR_NO_CREDIT: &str = r#"{"error":{"message":"Insufficient credits. Add more using https://openrouter.ai/settings/credits","code":402}}"#;
    const OR_UNKNOWN_MODEL: &str = r#"{"error":{"message":"no-such/model-xyz is not a valid model ID","code":400},"user_id":"user_x"}"#;
    const OR_RATE_LIMIT: &str =
        r#"{"error":{"message":"Rate limit exceeded: free-models-per-min.","code":429}}"#;

    #[test]
    fn bad_key_is_invalid_key() {
        assert_eq!(classify(401, OR_BAD_KEY), LlmFailure::InvalidKey);
        assert_eq!(classify(401, "").llm_code(), Some("llm_invalid_key"));
        assert_eq!(classify(401, "").stt_code(), Some("stt_invalid_key"));
    }

    #[test]
    fn no_credit_is_detected_from_402_and_from_openai_quota_errors() {
        assert_eq!(classify(402, OR_NO_CREDIT), LlmFailure::NoCredit);
        let openai = r#"{"error":{"message":"You exceeded your current quota","type":"insufficient_quota","code":"insufficient_quota"}}"#;
        assert_eq!(classify(429, openai), LlmFailure::NoCredit);
        assert_eq!(classify(402, "").llm_code(), Some("llm_no_credit"));
        assert_eq!(classify(402, "").stt_code(), Some("stt_no_credit"));
    }

    #[test]
    fn unknown_model_is_detected_from_400_message_and_404() {
        assert_eq!(classify(400, OR_UNKNOWN_MODEL), LlmFailure::UnknownModel);
        assert_eq!(
            classify(
                404,
                r#"{"error":{"message":"No endpoints found for foo/bar","code":404}}"#
            ),
            LlmFailure::UnknownModel
        );
        assert_eq!(
            classify(400, r#"{"error":{"message":"max_tokens too large"}}"#),
            LlmFailure::Other
        );
    }

    #[test]
    fn rate_limit_is_429() {
        assert_eq!(classify(429, OR_RATE_LIMIT), LlmFailure::RateLimited);
        assert_eq!(classify(429, "").llm_code(), Some("llm_rate_limited"));
        assert_eq!(classify(429, "").stt_code(), Some("stt_rate_limited"));
    }

    #[test]
    fn model_down_and_moderation_are_separate_kinds() {
        assert_eq!(
            classify(502, r#"{"error":{"message":"Provider returned error"}}"#),
            LlmFailure::ModelUnavailable
        );
        assert_eq!(classify(503, ""), LlmFailure::ModelUnavailable);
        assert_eq!(
            classify(
                403,
                r#"{"error":{"message":"Your input was flagged by moderation"}}"#
            ),
            LlmFailure::Moderated
        );
        assert_eq!(
            classify(403, r#"{"error":{"message":"forbidden"}}"#),
            LlmFailure::InvalidKey
        );
        assert_eq!(classify(500, ""), LlmFailure::Other);
        assert_eq!(classify(500, "").llm_code(), None);
    }

    #[test]
    fn provider_message_reads_common_envelopes_and_caps_length() {
        assert_eq!(
            provider_message(OR_BAD_KEY).as_deref(),
            Some("No auth credentials found")
        );
        assert_eq!(
            provider_message(r#"{"detail":"nope"}"#).as_deref(),
            Some("nope")
        );
        assert_eq!(provider_message("not json"), None);
        let long = serde_json::json!({"error": {"message": "错".repeat(500)}}).to_string();
        assert_eq!(provider_message(&long).unwrap().chars().count(), 200);
        assert_eq!(details_for("plain text body"), "plain text body");
    }

    #[test]
    fn coded_message_prefixes_known_failures_and_keeps_legacy_form_otherwise() {
        assert_eq!(
            coded_message("Ask request failed", 402, OR_NO_CREDIT, false),
            "[llm_no_credit] Insufficient credits. Add more using https://openrouter.ai/settings/credits"
        );
        assert_eq!(
            coded_message("Ask request failed", 500, "boom", false),
            "Ask request failed (500): boom"
        );
        assert!(coded_message("HTTP", 429, "", true).starts_with("[stt_rate_limited]"));
    }

    #[test]
    fn mid_stream_error_object_becomes_an_api_error() {
        let raw = r#"{"code":402,"message":"Insufficient credits"}"#;
        match app_error_from_stream_error(raw) {
            AppError::Api { status, body } => {
                assert_eq!(status, 402);
                assert_eq!(classify(status, &body), LlmFailure::NoCredit);
                assert_eq!(
                    provider_message(&body).as_deref(),
                    Some("Insufficient credits")
                );
            }
            other => panic!("unexpected: {other:?}"),
        }
        assert!(matches!(
            app_error_from_stream_error("plain failure"),
            AppError::Config(_)
        ));
        assert!(matches!(
            app_error_from_stream_error(r#"{"message":"no code"}"#),
            AppError::Config(_)
        ));
    }
}
