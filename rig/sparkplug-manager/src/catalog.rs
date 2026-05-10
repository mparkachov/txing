use std::collections::{BTreeMap, HashMap};

use anyhow::{Result, bail};

use txing_capability_protocol::InventoryDevice;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TypeCatalogDevice {
    pub thing_type: String,
    pub capabilities: Vec<String>,
    pub redcon_command_levels: Vec<u8>,
    pub redcon_rules: BTreeMap<u8, Vec<String>>,
}

impl TypeCatalogDevice {
    pub fn to_inventory_device(&self, thing_name: impl Into<String>) -> InventoryDevice {
        self.to_inventory_device_with_capabilities(thing_name, self.capabilities.clone())
    }

    pub fn to_inventory_device_with_capabilities(
        &self,
        thing_name: impl Into<String>,
        capabilities: Vec<String>,
    ) -> InventoryDevice {
        InventoryDevice {
            thing_name: thing_name.into(),
            thing_type: self.thing_type.clone(),
            capabilities,
            redcon_command_levels: self.redcon_command_levels.clone(),
            redcon_rules: self.redcon_rules.clone(),
        }
    }
}

pub fn reconstruct_type_record(parameters: &[(String, String)]) -> Result<TypeCatalogDevice> {
    let mut thing_type = None;
    let mut capabilities = None;
    let mut redcon_command_levels = None;
    let mut redcon_rules: BTreeMap<u8, Vec<String>> = BTreeMap::new();
    for (name, value) in parameters {
        let Some(leaf) = name.rsplit('/').next() else {
            continue;
        };
        match leaf {
            "thingType" => thing_type = Some(value.clone()),
            "capabilities" => capabilities = Some(parse_string_list(value)?),
            "redconCommandLevels" => {
                redcon_command_levels = Some(parse_redcon_levels(value)?);
            }
            _ => {
                if let Some(level_text) = name.split("/redconRules/").nth(1) {
                    let level_leaf = level_text
                        .split('/')
                        .next()
                        .ok_or_else(|| anyhow::anyhow!("redconRules leaf is malformed"))?;
                    let level = parse_redcon_level(level_leaf)?;
                    redcon_rules.insert(level, parse_string_list(value)?);
                }
            }
        }
    }
    let record = TypeCatalogDevice {
        thing_type: thing_type.ok_or_else(|| anyhow::anyhow!("missing thingType"))?,
        capabilities: capabilities.ok_or_else(|| anyhow::anyhow!("missing capabilities"))?,
        redcon_command_levels: redcon_command_levels
            .ok_or_else(|| anyhow::anyhow!("missing redconCommandLevels"))?,
        redcon_rules,
    };
    validate_type_record(&record)?;
    Ok(record)
}

pub fn validate_type_record(record: &TypeCatalogDevice) -> Result<()> {
    if record.thing_type.trim().is_empty() {
        bail!("thingType must not be empty");
    }
    if !record
        .capabilities
        .iter()
        .any(|capability| capability == "sparkplug")
    {
        bail!("capabilities must include sparkplug");
    }
    let capability_set: HashMap<&str, ()> = record
        .capabilities
        .iter()
        .map(|capability| (capability.as_str(), ()))
        .collect();
    for level in &record.redcon_command_levels {
        validate_redcon(*level)?;
    }
    for (level, capabilities) in &record.redcon_rules {
        validate_redcon(*level)?;
        if capabilities.is_empty() {
            bail!("redconRules.{level} must not be empty");
        }
        for capability in capabilities {
            if !capability_set.contains_key(capability.as_str()) {
                bail!("redconRules.{level} references unknown capability {capability}");
            }
        }
    }
    Ok(())
}

pub fn parse_string_list(value: &str) -> Result<Vec<String>> {
    if value.trim().is_empty() {
        return Ok(Vec::new());
    }
    value
        .split(',')
        .map(|item| {
            let text = item.trim();
            if text.is_empty() {
                bail!("list leaf contains an empty item");
            }
            Ok(text.to_string())
        })
        .collect()
}

fn parse_redcon_levels(value: &str) -> Result<Vec<u8>> {
    parse_string_list(value)?
        .into_iter()
        .map(|item| parse_redcon_level(&item))
        .collect()
}

fn parse_redcon_level(value: &str) -> Result<u8> {
    let level: u8 = value.parse()?;
    validate_redcon(level)?;
    Ok(level)
}

fn validate_redcon(level: u8) -> Result<()> {
    if !(1..=4).contains(&level) {
        bail!("redcon must be between 1 and 4");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reconstructs_redcon_rules_from_ssm_leaf_parameters() {
        let record = reconstruct_type_record(&[
            (
                "/txing/town/raspi/power/thingType".to_string(),
                "power".to_string(),
            ),
            (
                "/txing/town/raspi/power/capabilities".to_string(),
                "sparkplug,ble,power".to_string(),
            ),
            (
                "/txing/town/raspi/power/redconCommandLevels".to_string(),
                "4,3".to_string(),
            ),
            (
                "/txing/town/raspi/power/redconRules/4".to_string(),
                "sparkplug,ble".to_string(),
            ),
            (
                "/txing/town/raspi/power/redconRules/3".to_string(),
                "sparkplug,ble,power".to_string(),
            ),
        ])
        .unwrap();

        assert_eq!(record.thing_type, "power");
        assert_eq!(record.capabilities, vec!["sparkplug", "ble", "power"]);
        assert_eq!(record.redcon_command_levels, vec![4, 3]);
        assert_eq!(
            record.redcon_rules.get(&3).unwrap(),
            &vec![
                "sparkplug".to_string(),
                "ble".to_string(),
                "power".to_string()
            ]
        );
    }
}
