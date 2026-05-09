use std::fs::{File, OpenOptions};
use std::io::Write;
use std::path::Path;
use std::sync::{Arc, Mutex};

use chrono::{Local, SecondsFormat};

pub type EventField<'a> = (&'a str, String);

pub struct EventEmitter {
    stdout: bool,
    sinks: Vec<Box<dyn FnMut(&str) + Send>>,
}

impl EventEmitter {
    pub fn stdout() -> Self {
        Self {
            stdout: true,
            sinks: Vec::new(),
        }
    }

    pub fn quiet() -> Self {
        Self {
            stdout: false,
            sinks: Vec::new(),
        }
    }

    pub fn add_sink(&mut self, sink: impl FnMut(&str) + Send + 'static) {
        self.sinks.push(Box::new(sink));
    }

    pub fn add_file_sink(&mut self, path: impl AsRef<Path>) -> std::io::Result<()> {
        let file = Arc::new(Mutex::new(File::create(path)?));
        self.add_sink(move |line| {
            if let Ok(mut file) = file.lock() {
                let _ = writeln!(file, "{line}");
            }
        });
        Ok(())
    }

    pub fn add_file_sink_append(&mut self, path: impl AsRef<Path>) -> std::io::Result<()> {
        let file = Arc::new(Mutex::new(
            OpenOptions::new().create(true).append(true).open(path)?,
        ));
        self.add_sink(move |line| {
            if let Ok(mut file) = file.lock() {
                let _ = writeln!(file, "{line}");
            }
        });
        Ok(())
    }

    pub fn emit(&mut self, event: &str, fields: &[EventField<'_>]) {
        let mut line = format!("{} {}", local_timestamp(), event);
        for (key, value) in fields {
            line.push(' ');
            line.push_str(key);
            line.push('=');
            line.push_str(&format_value(value));
        }
        if self.stdout {
            println!("{line}");
        }
        for sink in &mut self.sinks {
            sink(&line);
        }
    }
}

pub fn parse_event_line(line: &str) -> (String, Vec<(String, String)>) {
    let mut tokens = split_fields(line);
    if tokens.len() < 2 {
        return (String::new(), Vec::new());
    }
    let event = tokens.remove(1);
    let fields = tokens
        .into_iter()
        .skip(1)
        .filter_map(|token| {
            let (key, value) = token.split_once('=')?;
            Some((key.to_string(), value.to_string()))
        })
        .collect();
    (event, fields)
}

pub fn local_timestamp() -> String {
    Local::now().to_rfc3339_opts(SecondsFormat::Millis, false)
}

pub fn local_timestamp_for_path() -> String {
    Local::now().format("%Y%m%d-%H%M%S%.3f").to_string()
}

fn format_value(value: &str) -> String {
    if value.is_empty()
        || value
            .chars()
            .any(|ch| ch.is_whitespace() || ch == '\'' || ch == '"')
    {
        format!("'{}'", value.replace('\'', "'\\''"))
    } else {
        value.to_string()
    }
}

fn split_fields(line: &str) -> Vec<String> {
    let mut result = Vec::new();
    let mut current = String::new();
    let mut chars = line.chars().peekable();
    let mut in_single = false;
    while let Some(ch) = chars.next() {
        match ch {
            '\'' => {
                if in_single && chars.peek() == Some(&'\\') {
                    current.push('\'');
                    let _ = chars.next();
                    let _ = chars.next();
                    continue;
                }
                in_single = !in_single;
            }
            ' ' | '\t' if !in_single => {
                if !current.is_empty() {
                    result.push(std::mem::take(&mut current));
                }
            }
            _ => current.push(ch),
        }
    }
    if !current.is_empty() {
        result.push(current);
    }
    result
}
