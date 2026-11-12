//! OpenRouter speech-to-text.
//!
//! OpenRouter exposes `POST /api/v1/audio/transcriptions` with a JSON body
//! (`model` plus an inline base64 `input_audio` object), not the multipart upload
//! used by Whisper-compatible providers. Audio is buffered while recording and
//! sent once when recording stops, like [`super::whisper_compat`].
//!
//! The API key is the user's OpenRouter key, shared with LLM polish.

use async_trait::async_trait;
use base64::Engine;

use crate::error::AppError;

use super::whisper_compat::{WhisperCompatConfig, WhisperCompatProvider};
use super::{SttConfig, SttProvider, TranscriptEvent};

pub const OPENROUTER_STT_PROVIDER: &str = "openrouter-stt";
pub const OPENROUTER_STT_ENDPOINT: &str = "https://openrouter.ai/api/v1/audio/transcriptions";
pub const OPENROUTER_STT_MODELS_URL: &str =
    "https://openrouter.ai/api/v1/models?output_modalities=transcription";
pub const DEFAULT_OPENROUTER_STT_MODEL: &str = "openai/whisper-large-v3-turbo";

const MAX_AUDIO_BYTES: usize = 24 * 1024 * 1024;
const REQUEST_TIMEOUT: std::time::Duration = std::time::Duration::from_secs(60);

/// Builds the provider config for the selected OpenRouter transcription model.
///
/// The shared [`WhisperCompatConfig`] type carries the endpoint and model so the
/// existing `create_provider` plumbing does not need a new parameter.
pub fn build_openrouter_stt_config(model: &str) -> Result<WhisperCompatConfig, String> {
    let model = model.trim();
    if model.is_empty() {
        return Err("Choose an OpenRouter speech-to-text model in Settings".to_string());
    }
    Ok(WhisperCompatConfig {
        provider_name: OPENROUTER_STT_PROVIDER.to_string(),
        endpoint: OPENROUTER_STT_ENDPOINT.to_string(),
        model: model.to_string(),
        extra_fields: Vec::new(),
        api_key_required: true,
    })
}

/// JSON request body for one transcription. Audio is sent inline because
/// OpenRouter rejects URLs for audio input on transcription models.
pub fn build_request_body(model: &str, wav: &[u8]) -> serde_json::Value {
    serde_json::json!({
        "model": model,
        "input_audio": {
            "data": base64::engine::general_purpose::STANDARD.encode(wav),
            "format": "wav",
        },
    })
}

/// Reads the transcript from a 200 response.
///
/// OpenRouter documents that a provider failure can arrive as HTTP 200 with a
/// top-level `error` object, so that shape is turned into an error here.
/// An empty `text` means no speech was detected and is not an error.
pub fn parse_transcript(body: &str) -> Result<Option<String>, AppError> {
    let value: serde_json::Value =
        serde_json::from_str(body).map_err(|e| AppError::Config(e.to_string()))?;

    if let Some(error) = value.get("error").filter(|e| !e.is_null()) {
        let status = error["code"]
            .as_u64()
            .and_then(|code| u16::try_from(code).ok())
            .unwrap_or(502);
        let message = error["message"].as_str().unwrap_or("provider error");
        return Err(AppError::Api {
            status,
            body: truncate_for_error(message),
        });
    }

    let text = value["text"].as_str().unwrap_or("").trim().to_string();
    Ok(if text.is_empty() { None } else { Some(text) })
}

fn truncate_for_error(text: &str) -> String {
    // Cut at a char boundary so multi-byte text cannot panic.
    let cut = text
        .char_indices()
        .take_while(|&(i, _)| i < 200)
        .last()
        .map(|(i, c)| i + c.len_utf8())
        .unwrap_or(text.len());
    text[..cut].to_string()
}

fn upload_error(error: reqwest::Error) -> AppError {
    if error.is_timeout() {
        AppError::Timeout(REQUEST_TIMEOUT)
    } else {
        error.into()
    }
}

pub struct OpenRouterSttProvider {
    endpoint: String,
    model: String,
    stt_config: Option<SttConfig>,
    audio_buffer: Vec<u8>,
    client: reqwest::Client,
}

impl OpenRouterSttProvider {
    pub fn new(config: WhisperCompatConfig) -> Self {
        Self::with_client(config, reqwest::Client::new())
    }

