use anyhow::{Context, Result, anyhow};
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AwsCredentials {
    pub access_key_id: String,
    pub secret_access_key: String,
    pub session_token: Option<String>,
}

pub fn resolve_credentials() -> Result<AwsCredentials> {
    if let Some(credentials) = load_from_environment()? {
        return Ok(credentials);
    }

    load_from_shared_credentials_file()
}

fn load_from_environment() -> Result<Option<AwsCredentials>> {
    let access_key_id = env::var("AWS_ACCESS_KEY_ID")
        .ok()
        .map(|value| value.trim().to_string());
    let secret_access_key = env::var("AWS_SECRET_ACCESS_KEY")
        .ok()
        .map(|value| value.trim().to_string());

    match (access_key_id, secret_access_key) {
        (Some(access_key_id), Some(secret_access_key))
            if !access_key_id.is_empty() && !secret_access_key.is_empty() =>
        {
            Ok(Some(AwsCredentials {
                access_key_id,
                secret_access_key,
                session_token: env::var("AWS_SESSION_TOKEN")
                    .ok()
                    .map(|value| value.trim().to_string())
                    .filter(|value| !value.is_empty()),
            }))
        }
        (None, None) => Ok(None),
        _ => Err(anyhow!(
            "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must either both be set or both be absent"
        )),
    }
}

fn load_from_shared_credentials_file() -> Result<AwsCredentials> {
    let profile = env::var("AWS_PROFILE").unwrap_or_else(|_| "default".to_string());
    let path = shared_credentials_path()
        .ok_or_else(|| anyhow!("could not determine the shared AWS credentials file path"))?;
    let content = fs::read_to_string(&path).with_context(|| {
        format!(
            "shared AWS credentials were not found in {} and no AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY environment variables were set",
            path.display()
        )
    })?;
    let sections = parse_ini_sections(&content);
    let section = sections.get(profile.as_str()).ok_or_else(|| {
        anyhow!(
            "shared AWS credentials file {} does not contain the profile {:?}",
            path.display(),
            profile
        )
    })?;

    let access_key_id = section
        .get("aws_access_key_id")
        .filter(|value| !value.is_empty())
        .cloned()
        .ok_or_else(|| anyhow!("profile {:?} is missing aws_access_key_id", profile))?;
    let secret_access_key = section
        .get("aws_secret_access_key")
        .filter(|value| !value.is_empty())
        .cloned()
        .ok_or_else(|| anyhow!("profile {:?} is missing aws_secret_access_key", profile))?;

    Ok(AwsCredentials {
        access_key_id,
        secret_access_key,
        session_token: section
            .get("aws_session_token")
            .cloned()
            .filter(|value| !value.is_empty()),
    })
}

fn shared_credentials_path() -> Option<PathBuf> {
    if let Ok(path) = env::var("AWS_SHARED_CREDENTIALS_FILE") {
        return Some(PathBuf::from(path));
    }

    let home = env::var_os("HOME")?;
    Some(Path::new(&home).join(".aws").join("credentials"))
}

fn parse_ini_sections(content: &str) -> HashMap<String, HashMap<String, String>> {
    let mut sections = HashMap::<String, HashMap<String, String>>::new();
    let mut current_section = String::new();

    for raw_line in content.lines() {
        let line = raw_line.trim();
        if line.is_empty() || line.starts_with('#') || line.starts_with(';') {
            continue;
        }

        if line.starts_with('[') && line.ends_with(']') {
            current_section = line[1..line.len() - 1].trim().to_string();
            sections.entry(current_section.clone()).or_default();
            continue;
        }

        let Some((key, value)) = line.split_once('=') else {
            continue;
        };
        if current_section.is_empty() {
            continue;
        }

        sections
            .entry(current_section.clone())
            .or_default()
            .insert(key.trim().to_string(), value.trim().to_string());
    }

    sections
}

#[cfg(test)]
mod tests {
    use super::{AwsCredentials, parse_ini_sections, resolve_credentials};
    use std::env;
    use std::fs;
    use std::sync::{Mutex, OnceLock};
    use tempfile::TempDir;

    fn env_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    #[test]
    fn parses_ini_sections() {
        let sections = parse_ini_sections(
            r#"
            [default]
            aws_access_key_id = test-access
            aws_secret_access_key = test-secret
            aws_session_token = test-token
            "#,
        );

        assert_eq!(
            sections.get("default"),
            Some(
                &[
                    ("aws_access_key_id".to_string(), "test-access".to_string()),
                    (
                        "aws_secret_access_key".to_string(),
                        "test-secret".to_string()
                    ),
                    ("aws_session_token".to_string(), "test-token".to_string()),
                ]
                .into_iter()
                .collect()
            )
        );
    }

    #[test]
    fn resolves_credentials_from_environment() {
        let _guard = env_lock().lock().expect("env lock should not be poisoned");
        let tempdir = TempDir::new().expect("tempdir should be created");
        let credentials_path = tempdir.path().join("credentials");
        fs::write(
            &credentials_path,
            "[default]\naws_access_key_id = file-access\naws_secret_access_key = file-secret\n",
        )
        .expect("credentials file should be written");

        unsafe {
            env::set_var("AWS_SHARED_CREDENTIALS_FILE", &credentials_path);
            env::set_var("AWS_ACCESS_KEY_ID", "env-access");
            env::set_var("AWS_SECRET_ACCESS_KEY", "env-secret");
            env::set_var("AWS_SESSION_TOKEN", "env-token");
        }

        let credentials = resolve_credentials().expect("environment credentials should resolve");
        assert_eq!(
            credentials,
            AwsCredentials {
                access_key_id: "env-access".to_string(),
                secret_access_key: "env-secret".to_string(),
                session_token: Some("env-token".to_string()),
            }
        );

        unsafe {
            env::remove_var("AWS_SHARED_CREDENTIALS_FILE");
            env::remove_var("AWS_ACCESS_KEY_ID");
            env::remove_var("AWS_SECRET_ACCESS_KEY");
            env::remove_var("AWS_SESSION_TOKEN");
        }
    }

    #[test]
    fn resolves_credentials_from_shared_credentials_file() {
        let _guard = env_lock().lock().expect("env lock should not be poisoned");
        let tempdir = TempDir::new().expect("tempdir should be created");
        let credentials_path = tempdir.path().join("credentials");
        fs::write(
            &credentials_path,
            "[board]\naws_access_key_id = file-access\naws_secret_access_key = file-secret\n",
        )
        .expect("credentials file should be written");

        unsafe {
            env::remove_var("AWS_ACCESS_KEY_ID");
            env::remove_var("AWS_SECRET_ACCESS_KEY");
            env::remove_var("AWS_SESSION_TOKEN");
            env::set_var("AWS_SHARED_CREDENTIALS_FILE", &credentials_path);
            env::set_var("AWS_PROFILE", "board");
        }

        let credentials = resolve_credentials().expect("file credentials should resolve");
        assert_eq!(
            credentials,
            AwsCredentials {
                access_key_id: "file-access".to_string(),
                secret_access_key: "file-secret".to_string(),
                session_token: None,
            }
        );

        unsafe {
            env::remove_var("AWS_SHARED_CREDENTIALS_FILE");
            env::remove_var("AWS_PROFILE");
        }
    }
}
