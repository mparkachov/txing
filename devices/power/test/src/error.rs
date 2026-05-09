use std::fmt;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RigError {
    pub stage: String,
    pub message: String,
}

impl RigError {
    pub fn new(stage: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            stage: stage.into(),
            message: message.into(),
        }
    }

    pub fn args(message: impl Into<String>) -> Self {
        Self::new("args", message)
    }
}

impl fmt::Display for RigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.stage, self.message)
    }
}

impl std::error::Error for RigError {}

pub type Result<T> = std::result::Result<T, RigError>;
