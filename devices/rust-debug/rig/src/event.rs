use std::time::{SystemTime, UNIX_EPOCH};

pub type EventField<'a> = (&'a str, String);

pub struct EventEmitter {
    stdout: bool,
    sinks: Vec<Box<dyn FnMut(&str) + Send>>,
}

impl Default for EventEmitter {
    fn default() -> Self {
        Self::stdout()
    }
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

    pub fn emit(&mut self, event: &str, fields: &[EventField<'_>]) {
        let mut line = format!("{} {}", unix_ms(), event);
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

fn unix_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
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
