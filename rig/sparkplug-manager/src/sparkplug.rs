use anyhow::{Result, bail};

pub const SPARKPLUG_NAMESPACE: &str = "spBv1.0";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u64)]
pub enum DataType {
    Int32 = 3,
    UInt64 = 8,
    Double = 10,
    Boolean = 11,
    String = 12,
}

#[derive(Debug, Clone, PartialEq)]
pub enum MetricValue {
    Int32(i32),
    UInt64(u64),
    Double(f64),
    Boolean(bool),
    String(String),
}

#[derive(Debug, Clone, PartialEq)]
pub struct Metric {
    pub name: String,
    pub value: MetricValue,
}

#[derive(Debug, Clone, PartialEq)]
pub struct Payload {
    pub timestamp: u64,
    pub metrics: Vec<Metric>,
    pub seq: Option<u64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodedCommand {
    pub metric_name: String,
    pub value: u8,
    pub seq: Option<u64>,
    pub timestamp: Option<u64>,
}

impl Metric {
    pub fn int32(name: impl Into<String>, value: i32) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::Int32(value),
        }
    }

    pub fn uint64(name: impl Into<String>, value: u64) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::UInt64(value),
        }
    }

    pub fn double(name: impl Into<String>, value: f64) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::Double(value),
        }
    }

    pub fn boolean(name: impl Into<String>, value: bool) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::Boolean(value),
        }
    }

    pub fn string(name: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            value: MetricValue::String(value.into()),
        }
    }
}

pub fn build_node_topic(group_id: &str, message_type: &str, edge_node_id: &str) -> String {
    format!("{SPARKPLUG_NAMESPACE}/{group_id}/{message_type}/{edge_node_id}")
}

pub fn build_device_topic(
    group_id: &str,
    message_type: &str,
    edge_node_id: &str,
    device_id: &str,
) -> String {
    format!("{SPARKPLUG_NAMESPACE}/{group_id}/{message_type}/{edge_node_id}/{device_id}")
}

pub fn encode_payload(payload: &Payload) -> Result<Vec<u8>> {
    let mut chunks = Vec::new();
    append_varint_field(&mut chunks, 1, payload.timestamp)?;
    for metric in &payload.metrics {
        let metric_payload = encode_metric(metric)?;
        append_bytes_field(&mut chunks, 2, &metric_payload)?;
    }
    if let Some(seq) = payload.seq {
        append_varint_field(&mut chunks, 3, seq)?;
    }
    Ok(chunks)
}

pub fn encode_metric(metric: &Metric) -> Result<Vec<u8>> {
    let mut chunks = Vec::new();
    append_string_field(&mut chunks, 1, &metric.name)?;
    match &metric.value {
        MetricValue::Int32(value) => {
            append_varint_field(&mut chunks, 4, DataType::Int32 as u64)?;
            append_varint_field(&mut chunks, 10, *value as u64)?;
        }
        MetricValue::UInt64(value) => {
            append_varint_field(&mut chunks, 4, DataType::UInt64 as u64)?;
            append_varint_field(&mut chunks, 11, *value)?;
        }
        MetricValue::Double(value) => {
            append_varint_field(&mut chunks, 4, DataType::Double as u64)?;
            append_fixed64_field(&mut chunks, 13, *value);
        }
        MetricValue::Boolean(value) => {
            append_varint_field(&mut chunks, 4, DataType::Boolean as u64)?;
            append_varint_field(&mut chunks, 14, u64::from(*value))?;
        }
        MetricValue::String(value) => {
            append_varint_field(&mut chunks, 4, DataType::String as u64)?;
            append_string_field(&mut chunks, 15, value)?;
        }
    }
    Ok(chunks)
}

pub fn decode_payload(data: &[u8]) -> Result<Payload> {
    let mut offset = 0;
    let mut timestamp = None;
    let mut seq = None;
    let mut metrics = Vec::new();
    while offset < data.len() {
        let (field_number, wire_type, next_offset) = read_key(data, offset)?;
        offset = next_offset;
        match (field_number, wire_type) {
            (1, 0) => {
                let (value, next) = read_varint(data, offset)?;
                timestamp = Some(value);
                offset = next;
            }
            (2, 2) => {
                let (value, next) = read_length_delimited(data, offset)?;
                metrics.push(decode_metric(value)?);
                offset = next;
            }
            (3, 0) => {
                let (value, next) = read_varint(data, offset)?;
                seq = Some(value);
                offset = next;
            }
            _ => {
                offset = skip_field(data, offset, wire_type)?;
            }
        }
    }
    Ok(Payload {
        timestamp: timestamp.unwrap_or(0),
        metrics,
        seq,
    })
}