    pub fn with_client(config: WhisperCompatConfig, client: reqwest::Client) -> Self {
        Self {
            endpoint: config.endpoint,
            model: config.model,
            stt_config: None,
            audio_buffer: Vec::new(),
            client,
        }
    }
}

#[async_trait]
impl SttProvider for OpenRouterSttProvider {
    async fn connect(&mut self, config: &SttConfig) -> Result<(), AppError> {
        if config.api_key.trim().is_empty() {
            return Err(AppError::Auth("OpenRouter API key is empty".to_string()));
        }
        self.stt_config = Some(config.clone());
        self.audio_buffer.clear();
        tracing::info!("openrouter-stt provider ready (buffering mode)");
        Ok(())
    }

    async fn send_audio(&mut self, chunk: &[u8]) -> Result<(), AppError> {
        if self.audio_buffer.len() + chunk.len() > MAX_AUDIO_BYTES {
            return Err(AppError::Config(
                "openrouter-stt: audio exceeds maximum length (~12 min)".to_string(),
            ));
        }
        self.audio_buffer.extend_from_slice(chunk);
        Ok(())
    }

    async fn recv_transcript(&mut self) -> Result<Option<TranscriptEvent>, AppError> {
        std::future::pending().await
    }

    async fn disconnect(&mut self) -> Result<Option<String>, AppError> {
        let config = match &self.stt_config {
            Some(c) => c.clone(),
            None => return Ok(None),
        };

        if self.audio_buffer.is_empty() {
            tracing::info!("openrouter-stt: no audio buffered, skipping");
            return Ok(None);
        }

        let audio_len_secs = self.audio_buffer.len() as f64 / (config.sample_rate as f64 * 2.0);
        let wav = WhisperCompatProvider::build_wav(&self.audio_buffer, config.sample_rate);
        self.audio_buffer.clear();
        tracing::info!(
            "openrouter-stt: sending {:.1}s of audio to {}",
            audio_len_secs,
            self.model
        );

        let body = build_request_body(&self.model, &wav);
        let mut attempt = 0u32;
        loop {
            let result = self
                .client
                .post(&self.endpoint)
                .header("Authorization", format!("Bearer {}", config.api_key))
                .json(&body)
                .timeout(REQUEST_TIMEOUT)
                .send()
                .await;

            match result {
                Ok(resp) => {
                    let status = resp.status();
                    let text = resp.text().await.map_err(upload_error)?;

                    if status.is_success() {
                        let transcript = parse_transcript(&text)?;
                        tracing::info!(
                            "openrouter-stt transcription: {} chars",
                            transcript.as_deref().map(str::len).unwrap_or(0)
                        );
                        return Ok(transcript);
                    }

                    let sanitized = truncate_for_error(&text);
                    if status.as_u16() >= 500 && attempt < 2 {
                        tracing::warn!(
                            "openrouter-stt server error {} (attempt {}/3)",
                            status,
                            attempt + 1
                        );
                        attempt += 1;
                        tokio::time::sleep(std::time::Duration::from_millis(
                            1000 * 2u64.pow(attempt - 1),
                        ))
                        .await;
                        continue;
                    }

                    // Never log request headers or the key; the body is the provider's error text.
                    tracing::error!("openrouter-stt HTTP {}: {}", status, sanitized);
                    return Err(AppError::Api {
                        status: status.as_u16(),
                        body: sanitized,
                    });
                }
                Err(e) if e.is_timeout() && attempt < 2 => {
                    tracing::warn!("openrouter-stt timeout (attempt {}/3)", attempt + 1);
                    attempt += 1;
                    tokio::time::sleep(std::time::Duration::from_millis(
                        1000 * 2u64.pow(attempt - 1),
                    ))
                    .await;
                    continue;
                }
                Err(e) => return Err(upload_error(e)),
            }
        }
    }

    fn name(&self) -> &str {
        OPENROUTER_STT_PROVIDER
    }
}

/// A transcription model offered by OpenRouter.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct OpenRouterSttModel {
    pub id: String,
    pub name: String,
}

