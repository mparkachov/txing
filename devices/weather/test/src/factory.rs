use std::path::Path;

use crate::error::{Result, RigError};

pub const DEFAULT_FACTORY_DATA_ADDRESS: u32 = 0x000f0000;
pub const FACTORY_DATA_MAGIC: &[u8; 4] = b"TXR1";
pub const FACTORY_DATA_VERSION: u8 = 1;
pub const FACTORY_DEVICE_NAME_SIZE: usize = 26;
pub const FACTORY_DATA_SIZE: usize = 36;

pub fn parse_address(value: &str) -> Result<u32> {
    let trimmed = value.trim();
    let parsed = if let Some(hex) = trimmed
        .strip_prefix("0x")
        .or_else(|| trimmed.strip_prefix("0X"))
    {
        u32::from_str_radix(hex, 16)
    } else {
        trimmed.parse()
    }
    .map_err(|_| RigError::args(format!("invalid address: {value:?}")))?;
    Ok(parsed)
}

pub fn validate_device_name(value: &str) -> Result<String> {
    let device_name = value.trim();
    if device_name.is_empty() {
        return Err(RigError::args("device name must not be empty"));
    }
    let encoded = device_name.as_bytes().iter().copied().collect::<Vec<_>>();
    if !device_name.is_ascii() {
        return Err(RigError::args("device name must be ASCII"));
    }
    if encoded.len() > FACTORY_DEVICE_NAME_SIZE {
        return Err(RigError::args(format!(
            "device name is too long ({} > {} bytes): {device_name:?}",
            encoded.len(),
            FACTORY_DEVICE_NAME_SIZE
        )));
    }
    if encoded.iter().any(|byte| *byte < 0x21 || *byte > 0x7e) {
        return Err(RigError::args(
            "device name may contain only printable non-space ASCII",
        ));
    }
    Ok(device_name.to_string())
}

pub fn build_factory_data(device_name: &str) -> Result<Vec<u8>> {
    let normalized = validate_device_name(device_name)?;
    let encoded = normalized.as_bytes();
    let mut payload = Vec::with_capacity(FACTORY_DATA_SIZE);
    payload.extend_from_slice(FACTORY_DATA_MAGIC);
    payload.push(FACTORY_DATA_VERSION);
    payload.push(encoded.len() as u8);
    payload.extend_from_slice(encoded);
    payload.resize(4 + 1 + 1 + FACTORY_DEVICE_NAME_SIZE, 0);
    let crc = crc32_ieee(&payload);
    payload.extend_from_slice(&crc.to_le_bytes());
    Ok(payload)
}

pub fn build_intel_hex(address: u32, data: &[u8]) -> Result<String> {
    let mut lines = Vec::new();
    let mut offset = 0usize;
    let mut current_high = None;

    while offset < data.len() {
        let absolute = address
            .checked_add(offset as u32)
            .ok_or_else(|| RigError::args("factory data address overflow"))?;
        let high = absolute >> 16;
        let low = (absolute & 0xffff) as u16;
        if Some(high) != current_high {
            lines.push(intel_hex_record(0, 0x04, &(high as u16).to_be_bytes())?);
            current_high = Some(high);
        }
        let chunk_size = usize::min(16, usize::min(data.len() - offset, 0x10000 - low as usize));
        lines.push(intel_hex_record(
            low,
            0x00,
            &data[offset..offset + chunk_size],
        )?);
        offset += chunk_size;
    }

    lines.push(intel_hex_record(0, 0x01, &[])?);
    Ok(lines.join("\n") + "\n")
}

pub fn write_factory_hex(device_name: &str, output: &Path, address: u32) -> Result<()> {
    let payload = build_factory_data(device_name)?;
    let hex = build_intel_hex(address, &payload)?;
    if let Some(parent) = output.parent() {
        std::fs::create_dir_all(parent).map_err(|err| {
            RigError::new(
                "factory",
                format!("failed to create {}: {err}", parent.display()),
            )
        })?;
    }
    std::fs::write(output, hex).map_err(|err| {
        RigError::new(
            "factory",
            format!("failed to write {}: {err}", output.display()),
        )
    })
}

fn crc32_ieee(data: &[u8]) -> u32 {
    let mut crc = 0xffff_ffffu32;
    for byte in data {
        crc ^= u32::from(*byte);
        for _ in 0..8 {
            let lsb = (crc & 1) != 0;
            crc >>= 1;
            if lsb {
                crc ^= 0xedb8_8320;
            }
        }
    }
    crc ^ 0xffff_ffff
}

fn intel_hex_record(address: u16, record_type: u8, data: &[u8]) -> Result<String> {
    if data.len() > u8::MAX as usize {
        return Err(RigError::args("Intel HEX record is too large"));
    }
    let mut body = Vec::with_capacity(4 + data.len());
    body.push(data.len() as u8);
    body.extend_from_slice(&address.to_be_bytes());
    body.push(record_type);
    body.extend_from_slice(data);
    let checksum = (!body.iter().fold(0u8, |sum, byte| sum.wrapping_add(*byte))).wrapping_add(1);
    Ok(format!(":{}{checksum:02X}", hex_upper(&body)))
}

fn hex_upper(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02X}")).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn factory_data_contains_power_compatible_redcon_record() {
        let payload = build_factory_data("weather-q8zbgb").unwrap();

        assert_eq!(payload.len(), FACTORY_DATA_SIZE);
        assert_eq!(&payload[0..4], FACTORY_DATA_MAGIC);
        assert_eq!(payload[4], FACTORY_DATA_VERSION);
        assert_eq!(payload[5], "weather-q8zbgb".len() as u8);
        assert_eq!(&payload[6..20], b"weather-q8zbgb");
        assert!(payload[20..32].iter().all(|byte| *byte == 0));
        let crc = u32::from_le_bytes([payload[32], payload[33], payload[34], payload[35]]);
        assert_eq!(crc, crc32_ieee(&payload[..32]));
    }

    #[test]
    fn rejects_names_that_do_not_fit_ble_local_name() {
        assert!(validate_device_name(&"x".repeat(FACTORY_DEVICE_NAME_SIZE + 1)).is_err());
        assert!(validate_device_name("weather-é").is_err());
        assert!(validate_device_name("weather one").is_err());
        assert_eq!(validate_device_name("weather-1").unwrap(), "weather-1");
    }

    #[test]
    fn writes_intel_hex_at_factory_address() {
        let payload = build_factory_data("weather-1").unwrap();
        let hex = build_intel_hex(DEFAULT_FACTORY_DATA_ADDRESS, &payload).unwrap();

        assert!(hex.starts_with(":02000004000F"));
        assert!(hex.contains(":10"));
        assert!(hex.ends_with(":00000001FF\n"));
    }
}