pub fn decode_metric(data: &[u8]) -> Result<Metric> {
    let mut offset = 0;
    let mut name = String::new();
    let mut datatype = 0;
    let mut int_value = None;
    let mut long_value = None;
    let mut double_value = None;
    let mut bool_value = None;
    let mut string_value = None;
    while offset < data.len() {
        let (field_number, wire_type, next_offset) = read_key(data, offset)?;
        offset = next_offset;
        match (field_number, wire_type) {
            (1, 2) => {
                let (value, next) = read_length_delimited(data, offset)?;
                name = String::from_utf8(value.to_vec())?;
                offset = next;
            }
            (4, 0) => {
                let (value, next) = read_varint(data, offset)?;
                datatype = value;
                offset = next;
            }
            (10, 0) => {
                let (value, next) = read_varint(data, offset)?;
                int_value = Some(value as i32);
                offset = next;
            }
            (11, 0) => {
                let (value, next) = read_varint(data, offset)?;
                long_value = Some(value);
                offset = next;
            }
            (13, 1) => {
                let (value, next) = read_fixed64(data, offset)?;
                double_value = Some(value);
                offset = next;
            }
            (14, 0) => {
                let (value, next) = read_varint(data, offset)?;
                bool_value = Some(value != 0);
                offset = next;
            }
            (15, 2) => {
                let (value, next) = read_length_delimited(data, offset)?;
                string_value = Some(String::from_utf8(value.to_vec())?);
                offset = next;
            }
            _ => {
                offset = skip_field(data, offset, wire_type)?;
            }
        }
    }
    let value = match datatype {
        value if value == DataType::Int32 as u64 => MetricValue::Int32(
            int_value.ok_or_else(|| anyhow::anyhow!("Int32 metric missing value"))?,
        ),
        value if value == DataType::UInt64 as u64 => MetricValue::UInt64(
            long_value.ok_or_else(|| anyhow::anyhow!("UInt64 metric missing value"))?,
        ),
        value if value == DataType::Double as u64 => MetricValue::Double(
            double_value.ok_or_else(|| anyhow::anyhow!("Double metric missing value"))?,
        ),
        value if value == DataType::Boolean as u64 => MetricValue::Boolean(
            bool_value.ok_or_else(|| anyhow::anyhow!("Boolean metric missing value"))?,
        ),
        value if value == DataType::String as u64 => MetricValue::String(
            string_value.ok_or_else(|| anyhow::anyhow!("String metric missing value"))?,
        ),
        _ => bail!("unsupported Sparkplug metric datatype {datatype}"),
    };
    Ok(Metric { name, value })
}

pub fn decode_redcon_command(data: &[u8]) -> Result<Option<DecodedCommand>> {
    let payload = decode_payload(data)?;
    for metric in payload.metrics {
        if metric.name != "redcon" {
            continue;
        }
        let value = match metric.value {
            MetricValue::Int32(value) => value,
            MetricValue::UInt64(value) => value as i32,
            _ => return Ok(None),
        };
        if !(1..=4).contains(&value) {
            return Ok(None);
        }
        return Ok(Some(DecodedCommand {
            metric_name: metric.name,
            value: value as u8,
            seq: payload.seq,
            timestamp: Some(payload.timestamp),
        }));
    }
    Ok(None)
}

pub fn build_redcon_payload(redcon: u8, seq: u64, timestamp: u64) -> Result<Vec<u8>> {
    validate_redcon(redcon)?;
    encode_payload(&Payload {
        timestamp,
        metrics: vec![Metric::int32("redcon", redcon as i32)],
        seq: Some(seq),
    })
}

pub fn build_device_report_payload(
    redcon: u8,
    seq: u64,
    timestamp: u64,
    metrics: Vec<Metric>,
) -> Result<Vec<u8>> {
    validate_redcon(redcon)?;
    let mut all_metrics = vec![Metric::int32("redcon", redcon as i32)];
    all_metrics.extend(metrics);
    encode_payload(&Payload {
        timestamp,
        metrics: all_metrics,
        seq: Some(seq),
    })
}

pub fn build_device_death_payload(seq: u64, timestamp: u64) -> Result<Vec<u8>> {
    encode_payload(&Payload {
        timestamp,
        metrics: Vec::new(),
        seq: Some(seq),
    })
}

pub fn build_node_birth_payload(
    redcon: u8,
    bdseq: u64,
    seq: u64,
    timestamp: u64,
) -> Result<Vec<u8>> {
    validate_redcon(redcon)?;
    encode_payload(&Payload {
        timestamp,
        metrics: vec![
            Metric::uint64("bdSeq", bdseq),
            Metric::int32("redcon", redcon as i32),
        ],
        seq: Some(seq),
    })
}

pub fn build_node_death_payload(redcon: u8, bdseq: u64, timestamp: u64) -> Result<Vec<u8>> {
    validate_redcon(redcon)?;
    encode_payload(&Payload {
        timestamp,
        metrics: vec![
            Metric::uint64("bdSeq", bdseq),
            Metric::int32("redcon", redcon as i32),
        ],
        seq: None,
    })
}

pub fn validate_redcon(level: u8) -> Result<()> {
    if !(1..=4).contains(&level) {
        bail!("redcon must be between 1 and 4, got {level}");
    }
    Ok(())
}