/// Reads `GET /models?output_modalities=transcription`. Entries that do not list
/// `transcription` as an output are dropped, so a changed filter cannot add chat models.
pub fn parse_models(body: &str) -> Result<Vec<OpenRouterSttModel>, String> {
    let value: serde_json::Value = serde_json::from_str(body).map_err(|e| e.to_string())?;
    let data = value["data"]
        .as_array()
        .ok_or_else(|| "Unexpected OpenRouter models response".to_string())?;
    let mut models: Vec<OpenRouterSttModel> = data
        .iter()
        .filter(|m| {
            m["architecture"]["output_modalities"]
                .as_array()
                .is_some_and(|o| o.iter().any(|x| x == "transcription"))
        })
        .filter_map(|m| {
            let id = m["id"].as_str()?.to_string();
            let name = m["name"].as_str().unwrap_or(&id).to_string();
            Some(OpenRouterSttModel { id, name })
        })
        .collect();
    models.sort_by(|a, b| a.id.cmp(&b.id));
    Ok(models)
}

/// Fetches the live transcription model list. The endpoint is public.
pub async fn fetch_models(client: &reqwest::Client) -> Result<Vec<OpenRouterSttModel>, String> {
    let resp = client
        .get(OPENROUTER_STT_MODELS_URL)
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("HTTP {}", resp.status()));
    }
    let body = resp.text().await.map_err(|e| e.to_string())?;
    parse_models(&body)
}

/// Sends 0.1 s of silence to check the key, credit and model. Returns the round-trip in ms.
/// Errors read `HTTP <status>: <provider message>` so the UI can show why it failed.
pub async fn probe(client: &reqwest::Client, api_key: &str, model: &str) -> Result<u32, String> {
    let wav = WhisperCompatProvider::build_wav(&[0u8; 3200], 16000);
    let started = std::time::Instant::now();
    let resp = client
        .post(OPENROUTER_STT_ENDPOINT)
        .header("Authorization", format!("Bearer {}", api_key))
        .json(&build_request_body(model, &wav))
        .timeout(std::time::Duration::from_secs(15))
        .send()
        .await
        .map_err(|e| e.to_string())?;
    let elapsed = started.elapsed().as_millis() as u32;
    let status = resp.status();
    let body = resp.text().await.map_err(|e| e.to_string())?;
    if !status.is_success() {
        // Known failures come back as `[stt_no_credit] ...` so the UI can explain what to do.
        if let Some(message) =
            crate::llm::http_error::classified_message(status.as_u16(), &body, true)
        {
            return Err(message);
        }
        return Err(format!(
            "HTTP {}: {}",
            status.as_u16(),
            crate::llm::http_error::details_for(&body)
        ));
    }
    parse_transcript(&body).map_err(|e| e.to_string())?;
    Ok(elapsed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};

    #[test]
    fn config_requires_a_model() {
        assert!(build_openrouter_stt_config("  ").is_err());
        let cfg = build_openrouter_stt_config(" openai/whisper-1 ").unwrap();
        assert_eq!(cfg.model, "openai/whisper-1");
        assert_eq!(cfg.endpoint, OPENROUTER_STT_ENDPOINT);
        assert!(cfg.api_key_required);
    }

    #[test]
    fn request_body_sends_inline_base64_wav() {
        let body = build_request_body("openai/whisper-1", &[1, 2, 3]);
        assert_eq!(body["model"], "openai/whisper-1");
        assert_eq!(body["input_audio"]["format"], "wav");
        assert_eq!(body["input_audio"]["data"], "AQID");
        assert!(body["input_audio"].get("url").is_none());
    }

    #[test]
    fn parses_text_and_treats_empty_text_as_no_speech() {
        let ok = r#"{"text":"  hello world ","usage":{"seconds":2,"cost":0.00000666}}"#;
        assert_eq!(
            parse_transcript(ok).unwrap().as_deref(),
            Some("hello world")
        );
        let silent = r#"{"text":"","usage":{"seconds":2,"cost":0.00000666}}"#;
        assert_eq!(parse_transcript(silent).unwrap(), None);
    }

    #[test]
    fn http_200_with_error_object_is_an_error() {
        let body = r#"{"error":{"code":402,"message":"Insufficient credits"}}"#;
        match parse_transcript(body).unwrap_err() {
            AppError::Api { status, body } => {
                assert_eq!(status, 402);
                assert_eq!(body, "Insufficient credits");
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }

    #[test]
    fn long_multibyte_error_text_is_truncated_on_a_char_boundary() {
        let body = serde_json::json!({"error": {"code": 400, "message": "错".repeat(500)}});
        match parse_transcript(&body.to_string()).unwrap_err() {
            AppError::Api { body, .. } => assert!(body.chars().count() <= 70),
            other => panic!("unexpected error: {other:?}"),
        }
    }

    #[tokio::test]
    async fn connect_rejects_an_empty_key() {
        let mut provider = OpenRouterSttProvider::new(build_openrouter_stt_config("m").unwrap());
        let err = provider.connect(&SttConfig::default()).await.unwrap_err();
        assert!(matches!(err, AppError::Auth(_)), "{err:?}");
    }

    /// Serves one canned HTTP response and returns the raw request it received.
    fn serve_once(
        status_line: &'static str,
        body: &'static str,
    ) -> (String, std::thread::JoinHandle<String>) {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let handle = std::thread::spawn(move || {
            let (mut socket, _) = listener.accept().unwrap();
            socket
                .set_read_timeout(Some(std::time::Duration::from_secs(10)))
                .unwrap();
            let mut request = Vec::new();
            let mut buf = [0u8; 4096];
            loop {
                let n = socket.read(&mut buf).unwrap();
                request.extend_from_slice(&buf[..n]);
                let text = String::from_utf8_lossy(&request).to_string();
                if let Some(split) = text.find("\r\n\r\n") {
                    let length = text[..split]
                        .lines()
                        .find_map(|l| {
                            l.to_ascii_lowercase()
                                .strip_prefix("content-length:")
                                .map(|v| v.trim().parse::<usize>().unwrap())
                        })
                        .unwrap_or(0);
                    if request.len() >= split + 4 + length {
                        break;
                    }
                }
                if n == 0 {
                    break;
                }
            }
            let response = format!(
                "HTTP/1.1 {status_line}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            socket.write_all(response.as_bytes()).unwrap();
            String::from_utf8_lossy(&request).to_string()
        });
        (format!("http://{address}/v1/audio/transcriptions"), handle)
    }

    async fn run(
        status_line: &'static str,
        body: &'static str,
    ) -> (Result<Option<String>, AppError>, String) {
        let (endpoint, server) = serve_once(status_line, body);
        let mut cfg = build_openrouter_stt_config("openai/whisper-large-v3-turbo").unwrap();
        cfg.endpoint = endpoint;
        let mut provider = OpenRouterSttProvider::new(cfg);
        provider
            .connect(&SttConfig {
                api_key: "sk-or-test-key".to_string(),
                ..SttConfig::default()
            })
            .await
            .unwrap();
        provider.send_audio(&[0, 0, 0, 0]).await.unwrap();
        let result = provider.disconnect().await;
        (result, server.join().unwrap())
    }

    #[tokio::test]
    async fn uploads_json_with_bearer_key_and_returns_the_transcript() {
        let (result, request) =
            run("200 OK", r#"{"text":"hello there","usage":{"seconds":1}}"#).await;
        assert_eq!(result.unwrap().as_deref(), Some("hello there"));
        let lower = request.to_ascii_lowercase();
        assert!(lower.contains("authorization: bearer sk-or-test-key"));
        assert!(lower.contains("content-type: application/json"));
        assert!(request.contains(r#""model":"openai/whisper-large-v3-turbo""#));
        assert!(request.contains(r#""format":"wav""#));
    }

    #[test]
    fn model_list_keeps_only_transcription_models_sorted() {
        let body = r#"{"data":[
          {"id":"openai/whisper-1","name":"OpenAI: Whisper 1","architecture":{"output_modalities":["transcription"]}},
          {"id":"openai/gpt-5","name":"GPT-5","architecture":{"output_modalities":["text"]}},
          {"id":"deepgram/nova-3","architecture":{"output_modalities":["transcription"]}}
        ]}"#;
        let models = parse_models(body).unwrap();
        assert_eq!(
            models,
            vec![
                OpenRouterSttModel {
                    id: "deepgram/nova-3".into(),
                    name: "deepgram/nova-3".into()
                },
                OpenRouterSttModel {
                    id: "openai/whisper-1".into(),
                    name: "OpenAI: Whisper 1".into()
                },
            ]
        );
        assert!(parse_models("{}").is_err());
    }

    #[tokio::test]
    async fn payment_required_is_reported_with_its_status() {
        let (result, _) = run(
            "402 Payment Required",
            r#"{"error":{"code":402,"message":"Insufficient credits"}}"#,
        )
        .await;
        match result.unwrap_err() {
            AppError::Api { status, body } => {
                assert_eq!(status, 402);
                assert!(body.contains("Insufficient credits"));
            }
            other => panic!("unexpected error: {other:?}"),
        }
    }
}