fn append_key(chunks: &mut Vec<u8>, field_number: u64, wire_type: u64) -> Result<()> {
    append_varint(chunks, (field_number << 3) | wire_type)
}

fn append_varint_field(chunks: &mut Vec<u8>, field_number: u64, value: u64) -> Result<()> {
    append_key(chunks, field_number, 0)?;
    append_varint(chunks, value)
}

fn append_string_field(chunks: &mut Vec<u8>, field_number: u64, value: &str) -> Result<()> {
    append_bytes_field(chunks, field_number, value.as_bytes())
}

fn append_bytes_field(chunks: &mut Vec<u8>, field_number: u64, value: &[u8]) -> Result<()> {
    append_key(chunks, field_number, 2)?;
    append_varint(chunks, value.len() as u64)?;
    chunks.extend_from_slice(value);
    Ok(())
}

fn append_fixed64_field(chunks: &mut Vec<u8>, field_number: u64, value: f64) {
    let _ = append_key(chunks, field_number, 1);
    chunks.extend_from_slice(&value.to_le_bytes());
}

fn append_varint(chunks: &mut Vec<u8>, mut value: u64) -> Result<()> {
    loop {
        let next_byte = (value & 0x7f) as u8;
        value >>= 7;
        if value != 0 {
            chunks.push(next_byte | 0x80);
        } else {
            chunks.push(next_byte);
            return Ok(());
        }
    }
}

fn read_key(data: &[u8], offset: usize) -> Result<(u64, u64, usize)> {
    let (key, next_offset) = read_varint(data, offset)?;
    Ok((key >> 3, key & 0x07, next_offset))
}

fn read_varint(data: &[u8], offset: usize) -> Result<(u64, usize)> {
    let mut value = 0u64;
    let mut shift = 0;
    let mut index = offset;
    loop {
        if index >= data.len() {
            bail!("unexpected end of buffer while reading varint");
        }
        let byte = data[index];
        index += 1;
        value |= u64::from(byte & 0x7f) << shift;
        if byte & 0x80 == 0 {
            return Ok((value, index));
        }
        shift += 7;
        if shift > 63 {
            bail!("varint is too large");
        }
    }
}

fn read_length_delimited(data: &[u8], offset: usize) -> Result<(&[u8], usize)> {
    let (length, next_offset) = read_varint(data, offset)?;
    let end = next_offset + length as usize;
    if end > data.len() {
        bail!("unexpected end of buffer while reading bytes field");
    }
    Ok((&data[next_offset..end], end))
}

fn read_fixed64(data: &[u8], offset: usize) -> Result<(f64, usize)> {
    let end = offset + 8;
    if end > data.len() {
        bail!("unexpected end of buffer while reading fixed64 field");
    }
    let mut bytes = [0u8; 8];
    bytes.copy_from_slice(&data[offset..end]);
    Ok((f64::from_le_bytes(bytes), end))
}

fn skip_field(data: &[u8], offset: usize, wire_type: u64) -> Result<usize> {
    match wire_type {
        0 => read_varint(data, offset).map(|(_, next)| next),
        1 => {
            let next = offset + 8;
            if next > data.len() {
                bail!("unexpected end of buffer while skipping fixed64 field");
            }
            Ok(next)
        }
        2 => read_length_delimited(data, offset).map(|(_, next)| next),
        5 => {
            let next = offset + 4;
            if next > data.len() {
                bail!("unexpected end of buffer while skipping fixed32 field");
            }
            Ok(next)
        }
        _ => bail!("unsupported wire type {wire_type}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redcon_command_round_trips() {
        let payload = build_redcon_payload(3, 9, 1714380000000).unwrap();

        let decoded = decode_redcon_command(&payload).unwrap().unwrap();

        assert_eq!(decoded.value, 3);
        assert_eq!(decoded.seq, Some(9));
        assert_eq!(decoded.timestamp, Some(1714380000000));
    }

    #[test]
    fn device_report_supports_typed_metrics() {
        let payload = build_device_report_payload(
            4,
            10,
            1714380000001,
            vec![
                Metric::int32("batteryMv", 3970),
                Metric::double("measuredTemperature", 21.625),
                Metric::boolean("commands/cmd-1/succeeded", true),
                Metric::string("commands/cmd-1/status", "succeeded"),
            ],
        )
        .unwrap();

        let decoded = decode_payload(&payload).unwrap();

        assert_eq!(decoded.seq, Some(10));
        assert_eq!(decoded.metrics[0], Metric::int32("redcon", 4));
        assert_eq!(decoded.metrics[1], Metric::int32("batteryMv", 3970));
        assert_eq!(
            decoded.metrics[2],
            Metric::double("measuredTemperature", 21.625)
        );
        assert_eq!(
            decoded.metrics[3],
            Metric::boolean("commands/cmd-1/succeeded", true)
        );
        assert_eq!(
            decoded.metrics[4],
            Metric::string("commands/cmd-1/status", "succeeded")
        );
    }
}
