use std::collections::{BTreeMap, BTreeSet};
use std::error::Error as StdError;
use std::fmt::{Debug, Display};

use anyhow::{Context, Result, anyhow};
use async_trait::async_trait;
use aws_sdk_iot::types::AttributePayload;
use aws_sdk_iotdataplane::primitives::Blob;
use chrono::{SecondsFormat, Utc};
use rand::Rng;
use serde_json::{Map, Value, json};

const THING_INDEX_NAME: &str = "AWS_Things";
const SHORT_ID_ALPHABET: &[u8] = b"0123456789abcdefghijklmnopqrstuvwxyz";
const SHORT_ID_LENGTH: usize = 6;
const TOWN_THING_TYPE: &str = "town";
const KIND_TOWN_TYPE: &str = "townType";
const KIND_RIG_TYPE: &str = "rigType";
const KIND_DEVICE_TYPE: &str = "deviceType";
const TOWN_ID_ATTRIBUTE: &str = "townId";
const RIG_ID_ATTRIBUTE: &str = "rigId";
const CFN_DISCHARGE_PHYSICAL_ID: &str = "txing-discharge-things-on-delete";
#[cfg(test)]
const ACTIVE_CFN_DISCHARGE_LOGICAL_ID: &str = "TxingDischargeThingsOnStackDelete";
const TYPE_CATALOG_ROOT: &str = "/txing";
const SPARKPLUG_NAMESPACE: &str = "spBv1.0";
const RIG_TYPE_THING_GROUP_PREFIX: &str = "txing-rig-type-";

const LIST_LEAF_FIELDS: &[&str] = &[
    "capabilities",
    "hostServices",
    "redconCommandLevels",
    "requiredAttributes",
    "searchableAttributes",
];
const REQUIRED_LIST_LEAF_FIELDS: &[&str] =
    &["capabilities", "requiredAttributes", "searchableAttributes"];
const RECORD_KIND_VALUES: &[&str] = &[KIND_TOWN_TYPE, KIND_RIG_TYPE, KIND_DEVICE_TYPE];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EnlistError {
    message: String,
}

impl EnlistError {
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl Display for EnlistError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.message)
    }
}

impl StdError for EnlistError {}

fn enlist_error(message: impl Into<String>) -> anyhow::Error {
    EnlistError::new(message).into()
}

fn enlist_bail<T>(message: impl Into<String>) -> Result<T> {
    Err(enlist_error(message))
}

fn utc_now_iso() -> String {
    Utc::now().to_rfc3339_opts(SecondsFormat::Secs, true)
}

fn error_type(error: &anyhow::Error) -> &'static str {
    if error.downcast_ref::<EnlistError>().is_some() {
        "EnlistError"
    } else {
        "Error"
    }
}

fn py_repr_str(value: &str) -> String {
    format!("'{}'", value.replace('\\', "\\\\").replace('\'', "\\'"))
}

fn py_repr_value(value: Option<&Value>) -> String {
    match value {
        Some(Value::String(text)) => py_repr_str(text),
        Some(Value::Null) | None => "None".to_string(),
        Some(other) => other.to_string(),
    }
}

fn error_is_not_found(error: &(impl Debug + Display)) -> bool {
    let text = format!("{error:?}");
    text.contains("ResourceNotFoundException")
        || text.contains("ResourceNotFound")
        || text.contains("NotFoundException")
        || text.contains("NotFound")
}

fn error_is_already_exists(error: &(impl Debug + Display)) -> bool {
    let text = format!("{error:?}");
    text.contains("ResourceAlreadyExistsException")
        || text.contains("ResourceAlreadyExists")
        || text.contains("AlreadyExists")
}

fn normalize_slug_text(label: &str, value: &str) -> Result<String> {
    let text = value.trim().to_ascii_lowercase();
    if text.is_empty() {
        return enlist_bail(format!("{label} must be non-empty"));
    }
    let mut normalized = String::new();
    let mut previous_dash = false;
    for ch in text.chars() {
        let mapped = if ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '-' {
            ch
        } else {
            '-'
        };
        if mapped == '-' {
            if !normalized.is_empty() && !previous_dash {
                normalized.push('-');
            }
            previous_dash = true;
        } else {
            normalized.push(mapped);
            previous_dash = false;
        }
    }
    while normalized.ends_with('-') {
        normalized.pop();
    }
    if normalized.is_empty()
        || normalized.starts_with('-')
        || normalized.ends_with('-')
        || normalized.contains("--")
        || !normalized
            .chars()
            .all(|ch| ch.is_ascii_lowercase() || ch.is_ascii_digit() || ch == '-')
    {
        return enlist_bail(format!(
            "{label} must normalize to '^[a-z0-9]+(?:-[a-z0-9]+)*$'; got {value:?}"
        ));
    }
    Ok(normalized)
}

fn rig_type_group_name(rig_type: &str) -> Result<String> {
    let normalized = normalize_slug_text("rig type", rig_type)?;
    Ok(format!("{RIG_TYPE_THING_GROUP_PREFIX}{normalized}"))
}

fn require_text_from_value(mapping: &Value, key: &str, context: &str) -> Result<String> {
    let Some(value) = mapping.get(key).and_then(Value::as_str) else {
        return enlist_bail(format!("{context} is missing required field {key:?}"));
    };
    let text = value.trim();
    if text.is_empty() {
        return enlist_bail(format!("{context} is missing required field {key:?}"));
    }
    Ok(text.to_string())
}

fn optional_text_from_value(mapping: &Value, key: &str) -> Option<String> {
    mapping
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(ToOwned::to_owned)
}

fn require_text(record: &Map<String, Value>, key: &str, context: &str) -> Result<String> {
    let Some(value) = record.get(key).and_then(Value::as_str) else {
        return enlist_bail(format!("{context} is missing required field {key:?}"));
    };
    let text = value.trim();
    if text.is_empty() {
        return enlist_bail(format!("{context} is missing required field {key:?}"));
    }
    Ok(text.to_string())
}

fn require_thing_attribute(
    attributes: &BTreeMap<String, String>,
    key: &str,
    context: &str,
) -> Result<String> {
    attributes
        .get(key)
        .map(String::as_str)
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(ToOwned::to_owned)
        .ok_or_else(|| enlist_error(format!("{context} is missing required field {key:?}")))
}

fn iot_attribute_value(label: &str, value: &str) -> Result<String> {
    if value.chars().all(is_iot_attribute_char) {
        return Ok(value.to_string());
    }
    let mut encoded = String::new();
    let mut previous_dash = false;
    for ch in value.chars() {
        if is_iot_attribute_char(ch) {
            encoded.push(ch);
            previous_dash = false;
        } else if !encoded.is_empty() && !previous_dash {
            encoded.push('-');
            previous_dash = true;
        }
    }
    while encoded.ends_with('-') {
        encoded.pop();
    }
    if encoded.is_empty() || !encoded.chars().all(is_iot_attribute_char) {
        return enlist_bail(format!(
            "IoT registry attribute {label:?} cannot be encoded into '^[a-zA-Z0-9_.,@/:#=\\[\\]-]*$': {value:?}"
        ));
    }
    Ok(encoded)
}

fn is_iot_attribute_char(ch: char) -> bool {
    ch.is_ascii_alphanumeric()
        || matches!(
            ch,
            '_' | '.' | ',' | '@' | '/' | ':' | '#' | '=' | '[' | ']' | '-'
        )
}

fn iot_attributes(attributes: BTreeMap<String, String>) -> Result<BTreeMap<String, String>> {
    attributes
        .into_iter()
        .map(|(key, value)| {
            let encoded = iot_attribute_value(&key, &value)?;
            Ok((key, encoded))
        })
        .collect()
}

fn list_value(record: &Map<String, Value>, key: &str, context: &str) -> Result<Vec<String>> {
    let Some(values) = record.get(key).and_then(Value::as_array) else {
        return enlist_bail(format!("{context} is missing required list field {key:?}"));
    };
    let mut result = Vec::with_capacity(values.len());
    for value in values {
        let Some(item) = value
            .as_str()
            .map(str::trim)
            .filter(|item| !item.is_empty())
        else {
            return enlist_bail(format!("{context} is missing required list field {key:?}"));
        };
        result.push(item.to_string());
    }
    Ok(result)
}

fn encode_capabilities_set(capabilities: &[String]) -> Result<String> {
    if capabilities.is_empty() {
        return enlist_bail("capability set must not be empty");
    }
    Ok(capabilities.join(","))
}

fn parse_capabilities_set(value: &str, thing_name: &str) -> Result<Vec<String>> {
    if value.trim().is_empty() {
        return enlist_bail(format!(
            "Thing {thing_name:?} is missing required IoT registry attribute 'capabilities'"
        ));
    }
    let mut capabilities = Vec::new();
    let mut seen = BTreeSet::new();
    for raw in value.split(',') {
        let capability = raw.trim();
        if capability.is_empty() || capability != raw {
            return enlist_bail(format!(
                "Thing {thing_name:?} has malformed 'capabilities': {value:?}"
            ));
        }
        if !seen.insert(capability.to_string()) {
            return enlist_bail(format!(
                "Thing {thing_name:?} has duplicate capability {capability:?}"
            ));
        }
        capabilities.push(capability.to_string());
    }
    if !seen.contains("sparkplug") {
        return enlist_bail(format!(
            "Thing {thing_name:?} capability set must include 'sparkplug'"
        ));
    }
    Ok(capabilities)
}

fn capabilities(record: &Map<String, Value>, context: &str) -> Result<Vec<String>> {
    let values = list_value(record, "capabilities", context)?;
    parse_capabilities_set(&encode_capabilities_set(&values)?, context)
}

fn record_context(record: &Map<String, Value>) -> String {
    record
        .get("path")
        .and_then(Value::as_str)
        .unwrap_or("type catalog record")
        .to_string()
}

fn town_type_path() -> String {
    catalog_path(&["town"])
}

fn rig_type_path(rig_type: &str) -> String {
    catalog_path(&["town", rig_type])
}

fn device_type_path(rig_type: &str, device_type: &str) -> String {
    catalog_path(&["town", rig_type, device_type])
}

fn catalog_path(parts: &[&str]) -> String {
    let mut path = TYPE_CATALOG_ROOT.to_string();
    for part in parts {
        path.push('/');
        path.push_str(part);
    }
    path
}

fn normalize_catalog_path(value: &str) -> String {
    let mut text = value.trim();
    if let Some(stripped) = text.strip_prefix("ssm:") {
        text = stripped;
    }
    if text.is_empty() {
        return TYPE_CATALOG_ROOT.to_string();
    }
    if text == TYPE_CATALOG_ROOT || text.starts_with(&format!("{TYPE_CATALOG_ROOT}/")) {
        return text.trim_end_matches('/').to_string();
    }
    format!("{TYPE_CATALOG_ROOT}/{}", text.trim_matches('/'))
}

fn parse_list_leaf(parameter_name: &str, value: &str) -> Result<Value> {
    if value.trim().is_empty() {
        return Ok(Value::Array(Vec::new()));
    }
    let mut items = Vec::new();
    for raw in value.split(',') {
        let item = raw.trim();
        if item.is_empty() {
            return enlist_bail(format!(
                "SSM type catalog leaf {parameter_name:?} contains an empty list item"
            ));
        }
        items.push(Value::String(item.to_string()));
    }
    Ok(Value::Array(items))
}

fn assign_record_leaf(
    record: &mut Map<String, Value>,
    parameter_name: &str,
    leaf_path: &[&str],
    value: &str,
) -> Result<()> {
    if leaf_path.is_empty() {
        return Ok(());
    }
    let decoded = if leaf_path.len() == 1 && LIST_LEAF_FIELDS.contains(&leaf_path[0]) {
        parse_list_leaf(parameter_name, value)?
    } else if leaf_path.len() == 2 && leaf_path[0] == "redconRules" {
        parse_list_leaf(parameter_name, value)?
    } else {
        Value::String(value.to_string())
    };

    let mut cursor = record;
    for part in &leaf_path[..leaf_path.len() - 1] {
        let entry = cursor
            .entry((*part).to_string())
            .or_insert_with(|| Value::Object(Map::new()));
        let Some(child) = entry.as_object_mut() else {
            return enlist_bail(format!(
                "SSM type catalog leaf {parameter_name:?} collides with another leaf"
            ));
        };
        cursor = child;
    }
    cursor.insert(leaf_path[leaf_path.len() - 1].to_string(), decoded);
    Ok(())
}

fn reconstruct_record_from_parameters(
    path: &str,
    parameters: &[ParameterRecord],
) -> Result<Map<String, Value>> {
    let normalized_path = normalize_catalog_path(path);
    let prefix = format!("{normalized_path}/");
    let child_record_prefixes: Vec<String> = parameters
        .iter()
        .filter_map(|parameter| {
            let record_path = parameter.name.strip_suffix("/kind")?;
            if record_path == normalized_path {
                return None;
            }
            if !record_path.starts_with(&prefix) {
                return None;
            }
            if !RECORD_KIND_VALUES.contains(&parameter.value.as_str()) {
                return None;
            }
            Some(format!("{record_path}/"))
        })
        .collect();

    let mut record = Map::new();
    for parameter in parameters {
        if !parameter.name.starts_with(&prefix) {
            continue;
        }
        if child_record_prefixes
            .iter()
            .any(|child_prefix| parameter.name.starts_with(child_prefix))
        {
            continue;
        }
        let relative_name = &parameter.name[prefix.len()..];
        if relative_name.is_empty() {
            continue;
        }
        let leaf_path: Vec<&str> = relative_name.split('/').collect();
        assign_record_leaf(&mut record, &parameter.name, &leaf_path, &parameter.value)?;
    }

    let kind = record
        .get("kind")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .to_string();
    if !RECORD_KIND_VALUES.contains(&kind.as_str()) {
        return enlist_bail(format!(
            "Missing SSM type catalog record {normalized_path:?}; run aws::deploy"
        ));
    }
    record
        .entry("path".to_string())
        .or_insert_with(|| Value::String(normalized_path.clone()));
    if kind == KIND_RIG_TYPE {
        record
            .entry("hostServices".to_string())
            .or_insert_with(|| Value::Array(Vec::new()));
    }
    for field_name in REQUIRED_LIST_LEAF_FIELDS {
        let Some(values) = record.get(*field_name).and_then(Value::as_array) else {
            return enlist_bail(format!(
                "SSM type catalog record {normalized_path:?} is missing {field_name}"
            ));
        };
        if values.is_empty()
            || values
                .iter()
                .any(|value| value.as_str().map(str::trim).unwrap_or("").is_empty())
        {
            return enlist_bail(format!(
                "SSM type catalog record {normalized_path:?} is missing {field_name}"
            ));
        }
    }
    Ok(record)
}

fn sparkplug_shadow_payload(
    payload: Value,
    topic: Option<Value>,
    projection: Option<Value>,
) -> Value {
    let mut reported = Map::new();
    reported.insert("payload".to_string(), payload);
    if let Some(topic) = topic {
        reported.insert("topic".to_string(), topic);
    }
    if let Some(projection) = projection {
        if !projection.as_object().is_some_and(Map::is_empty) {
            reported.insert("projection".to_string(), projection);
        }
    }
    json!({ "state": { "reported": reported } })
}

fn static_group_shadow_payload(_group_id: &str) -> Value {
    sparkplug_shadow_payload(json!({ "metrics": { "redcon": 1 } }), None, None)
}

fn offline_node_shadow_payload(group_id: &str, edge_node_id: &str) -> Value {
    sparkplug_shadow_payload(
        json!({ "metrics": { "redcon": 4 } }),
        Some(json!({
            "namespace": SPARKPLUG_NAMESPACE,
            "groupId": group_id,
            "messageType": "NDEATH",
            "edgeNodeId": edge_node_id,
        })),
        None,
    )
}

fn offline_device_shadow_payload(group_id: &str, edge_node_id: &str, device_id: &str) -> Value {
    sparkplug_shadow_payload(
        json!({ "metrics": {} }),
        Some(json!({
            "namespace": SPARKPLUG_NAMESPACE,
            "groupId": group_id,
            "messageType": "DDEATH",
            "edgeNodeId": edge_node_id,
            "deviceId": device_id,
        })),
        None,
    )
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThingRecord {
    pub thing_name: String,
    pub thing_type_name: String,
    pub attributes: BTreeMap<String, String>,
    pub version: Option<i64>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SearchPage {
    pub thing_names: Vec<String>,
    pub next_token: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParameterRecord {
    pub name: String,
    pub value: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ParameterPage {
    pub parameters: Vec<ParameterRecord>,
    pub next_token: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PrincipalPage {
    pub principals: Vec<String>,
    pub next_token: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ThingGroupMembershipPage {
    pub thing_group_names: Vec<String>,
    pub next_token: Option<String>,
}

#[async_trait]
pub trait EnlistAws: Send + Sync {
    async fn describe_thing(&self, thing_name: &str) -> Result<Option<ThingRecord>>;
    async fn create_thing(
        &self,
        thing_name: &str,
        thing_type_name: &str,
        attributes: BTreeMap<String, String>,
    ) -> Result<()>;
    async fn update_thing_attributes(
        &self,
        thing_name: &str,
        attributes: BTreeMap<String, String>,
        expected_version: Option<i64>,
    ) -> Result<()>;
    async fn delete_thing(&self, thing_name: &str) -> Result<bool>;
    async fn search_index(&self, query: &str, next_token: Option<&str>) -> Result<SearchPage>;
    async fn get_shadow(&self, thing_name: &str, shadow_name: &str) -> Result<Option<Vec<u8>>>;
    async fn update_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
        payload: Vec<u8>,
    ) -> Result<()>;
    async fn delete_shadow(&self, thing_name: &str, shadow_name: &str) -> Result<bool>;
    async fn get_parameters_by_path(
        &self,
        path: &str,
        next_token: Option<&str>,
    ) -> Result<ParameterPage>;
    async fn list_thing_principals(
        &self,
        thing_name: &str,
        next_token: Option<&str>,
    ) -> Result<PrincipalPage>;
    async fn detach_thing_principal(&self, thing_name: &str, principal: &str) -> Result<()>;
    async fn create_thing_group(&self, thing_group_name: &str) -> Result<()>;
    async fn list_thing_groups_for_thing(
        &self,
        thing_name: &str,
        next_token: Option<&str>,
    ) -> Result<ThingGroupMembershipPage>;
    async fn add_thing_to_thing_group(
        &self,
        thing_name: &str,
        thing_group_name: &str,
    ) -> Result<()>;
    async fn remove_thing_from_thing_group(
        &self,
        thing_name: &str,
        thing_group_name: &str,
    ) -> Result<()>;
}

#[derive(Clone)]
pub struct AwsEnlistClient {
    iot: aws_sdk_iot::Client,
    iot_data: aws_sdk_iotdataplane::Client,
    ssm: aws_sdk_ssm::Client,
}

impl AwsEnlistClient {
    pub async fn from_env() -> Result<Self> {
        let config = aws_config::load_defaults(aws_config::BehaviorVersion::latest()).await;
        let iot = aws_sdk_iot::Client::new(&config);
        let endpoint = iot
            .describe_endpoint()
            .endpoint_type("iot:Data-ATS")
            .send()
            .await
            .context("describe AWS IoT data endpoint")?
            .endpoint_address()
            .ok_or_else(|| anyhow!("AWS IoT describe_endpoint returned no endpointAddress"))?
            .to_string();
        let data_config = aws_sdk_iotdataplane::config::Builder::from(&config)
            .endpoint_url(format!("https://{endpoint}"))
            .build();
        Ok(Self {
            iot,
            iot_data: aws_sdk_iotdataplane::Client::from_conf(data_config),
            ssm: aws_sdk_ssm::Client::new(&config),
        })
    }
}

#[async_trait]
impl EnlistAws for AwsEnlistClient {
    async fn describe_thing(&self, thing_name: &str) -> Result<Option<ThingRecord>> {
        match self
            .iot
            .describe_thing()
            .thing_name(thing_name)
            .send()
            .await
        {
            Ok(response) => {
                let Some(returned_name) = response.thing_name() else {
                    return enlist_bail(format!(
                        "Thing {thing_name:?} returned invalid thing name"
                    ));
                };
                let Some(thing_type_name) = response.thing_type_name() else {
                    return enlist_bail(format!(
                        "Thing {thing_name:?} returned invalid thing type"
                    ));
                };
                Ok(Some(ThingRecord {
                    thing_name: returned_name.to_string(),
                    thing_type_name: thing_type_name.to_string(),
                    attributes: response
                        .attributes()
                        .cloned()
                        .unwrap_or_default()
                        .into_iter()
                        .collect(),
                    version: Some(response.version()),
                }))
            }
            Err(err) if error_is_not_found(&err) => Ok(None),
            Err(err) => Err(anyhow!(err)).context("describe AWS IoT thing"),
        }
    }

    async fn create_thing(
        &self,
        thing_name: &str,
        thing_type_name: &str,
        attributes: BTreeMap<String, String>,
    ) -> Result<()> {
        self.iot
            .create_thing()
            .thing_name(thing_name)
            .thing_type_name(thing_type_name)
            .attribute_payload(
                AttributePayload::builder()
                    .set_attributes(Some(attributes.into_iter().collect()))
                    .build(),
            )
            .send()
            .await
            .context("create AWS IoT thing")?;
        Ok(())
    }

    async fn update_thing_attributes(
        &self,
        thing_name: &str,
        attributes: BTreeMap<String, String>,
        expected_version: Option<i64>,
    ) -> Result<()> {
        let mut request = self
            .iot
            .update_thing()
            .thing_name(thing_name)
            .attribute_payload(
                AttributePayload::builder()
                    .set_attributes(Some(attributes.into_iter().collect()))
                    .merge(true)
                    .build(),
            );
        if let Some(version) = expected_version {
            request = request.expected_version(version);
        }
        request
            .send()
            .await
            .context("update AWS IoT thing attributes")?;
        Ok(())
    }

    async fn delete_thing(&self, thing_name: &str) -> Result<bool> {
        match self.iot.delete_thing().thing_name(thing_name).send().await {
            Ok(_) => Ok(true),
            Err(err) if error_is_not_found(&err) => Ok(false),
            Err(err) => Err(anyhow!(err)).context("delete AWS IoT thing"),
        }
    }

    async fn search_index(&self, query: &str, next_token: Option<&str>) -> Result<SearchPage> {
        let mut request = self
            .iot
            .search_index()
            .index_name(THING_INDEX_NAME)
            .query_string(query)
            .max_results(100);
        if let Some(token) = next_token {
            request = request.next_token(token);
        }
        let response = request.send().await.context("search AWS IoT thing index")?;
        Ok(SearchPage {
            thing_names: response
                .things()
                .iter()
                .filter_map(|thing| thing.thing_name().map(str::trim))
                .filter(|thing_name| !thing_name.is_empty())
                .map(ToOwned::to_owned)
                .collect(),
            next_token: response
                .next_token()
                .map(str::trim)
                .filter(|token| !token.is_empty())
                .map(ToOwned::to_owned),
        })
    }

    async fn get_shadow(&self, thing_name: &str, shadow_name: &str) -> Result<Option<Vec<u8>>> {
        match self
            .iot_data
            .get_thing_shadow()
            .thing_name(thing_name)
            .shadow_name(shadow_name)
            .send()
            .await
        {
            Ok(output) => Ok(output.payload().map(|payload| payload.as_ref().to_vec())),
            Err(err) if error_is_not_found(&err) => Ok(None),
            Err(err) => Err(anyhow!(err)).context("get AWS IoT thing shadow"),
        }
    }

    async fn update_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
        payload: Vec<u8>,
    ) -> Result<()> {
        self.iot_data
            .update_thing_shadow()
            .thing_name(thing_name)
            .shadow_name(shadow_name)
            .payload(Blob::new(payload))
            .send()
            .await
            .context("update AWS IoT thing shadow")?;
        Ok(())
    }

    async fn delete_shadow(&self, thing_name: &str, shadow_name: &str) -> Result<bool> {
        match self
            .iot_data
            .delete_thing_shadow()
            .thing_name(thing_name)
            .shadow_name(shadow_name)
            .send()
            .await
        {
            Ok(_) => Ok(true),
            Err(err) if error_is_not_found(&err) => Ok(false),
            Err(err) => Err(anyhow!(err)).context("delete AWS IoT thing shadow"),
        }
    }

    async fn get_parameters_by_path(
        &self,
        path: &str,
        next_token: Option<&str>,
    ) -> Result<ParameterPage> {
        let mut request = self
            .ssm
            .get_parameters_by_path()
            .path(path)
            .recursive(true)
            .with_decryption(false);
        if let Some(token) = next_token {
            request = request.next_token(token);
        }
        let response = request
            .send()
            .await
            .context("read SSM type catalog parameters")?;
        Ok(ParameterPage {
            parameters: response
                .parameters()
                .iter()
                .filter_map(|parameter| {
                    Some(ParameterRecord {
                        name: parameter.name()?.to_string(),
                        value: parameter.value()?.to_string(),
                    })
                })
                .collect(),
            next_token: response
                .next_token()
                .map(str::trim)
                .filter(|token| !token.is_empty())
                .map(ToOwned::to_owned),
        })
    }

    async fn list_thing_principals(
        &self,
        thing_name: &str,
        next_token: Option<&str>,
    ) -> Result<PrincipalPage> {
        let mut request = self.iot.list_thing_principals().thing_name(thing_name);
        if let Some(token) = next_token {
            request = request.next_token(token);
        }
        match request.send().await {
            Ok(response) => Ok(PrincipalPage {
                principals: response.principals().to_vec(),
                next_token: response
                    .next_token()
                    .map(str::trim)
                    .filter(|token| !token.is_empty())
                    .map(ToOwned::to_owned),
            }),
            Err(err) if error_is_not_found(&err) => Ok(PrincipalPage {
                principals: Vec::new(),
                next_token: None,
            }),
            Err(err) => Err(anyhow!(err)).context("list AWS IoT thing principals"),
        }
    }

    async fn detach_thing_principal(&self, thing_name: &str, principal: &str) -> Result<()> {
        match self
            .iot
            .detach_thing_principal()
            .thing_name(thing_name)
            .principal(principal)
            .send()
            .await
        {
            Ok(_) => Ok(()),
            Err(err) if error_is_not_found(&err) => Ok(()),
            Err(err) => Err(anyhow!(err)).context("detach AWS IoT thing principal"),
        }
    }

    async fn create_thing_group(&self, thing_group_name: &str) -> Result<()> {
        match self
            .iot
            .create_thing_group()
            .thing_group_name(thing_group_name)
            .send()
            .await
        {
            Ok(_) => Ok(()),
            Err(err) if error_is_already_exists(&err) => Ok(()),
            Err(err) => Err(anyhow!(err)).context("create AWS IoT thing group"),
        }
    }

    async fn list_thing_groups_for_thing(
        &self,
        thing_name: &str,
        next_token: Option<&str>,
    ) -> Result<ThingGroupMembershipPage> {
        let mut request = self
            .iot
            .list_thing_groups_for_thing()
            .thing_name(thing_name);
        if let Some(token) = next_token {
            request = request.next_token(token);
        }
        match request.send().await {
            Ok(response) => Ok(ThingGroupMembershipPage {
                thing_group_names: response
                    .thing_groups()
                    .iter()
                    .filter_map(|group| group.group_name().map(str::trim))
                    .filter(|name| !name.is_empty())
                    .map(ToOwned::to_owned)
                    .collect(),
                next_token: response
                    .next_token()
                    .map(str::trim)
                    .filter(|token| !token.is_empty())
                    .map(ToOwned::to_owned),
            }),
            Err(err) if error_is_not_found(&err) => Ok(ThingGroupMembershipPage {
                thing_group_names: Vec::new(),
                next_token: None,
            }),
            Err(err) => Err(anyhow!(err)).context("list AWS IoT thing groups for thing"),
        }
    }

    async fn add_thing_to_thing_group(
        &self,
        thing_name: &str,
        thing_group_name: &str,
    ) -> Result<()> {
        self.iot
            .add_thing_to_thing_group()
            .thing_name(thing_name)
            .thing_group_name(thing_group_name)
            .send()
            .await
            .context("add AWS IoT thing to thing group")?;
        Ok(())
    }

    async fn remove_thing_from_thing_group(
        &self,
        thing_name: &str,
        thing_group_name: &str,
    ) -> Result<()> {
        match self
            .iot
            .remove_thing_from_thing_group()
            .thing_name(thing_name)
            .thing_group_name(thing_group_name)
            .send()
            .await
        {
            Ok(_) => Ok(()),
            Err(err) if error_is_not_found(&err) => Ok(()),
            Err(err) => Err(anyhow!(err)).context("remove AWS IoT thing from thing group"),
        }
    }
}

pub trait ShortIdSource: Send {
    fn next_short_id(&mut self) -> String;
}

#[derive(Debug, Default)]
pub struct RandomShortIds;

impl ShortIdSource for RandomShortIds {
    fn next_short_id(&mut self) -> String {
        let mut rng = rand::thread_rng();
        (0..SHORT_ID_LENGTH)
            .map(|_| {
                let index = rng.gen_range(0..SHORT_ID_ALPHABET.len());
                SHORT_ID_ALPHABET[index] as char
            })
            .collect()
    }
}

#[derive(Debug, Clone, PartialEq)]
struct EnlistResult {
    thing_name: String,
    thing_type_name: String,
    created: bool,
    attributes: BTreeMap<String, String>,
    initialized_shadows: Vec<String>,
    auxiliary_resources: Value,
}

impl EnlistResult {
    fn to_payload(&self) -> Value {
        json!({
            "thingName": self.thing_name,
            "thingTypeName": self.thing_type_name,
            "created": self.created,
            "attributes": self.attributes,
            "initializedShadows": self.initialized_shadows,
            "auxiliaryResources": self.auxiliary_resources,
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
struct DischargeResult {
    thing_name: String,
    thing_type_name: Option<String>,
    deleted: bool,
    attributes: BTreeMap<String, String>,
    deleted_shadows: Vec<String>,
    detached_principals: Vec<String>,
    auxiliary_resources: Value,
}

impl DischargeResult {
    fn missing(thing_name: String) -> Self {
        Self {
            thing_name,
            thing_type_name: None,
            deleted: false,
            attributes: BTreeMap::new(),
            deleted_shadows: Vec::new(),
            detached_principals: Vec::new(),
            auxiliary_resources: json!({}),
        }
    }

    fn to_payload(&self) -> Value {
        json!({
            "thingName": self.thing_name,
            "thingTypeName": self.thing_type_name,
            "deleted": self.deleted,
            "attributes": self.attributes,
            "deletedShadows": self.deleted_shadows,
            "detachedPrincipals": self.detached_principals,
            "auxiliaryResources": self.auxiliary_resources,
        })
    }
}

pub struct EnlistService<'a, A: EnlistAws + ?Sized, R: ShortIdSource> {
    aws: &'a A,
    ids: R,
}

impl<'a, A: EnlistAws + ?Sized, R: ShortIdSource> EnlistService<'a, A, R> {
    pub fn new(aws: &'a A, ids: R) -> Self {
        Self { aws, ids }
    }

    pub async fn handle(&mut self, event: &Value) -> Result<Value> {
        let action = require_text_from_value(event, "action", "enlist event")?;
        match action.as_str() {
            "enlistTown" => {
                let town_name = require_text_from_value(event, "townName", "enlistTown")?;
                Ok(self.enlist_town(&town_name).await?.to_payload())
            }
            "enlistRig" => {
                let town_id = require_text_from_value(event, "townId", "enlistRig")?;
                let rig_type = require_text_from_value(event, "rigType", "enlistRig")?;
                let rig_name = require_text_from_value(event, "rigName", "enlistRig")?;
                Ok(self
                    .enlist_rig(&town_id, &rig_type, &rig_name)
                    .await?
                    .to_payload())
            }
            "enlistDevice" => {
                let rig_id = require_text_from_value(event, "rigId", "enlistDevice")?;
                let device_type = require_text_from_value(event, "deviceType", "enlistDevice")?;
                let device_name = optional_text_from_value(event, "deviceName");
                Ok(self
                    .enlist_device(&rig_id, &device_type, device_name.as_deref())
                    .await?
                    .to_payload())
            }
            "assignDevice" => {
                let device_id = require_text_from_value(event, "deviceId", "assignDevice")?;
                let rig_id = require_text_from_value(event, "rigId", "assignDevice")?;
                Ok(self.assign_device(&device_id, &rig_id).await?.to_payload())
            }
            "dischargeThing" => {
                let thing_id = require_text_from_value(event, "thingId", "dischargeThing")?;
                Ok(self.discharge_thing(&thing_id).await?.to_payload())
            }
            "dischargeAll" => Ok(self.discharge_all().await?),
            _ => enlist_bail(format!(
                "unsupported enlist action: {}",
                py_repr_str(&action)
            )),
        }
    }

    async fn describe_thing(&self, thing_name: &str) -> Result<ThingRecord> {
        self.aws
            .describe_thing(thing_name)
            .await?
            .ok_or_else(|| enlist_error(format!("Thing {thing_name:?} is not registered")))
    }

    async fn allocate_thing_name(&mut self, thing_type: &str) -> Result<(String, String)> {
        let prefix = normalize_slug_text("thing type", thing_type)?;
        for _ in 0..256 {
            let short_id = self.ids.next_short_id();
            let thing_name = format!("{prefix}-{short_id}");
            if self.aws.describe_thing(&thing_name).await?.is_none() {
                return Ok((thing_name, short_id));
            }
        }
        enlist_bail(format!(
            "failed to allocate a unique thing name for type {thing_type:?}"
        ))
    }

    async fn search_one(&self, query: &str, missing: &str, multiple: &str) -> Result<ThingRecord> {
        let names = self.search_thing_names(query).await?;
        if names.is_empty() {
            return enlist_bail(missing.to_string());
        }
        if names.len() > 1 {
            return enlist_bail(multiple.to_string());
        }
        self.describe_thing(&names[0]).await
    }

    async fn search_thing_names(&self, query: &str) -> Result<Vec<String>> {
        let mut names = BTreeSet::new();
        let mut next_token = None;
        loop {
            let page = self
                .aws
                .search_index(query, next_token.as_deref())
                .await
                .with_context(|| format!("search AWS IoT thing index for {query:?}"))?;
            names.extend(page.thing_names);
            next_token = page.next_token;
            if next_token.is_none() {
                break;
            }
        }
        Ok(names.into_iter().collect())
    }

    async fn find_town(&self, town_name: &str) -> Result<Option<ThingRecord>> {
        match self
            .search_one(
                &format!(
                    "thingTypeName:{TOWN_THING_TYPE} AND attributes.kind:{KIND_TOWN_TYPE} AND attributes.name:{town_name}"
                ),
                &format!("Town {town_name:?} is not registered"),
                &format!("Town {town_name:?} matched multiple things"),
            )
            .await
        {
            Ok(thing) => Ok(Some(thing)),
            Err(error) if error.to_string().contains("is not registered") => Ok(None),
            Err(error) => Err(error),
        }
    }

    async fn find_rig(
        &self,
        town_id: &str,
        rig_type: &str,
        rig_name: &str,
    ) -> Result<Option<ThingRecord>> {
        match self
            .search_one(
                &format!(
                    "thingTypeName:{rig_type} AND attributes.kind:{KIND_RIG_TYPE} AND attributes.name:{rig_name} AND attributes.{TOWN_ID_ATTRIBUTE}:{town_id}"
                ),
                &format!("Rig {rig_name:?} is not registered under town {town_id:?}"),
                &format!("Rig {rig_name:?} matched multiple things under town {town_id:?}"),
            )
            .await
        {
            Ok(thing) => Ok(Some(thing)),
            Err(error) if error.to_string().contains("is not registered") => Ok(None),
            Err(error) => Err(error),
        }
    }

    async fn find_device(
        &self,
        rig_id: &str,
        device_type: &str,
        device_name: &str,
    ) -> Result<Option<ThingRecord>> {
        match self
            .search_one(
                &format!(
                    "thingTypeName:{device_type} AND attributes.kind:{KIND_DEVICE_TYPE} AND attributes.name:{device_name} AND attributes.{RIG_ID_ATTRIBUTE}:{rig_id}"
                ),
                &format!("Device {device_name:?} is not registered under rig {rig_id:?}"),
                &format!("Device {device_name:?} matched multiple things under rig {rig_id:?}"),
            )
            .await
        {
            Ok(thing) => Ok(Some(thing)),
            Err(error) if error.to_string().contains("is not registered") => Ok(None),
            Err(error) => Err(error),
        }
    }

    async fn read_parameters_by_path(&self, path: &str) -> Result<Vec<ParameterRecord>> {
        let normalized_path = normalize_catalog_path(path);
        let mut parameters = Vec::new();
        let mut next_token = None;
        loop {
            let page = self
                .aws
                .get_parameters_by_path(&normalized_path, next_token.as_deref())
                .await?;
            parameters.extend(page.parameters);
            next_token = page.next_token;
            if next_token.is_none() {
                break;
            }
        }
        parameters.sort_by(|left, right| left.name.cmp(&right.name));
        Ok(parameters)
    }

    async fn type_record(&self, path: &str) -> Result<Map<String, Value>> {
        let normalized_path = normalize_catalog_path(path);
        reconstruct_record_from_parameters(
            &normalized_path,
            &self.read_parameters_by_path(&normalized_path).await?,
        )
    }

    async fn rig_type_record(&self, rig_type: &str) -> Result<Map<String, Value>> {
        self.type_record(&rig_type_path(rig_type)).await
    }

    async fn device_type_record(
        &self,
        rig_type: &str,
        device_type: &str,
    ) -> Result<Map<String, Value>> {
        self.type_record(&device_type_path(rig_type, device_type))
            .await
    }

    async fn device_record_for_rig(
        &self,
        rig: &ThingRecord,
        device_type: &str,
    ) -> Result<Map<String, Value>> {
        match self
            .device_type_record(&rig.thing_type_name, device_type)
            .await
        {
            Ok(record) => Ok(record),
            Err(_) => enlist_bail(format!(
                "Device type {} is not compatible with rig type {}; missing SSM type catalog record {}",
                py_repr_str(device_type),
                py_repr_str(&rig.thing_type_name),
                py_repr_str(&device_type_path(&rig.thing_type_name, device_type)),
            )),
        }
    }

    fn base_attributes(
        &self,
        record: &Map<String, Value>,
        name: &str,
        short_id: &str,
    ) -> Result<BTreeMap<String, String>> {
        let context = record_context(record);
        let kind = require_text(record, "kind", &context)?;
        let type_path = require_text(record, "path", &context)?;
        let display_name = require_text(record, "displayName", &context)?;
        let capabilities = encode_capabilities_set(&capabilities(record, &context)?)?;
        let mut attributes = BTreeMap::from([
            ("name".to_string(), name.to_string()),
            ("shortId".to_string(), short_id.to_string()),
            ("kind".to_string(), kind),
            ("typePath".to_string(), type_path),
            ("displayName".to_string(), display_name),
            ("capabilities".to_string(), capabilities),
        ]);
        if record.get("redconCommandLevels").is_some() {
            attributes.insert(
                "redconCommandLevels".to_string(),
                list_value(record, "redconCommandLevels", &context)?.join(","),
            );
        }
        iot_attributes(attributes)
    }

    async fn update_thing_attributes(
        &self,
        thing: &ThingRecord,
        attributes: BTreeMap<String, String>,
    ) -> Result<()> {
        self.aws
            .update_thing_attributes(&thing.thing_name, attributes, thing.version)
            .await
    }

    async fn list_thing_group_names(&self, thing_name: &str) -> Result<Vec<String>> {
        let mut names = BTreeSet::new();
        let mut next_token = None;
        loop {
            let page = self
                .aws
                .list_thing_groups_for_thing(thing_name, next_token.as_deref())
                .await
                .with_context(|| format!("list AWS IoT thing groups for {thing_name}"))?;
            names.extend(page.thing_group_names);
            next_token = page.next_token;
            if next_token.is_none() {
                break;
            }
        }
        Ok(names.into_iter().collect())
    }

    async fn ensure_rig_type_group_membership(
        &self,
        thing_name: &str,
        rig_type: &str,
    ) -> Result<String> {
        let target_group = rig_type_group_name(rig_type)?;
        self.aws.create_thing_group(&target_group).await?;
        for group in self.list_thing_group_names(thing_name).await? {
            if group.starts_with(RIG_TYPE_THING_GROUP_PREFIX) && group != target_group {
                self.aws
                    .remove_thing_from_thing_group(thing_name, &group)
                    .await?;
            }
        }
        self.aws
            .add_thing_to_thing_group(thing_name, &target_group)
            .await?;
        Ok(target_group)
    }

    async fn ensure_shadow(
        &self,
        thing_name: &str,
        shadow_name: &str,
        payload: ShadowPayload,
    ) -> Result<bool> {
        if self
            .aws
            .get_shadow(thing_name, shadow_name)
            .await?
            .is_some()
        {
            return Ok(false);
        }
        self.aws
            .update_shadow(thing_name, shadow_name, payload.into_bytes()?)
            .await?;
        Ok(true)
    }

    async fn initialize_town_shadows(&self, thing_name: &str) -> Result<Vec<String>> {
        if self
            .ensure_shadow(
                thing_name,
                "sparkplug",
                ShadowPayload::Json(static_group_shadow_payload(thing_name)),
            )
            .await?
        {
            Ok(vec!["sparkplug".to_string()])
        } else {
            Ok(Vec::new())
        }
    }

    async fn initialize_rig_shadows(
        &self,
        thing_name: &str,
        town_id: &str,
        rig_id: &str,
    ) -> Result<Vec<String>> {
        if self
            .ensure_shadow(
                thing_name,
                "sparkplug",
                ShadowPayload::Json(offline_node_shadow_payload(town_id, rig_id)),
            )
            .await?
        {
            Ok(vec!["sparkplug".to_string()])
        } else {
            Ok(Vec::new())
        }
    }

    async fn initialize_device_shadows(
        &self,
        thing_name: &str,
        record: &Map<String, Value>,
        town_id: &str,
        rig_id: &str,
    ) -> Result<Vec<String>> {
        let mut initialized = Vec::new();
        for shadow_name in capabilities(record, &record_context(record))? {
            let payload = if shadow_name == "sparkplug" {
                ShadowPayload::Json(offline_device_shadow_payload(town_id, rig_id, thing_name))
            } else {
                let shadow_record = record
                    .get("shadows")
                    .and_then(Value::as_object)
                    .and_then(|shadows| shadows.get(&shadow_name))
                    .and_then(Value::as_object)
                    .ok_or_else(|| {
                        enlist_error(format!(
                            "type catalog record {:?} is missing shadow {shadow_name:?}",
                            record_context(record)
                        ))
                    })?;
                ShadowPayload::Text(require_text(
                    shadow_record,
                    "defaultPayload",
                    &format!("shadow {shadow_name:?}"),
                )?)
            };
            if self
                .ensure_shadow(thing_name, &shadow_name, payload)
                .await?
            {
                initialized.push(shadow_name);
            }
        }
        Ok(initialized)
    }

    fn thing_result(
        &self,
        thing: &ThingRecord,
        created: bool,
        attributes: BTreeMap<String, String>,
        initialized_shadows: Vec<String>,
        auxiliary_resources: Value,
    ) -> EnlistResult {
        EnlistResult {
            thing_name: thing.thing_name.clone(),
            thing_type_name: thing.thing_type_name.clone(),
            created,
            attributes,
            initialized_shadows,
            auxiliary_resources,
        }
    }

    async fn enlist_town(&mut self, town_name: &str) -> Result<EnlistResult> {
        let normalized_town_name = normalize_slug_text("town name", town_name)?;
        let record = self.type_record(&town_type_path()).await?;
        let existing = self.find_town(&normalized_town_name).await?;
        let created = existing.is_none();
        let thing = if let Some(existing) = existing {
            let short_id =
                require_thing_attribute(&existing.attributes, "shortId", "town attributes")?;
            let attributes = self.base_attributes(&record, &normalized_town_name, &short_id)?;
            self.update_thing_attributes(&existing, attributes).await?;
            self.describe_thing(&existing.thing_name).await?
        } else {
            let (thing_name, short_id) = self.allocate_thing_name(TOWN_THING_TYPE).await?;
            let attributes = self.base_attributes(&record, &normalized_town_name, &short_id)?;
            self.aws
                .create_thing(&thing_name, TOWN_THING_TYPE, attributes)
                .await?;
            self.describe_thing(&thing_name).await?
        };
        let attributes = self.base_attributes(
            &record,
            &normalized_town_name,
            require_thing_attribute(&thing.attributes, "shortId", "town attributes")?.as_str(),
        )?;
        let initialized = self.initialize_town_shadows(&thing.thing_name).await?;
        Ok(self.thing_result(&thing, created, attributes, initialized, json!({})))
    }

    async fn enlist_rig(
        &mut self,
        town_id: &str,
        rig_type: &str,
        rig_name: &str,
    ) -> Result<EnlistResult> {
        let normalized_town_id = normalize_slug_text("town id", town_id)?;
        let normalized_rig_type = normalize_slug_text("rig type", rig_type)?;
        let normalized_rig_name = normalize_slug_text("rig name", rig_name)?;
        let town = self.describe_thing(&normalized_town_id).await?;
        if town.thing_type_name != TOWN_THING_TYPE
            || town.attributes.get("kind").map(String::as_str) != Some(KIND_TOWN_TYPE)
        {
            return enlist_bail(format!("Thing {normalized_town_id:?} is not a town"));
        }
        let record = self.rig_type_record(&normalized_rig_type).await?;
        let existing = self
            .find_rig(
                &normalized_town_id,
                &normalized_rig_type,
                &normalized_rig_name,
            )
            .await?;
        let created = existing.is_none();
        let host_services = if record.get("hostServices").is_some() {
            list_value(&record, "hostServices", &record_context(&record))?
        } else {
            Vec::new()
        };
        let build_attributes =
            |service: &Self, short_id: &str| -> Result<BTreeMap<String, String>> {
                let mut attributes =
                    service.base_attributes(&record, &normalized_rig_name, short_id)?;
                attributes.insert(TOWN_ID_ATTRIBUTE.to_string(), normalized_town_id.clone());
                attributes.insert("rigType".to_string(), normalized_rig_type.clone());
                if !host_services.is_empty() {
                    attributes.insert("hostServices".to_string(), host_services.join(","));
                }
                Ok(attributes)
            };
        let thing = if let Some(existing) = existing {
            let short_id =
                require_thing_attribute(&existing.attributes, "shortId", "rig attributes")?;
            self.update_thing_attributes(&existing, build_attributes(self, &short_id)?)
                .await?;
            self.describe_thing(&existing.thing_name).await?
        } else {
            let (thing_name, short_id) = self.allocate_thing_name(&normalized_rig_type).await?;
            self.aws
                .create_thing(
                    &thing_name,
                    &normalized_rig_type,
                    build_attributes(self, &short_id)?,
                )
                .await?;
            self.describe_thing(&thing_name).await?
        };
        let attributes = build_attributes(
            self,
            require_thing_attribute(&thing.attributes, "shortId", "rig attributes")?.as_str(),
        )?;
        let initialized = self
            .initialize_rig_shadows(&thing.thing_name, &normalized_town_id, &thing.thing_name)
            .await?;
        let thing_group_name = self
            .ensure_rig_type_group_membership(&thing.thing_name, &normalized_rig_type)
            .await?;
        Ok(self.thing_result(
            &thing,
            created,
            attributes,
            initialized,
            json!({ "thingGroupName": thing_group_name }),
        ))
    }

    async fn enlist_device(
        &mut self,
        rig_id: &str,
        device_type: &str,
        device_name: Option<&str>,
    ) -> Result<EnlistResult> {
        let normalized_rig_id = normalize_slug_text("rig id", rig_id)?;
        let normalized_device_type = normalize_slug_text("device type", device_type)?;
        let rig = self.describe_thing(&normalized_rig_id).await?;
        if rig.attributes.get("kind").map(String::as_str) != Some(KIND_RIG_TYPE) {
            return enlist_bail(format!("Thing {normalized_rig_id:?} is not a rig"));
        }
        let town_id =
            require_thing_attribute(&rig.attributes, TOWN_ID_ATTRIBUTE, "rig attributes")?;
        let town = self.describe_thing(&town_id).await?;
        if town.attributes.get("kind").map(String::as_str) != Some(KIND_TOWN_TYPE) {
            return enlist_bail(format!("Thing {town_id:?} is not a town"));
        }
        let record = self
            .device_record_for_rig(&rig, &normalized_device_type)
            .await?;
        let default_name = require_text(&record, "defaultName", &record_context(&record))?;
        let normalized_device_name =
            normalize_slug_text("device name", device_name.unwrap_or(&default_name))?;
        let existing = self
            .find_device(
                &normalized_rig_id,
                &normalized_device_type,
                &normalized_device_name,
            )
            .await?;
        let created = existing.is_none();
        let rig_type = rig.thing_type_name.clone();
        let build_attributes =
            |service: &Self, short_id: &str| -> Result<BTreeMap<String, String>> {
                let mut attributes =
                    service.base_attributes(&record, &normalized_device_name, short_id)?;
                attributes.insert(TOWN_ID_ATTRIBUTE.to_string(), town_id.clone());
                attributes.insert(RIG_ID_ATTRIBUTE.to_string(), normalized_rig_id.clone());
                attributes.insert("rigType".to_string(), rig_type.clone());
                attributes.insert("deviceType".to_string(), normalized_device_type.clone());
                if let Some(adapter) = record
                    .get("web")
                    .and_then(Value::as_object)
                    .and_then(|web| web.get("adapter"))
                    .and_then(Value::as_str)
                {
                    attributes.insert("webAdapter".to_string(), adapter.to_string());
                }
                iot_attributes(attributes)
            };
        let thing = if let Some(existing) = existing {
            let short_id =
                require_thing_attribute(&existing.attributes, "shortId", "device attributes")?;
            self.update_thing_attributes(&existing, build_attributes(self, &short_id)?)
                .await?;
            self.describe_thing(&existing.thing_name).await?
        } else {
            let (thing_name, short_id) = self.allocate_thing_name(&normalized_device_type).await?;
            self.aws
                .create_thing(
                    &thing_name,
                    &normalized_device_type,
                    build_attributes(self, &short_id)?,
                )
                .await?;
            self.describe_thing(&thing_name).await?
        };
        let attributes = build_attributes(
            self,
            require_thing_attribute(&thing.attributes, "shortId", "device attributes")?.as_str(),
        )?;
        let initialized = self
            .initialize_device_shadows(&thing.thing_name, &record, &town_id, &normalized_rig_id)
            .await?;
        Ok(self.thing_result(&thing, created, attributes, initialized, json!({})))
    }

    async fn assign_device(&self, device_id: &str, rig_id: &str) -> Result<EnlistResult> {
        let normalized_device_id = normalize_slug_text("device id", device_id)?;
        let normalized_rig_id = normalize_slug_text("rig id", rig_id)?;
        let device = self.describe_thing(&normalized_device_id).await?;
        let rig = self.describe_thing(&normalized_rig_id).await?;
        if rig.attributes.get("kind").map(String::as_str) != Some(KIND_RIG_TYPE) {
            return enlist_bail(format!("Thing {normalized_rig_id:?} is not a rig"));
        }
        let device_type = device.thing_type_name.clone();
        let record = self.device_record_for_rig(&rig, &device_type).await?;
        let rig_type = rig.thing_type_name.clone();
        let town_id =
            require_thing_attribute(&rig.attributes, TOWN_ID_ATTRIBUTE, "rig attributes")?;
        let mut attributes = self.base_attributes(
            &record,
            &require_thing_attribute(&device.attributes, "name", "device attributes")?,
            &require_thing_attribute(&device.attributes, "shortId", "device attributes")?,
        )?;
        attributes.insert(TOWN_ID_ATTRIBUTE.to_string(), town_id);
        attributes.insert(RIG_ID_ATTRIBUTE.to_string(), normalized_rig_id);
        attributes.insert("rigType".to_string(), rig_type);
        attributes.insert("deviceType".to_string(), device_type);
        if let Some(adapter) = record
            .get("web")
            .and_then(Value::as_object)
            .and_then(|web| web.get("adapter"))
            .and_then(Value::as_str)
        {
            attributes.insert("webAdapter".to_string(), adapter.to_string());
        }
        let attributes = iot_attributes(attributes)?;
        self.update_thing_attributes(&device, attributes.clone())
            .await?;
        let updated = self.describe_thing(&normalized_device_id).await?;
        Ok(self.thing_result(&updated, false, attributes, Vec::new(), json!({})))
    }

    async fn detach_thing_principals(&self, thing_name: &str) -> Result<Vec<String>> {
        let mut detached = Vec::new();
        let mut next_token = None;
        loop {
            let page = self
                .aws
                .list_thing_principals(thing_name, next_token.as_deref())
                .await?;
            for principal in page.principals {
                if principal.trim().is_empty() {
                    continue;
                }
                self.aws
                    .detach_thing_principal(thing_name, &principal)
                    .await?;
                detached.push(principal);
            }
            next_token = page.next_token;
            if next_token.is_none() {
                break;
            }
        }
        Ok(detached)
    }

    async fn discharge_thing(&self, thing_id: &str) -> Result<DischargeResult> {
        let normalized_thing_id = normalize_slug_text("thing id", thing_id)?;
        let Some(thing) = self.aws.describe_thing(&normalized_thing_id).await? else {
            return Ok(DischargeResult::missing(normalized_thing_id));
        };
        let capabilities = parse_capabilities_set(
            &require_thing_attribute(
                &thing.attributes,
                "capabilities",
                &format!("thing {:?} attributes", thing.thing_name),
            )?,
            &thing.thing_name,
        )?;
        let mut deleted_shadows = Vec::new();
        for shadow_name in capabilities {
            if self
                .aws
                .delete_shadow(&thing.thing_name, &shadow_name)
                .await?
            {
                deleted_shadows.push(shadow_name);
            }
        }
        let detached_principals = self.detach_thing_principals(&thing.thing_name).await?;
        let deleted = self.aws.delete_thing(&thing.thing_name).await?;
        Ok(DischargeResult {
            thing_name: thing.thing_name,
            thing_type_name: Some(thing.thing_type_name),
            deleted,
            attributes: thing.attributes,
            deleted_shadows,
            detached_principals,
            auxiliary_resources: json!({}),
        })
    }

    async fn discharge_all(&self) -> Result<Value> {
        let mut results = Vec::new();
        for kind in [KIND_DEVICE_TYPE, KIND_RIG_TYPE, KIND_TOWN_TYPE] {
            for thing_name in self
                .search_thing_names(&format!("attributes.kind:{kind}"))
                .await?
            {
                results.push(self.discharge_thing(&thing_name).await?);
            }
        }
        let deleted_count = results.iter().filter(|result| result.deleted).count();
        Ok(json!({
            "deletedThings": results.iter().map(DischargeResult::to_payload).collect::<Vec<_>>(),
            "deletedThingCount": deleted_count,
        }))
    }
}

enum ShadowPayload {
    Json(Value),
    Text(String),
}

impl ShadowPayload {
    fn into_bytes(self) -> Result<Vec<u8>> {
        match self {
            Self::Json(value) => serde_json::to_vec(&value).context("encode shadow payload"),
            Self::Text(value) => Ok(value.into_bytes()),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CfnStatus {
    Success,
    Failed,
}

impl CfnStatus {
    fn as_str(self) -> &'static str {
        match self {
            Self::Success => "SUCCESS",
            Self::Failed => "FAILED",
        }
    }
}

#[async_trait]
pub trait CfnResponder: Send + Sync {
    async fn send(
        &self,
        event: &Value,
        status: CfnStatus,
        data: Value,
        reason: Option<String>,
        physical_resource_id: String,
    ) -> Result<()>;
}

#[derive(Debug, Clone, Default)]
pub struct HttpCfnResponder {
    client: reqwest::Client,
}

#[async_trait]
impl CfnResponder for HttpCfnResponder {
    async fn send(
        &self,
        event: &Value,
        status: CfnStatus,
        data: Value,
        reason: Option<String>,
        physical_resource_id: String,
    ) -> Result<()> {
        let response_url = require_text_from_value(event, "ResponseURL", "CloudFormation event")?;
        let body = json!({
            "Status": status.as_str(),
            "Reason": reason.unwrap_or_else(|| "See CloudWatch log stream: txing-enlist-lambda".to_string()),
            "PhysicalResourceId": physical_resource_id,
            "StackId": require_text_from_value(event, "StackId", "CloudFormation event")?,
            "RequestId": require_text_from_value(event, "RequestId", "CloudFormation event")?,
            "LogicalResourceId": require_text_from_value(event, "LogicalResourceId", "CloudFormation event")?,
            "NoEcho": false,
            "Data": data,
        })
        .to_string();
        self.client
            .put(response_url)
            .header("content-type", "")
            .header("content-length", body.len().to_string())
            .body(body)
            .send()
            .await
            .context("send CloudFormation custom resource response")?
            .error_for_status()
            .context("CloudFormation custom resource response failed")?;
        Ok(())
    }
}

fn is_cfn_custom_resource_event(event: &Value) -> bool {
    matches!(
        event.get("RequestType").and_then(Value::as_str),
        Some("Create" | "Update" | "Delete")
    ) && event.get("ResponseURL").and_then(Value::as_str).is_some()
        && event
            .get("ResourceProperties")
            .and_then(Value::as_object)
            .is_some()
}

async fn handle_cfn_custom_resource<A, R, C>(
    event: &Value,
    service: &mut EnlistService<'_, A, R>,
    responder: &C,
) -> Value
where
    A: EnlistAws + ?Sized,
    R: ShortIdSource,
    C: CfnResponder + ?Sized,
{
    let properties = event
        .get("ResourceProperties")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    let physical_resource_id = event
        .get("PhysicalResourceId")
        .and_then(Value::as_str)
        .or_else(|| properties.get("PhysicalResourceId").and_then(Value::as_str))
        .unwrap_or(CFN_DISCHARGE_PHYSICAL_ID)
        .to_string();
    match handle_cfn_custom_resource_inner(event, service).await {
        Ok(data) => {
            if let Err(error) = responder
                .send(
                    event,
                    CfnStatus::Success,
                    data.clone(),
                    None,
                    physical_resource_id,
                )
                .await
            {
                return json!({
                    "ok": false,
                    "errorType": error_type(&error),
                    "message": error.to_string(),
                });
            }
            let mut payload = data.as_object().cloned().unwrap_or_default();
            payload.insert("ok".to_string(), Value::Bool(true));
            Value::Object(payload)
        }
        Err(error) => {
            let _ = responder
                .send(
                    event,
                    CfnStatus::Failed,
                    json!({}),
                    Some(error.to_string()),
                    physical_resource_id,
                )
                .await;
            json!({
                "ok": false,
                "errorType": error_type(&error),
                "message": error.to_string(),
            })
        }
    }
}

async fn handle_cfn_custom_resource_inner<A, R>(
    event: &Value,
    service: &mut EnlistService<'_, A, R>,
) -> Result<Value>
where
    A: EnlistAws + ?Sized,
    R: ShortIdSource,
{
    let properties = event
        .get("ResourceProperties")
        .and_then(Value::as_object)
        .ok_or_else(|| enlist_error("CloudFormation event is missing ResourceProperties"))?;
    if properties.get("CleanupType").and_then(Value::as_str) != Some("TxingDischargeThings") {
        return enlist_bail(format!(
            "Unsupported CleanupType: {}",
            py_repr_value(properties.get("CleanupType"))
        ));
    }
    if event.get("RequestType").and_then(Value::as_str) == Some("Delete") {
        service.discharge_all().await
    } else {
        Ok(json!({ "skipped": true }))
    }
}

pub async fn handle_lambda_event<A, C>(event: Value, aws: &A, responder: &C) -> Value
where
    A: EnlistAws + ?Sized,
    C: CfnResponder + ?Sized,
{
    let mut service = EnlistService::new(aws, RandomShortIds);
    handle_lambda_event_with_service(event, &mut service, responder).await
}

pub async fn handle_lambda_event_with_service<A, R, C>(
    event: Value,
    service: &mut EnlistService<'_, A, R>,
    responder: &C,
) -> Value
where
    A: EnlistAws + ?Sized,
    R: ShortIdSource,
    C: CfnResponder + ?Sized,
{
    if is_cfn_custom_resource_event(&event) {
        return handle_cfn_custom_resource(&event, service, responder).await;
    }
    match service.handle(&event).await {
        Ok(mut result) => {
            let Some(object) = result.as_object_mut() else {
                return json!({
                    "ok": false,
                    "errorType": "Error",
                    "message": "enlist action returned a non-object payload",
                    "processedAt": utc_now_iso(),
                });
            };
            object.insert("ok".to_string(), Value::Bool(true));
            object.insert("processedAt".to_string(), Value::String(utc_now_iso()));
            result
        }
        Err(error) => json!({
            "ok": false,
            "errorType": error_type(&error),
            "message": error.to_string(),
            "processedAt": utc_now_iso(),
        }),
    }
}

#[cfg(test)]
mod tests {
    use std::collections::{BTreeMap, VecDeque};
    use std::sync::{Arc, Mutex};

    use anyhow::bail;

    use super::*;

    #[derive(Debug, Clone)]
    struct SequenceShortIds {
        ids: VecDeque<String>,
        next: usize,
    }

    impl SequenceShortIds {
        fn new() -> Self {
            Self {
                ids: VecDeque::from(vec![
                    "000001".to_string(),
                    "000002".to_string(),
                    "000003".to_string(),
                    "000004".to_string(),
                    "000005".to_string(),
                    "000006".to_string(),
                    "000007".to_string(),
                    "000008".to_string(),
                ]),
                next: 9,
            }
        }
    }

    impl ShortIdSource for SequenceShortIds {
        fn next_short_id(&mut self) -> String {
            self.ids.pop_front().unwrap_or_else(|| {
                let value = format!("{:06}", self.next);
                self.next += 1;
                value
            })
        }
    }

    #[derive(Debug, Clone, Default)]
    struct FakeAws {
        state: Arc<Mutex<FakeState>>,
    }

    #[derive(Debug, Default)]
    struct FakeState {
        things: BTreeMap<String, ThingRecord>,
        shadows: BTreeMap<(String, String), Vec<u8>>,
        shadow_updates: Vec<(String, String, Vec<u8>)>,
        parameters: BTreeMap<String, String>,
        principals: BTreeMap<String, Vec<String>>,
        thing_groups: BTreeMap<String, BTreeSet<String>>,
        parameter_page_size: Option<usize>,
        search_page_size: Option<usize>,
    }

    impl FakeAws {
        fn seeded() -> Self {
            let aws = Self::default();
            seed_type_catalog(&aws);
            aws
        }

        fn put_parameter(&self, name: &str, value: &str) {
            self.state
                .lock()
                .unwrap()
                .parameters
                .insert(name.to_string(), value.to_string());
        }

        fn put_shadow(&self, thing_name: &str, shadow_name: &str, payload: &[u8]) {
            self.state.lock().unwrap().shadows.insert(
                (thing_name.to_string(), shadow_name.to_string()),
                payload.to_vec(),
            );
        }

        fn shadow_json(&self, thing_name: &str, shadow_name: &str) -> Value {
            let state = self.state.lock().unwrap();
            serde_json::from_slice(
                state
                    .shadows
                    .get(&(thing_name.to_string(), shadow_name.to_string()))
                    .expect("shadow exists"),
            )
            .expect("shadow json")
        }

        fn shadow_bytes(&self, thing_name: &str, shadow_name: &str) -> Vec<u8> {
            self.state
                .lock()
                .unwrap()
                .shadows
                .get(&(thing_name.to_string(), shadow_name.to_string()))
                .expect("shadow exists")
                .clone()
        }

        fn shadow_update_count(&self) -> usize {
            self.state.lock().unwrap().shadow_updates.len()
        }

        fn thing_attributes(&self, thing_name: &str) -> BTreeMap<String, String> {
            self.state
                .lock()
                .unwrap()
                .things
                .get(thing_name)
                .expect("thing exists")
                .attributes
                .clone()
        }

        fn remove_attribute(&self, thing_name: &str, attribute: &str) {
            self.state
                .lock()
                .unwrap()
                .things
                .get_mut(thing_name)
                .expect("thing exists")
                .attributes
                .remove(attribute);
        }

        fn add_principals(&self, thing_name: &str, principals: Vec<&str>) {
            self.state.lock().unwrap().principals.insert(
                thing_name.to_string(),
                principals.into_iter().map(ToOwned::to_owned).collect(),
            );
        }

        fn thing_names(&self) -> BTreeSet<String> {
            self.state.lock().unwrap().things.keys().cloned().collect()
        }

        fn thing_group_members(&self, thing_group_name: &str) -> BTreeSet<String> {
            self.state
                .lock()
                .unwrap()
                .thing_groups
                .get(thing_group_name)
                .cloned()
                .unwrap_or_default()
        }

        fn set_parameter_page_size(&self, size: usize) {
            self.state.lock().unwrap().parameter_page_size = Some(size);
        }

        fn set_search_page_size(&self, size: usize) {
            self.state.lock().unwrap().search_page_size = Some(size);
        }
    }

    #[async_trait]
    impl EnlistAws for FakeAws {
        async fn describe_thing(&self, thing_name: &str) -> Result<Option<ThingRecord>> {
            Ok(self.state.lock().unwrap().things.get(thing_name).cloned())
        }

        async fn create_thing(
            &self,
            thing_name: &str,
            thing_type_name: &str,
            attributes: BTreeMap<String, String>,
        ) -> Result<()> {
            validate_iot_attributes(&attributes)?;
            let mut state = self.state.lock().unwrap();
            if state.things.contains_key(thing_name) {
                bail!("thing already exists");
            }
            state.things.insert(
                thing_name.to_string(),
                ThingRecord {
                    thing_name: thing_name.to_string(),
                    thing_type_name: thing_type_name.to_string(),
                    attributes,
                    version: Some(1),
                },
            );
            Ok(())
        }

        async fn update_thing_attributes(
            &self,
            thing_name: &str,
            attributes: BTreeMap<String, String>,
            expected_version: Option<i64>,
        ) -> Result<()> {
            validate_iot_attributes(&attributes)?;
            let mut state = self.state.lock().unwrap();
            let thing = state
                .things
                .get_mut(thing_name)
                .ok_or_else(|| anyhow!("thing not found"))?;
            if expected_version.is_some() && expected_version != thing.version {
                bail!("version conflict");
            }
            thing.attributes.extend(attributes);
            thing.version = Some(thing.version.unwrap_or(0) + 1);
            Ok(())
        }

        async fn delete_thing(&self, thing_name: &str) -> Result<bool> {
            let mut state = self.state.lock().unwrap();
            if state
                .principals
                .get(thing_name)
                .is_some_and(|principals| !principals.is_empty())
            {
                bail!("principals are still attached");
            }
            Ok(state.things.remove(thing_name).is_some())
        }

        async fn search_index(&self, query: &str, next_token: Option<&str>) -> Result<SearchPage> {
            let state = self.state.lock().unwrap();
            let mut names: Vec<String> = state
                .things
                .values()
                .filter(|thing| matches_query(thing, query))
                .map(|thing| thing.thing_name.clone())
                .collect();
            names.sort();
            let start = next_token
                .and_then(|token| token.parse::<usize>().ok())
                .unwrap_or(0);
            if let Some(page_size) = state.search_page_size {
                let end = usize::min(start + page_size, names.len());
                Ok(SearchPage {
                    thing_names: names[start..end].to_vec(),
                    next_token: (end < names.len()).then(|| end.to_string()),
                })
            } else {
                Ok(SearchPage {
                    thing_names: names,
                    next_token: None,
                })
            }
        }

        async fn get_shadow(&self, thing_name: &str, shadow_name: &str) -> Result<Option<Vec<u8>>> {
            Ok(self
                .state
                .lock()
                .unwrap()
                .shadows
                .get(&(thing_name.to_string(), shadow_name.to_string()))
                .cloned())
        }

        async fn update_shadow(
            &self,
            thing_name: &str,
            shadow_name: &str,
            payload: Vec<u8>,
        ) -> Result<()> {
            let mut state = self.state.lock().unwrap();
            state.shadows.insert(
                (thing_name.to_string(), shadow_name.to_string()),
                payload.clone(),
            );
            state
                .shadow_updates
                .push((thing_name.to_string(), shadow_name.to_string(), payload));
            Ok(())
        }

        async fn delete_shadow(&self, thing_name: &str, shadow_name: &str) -> Result<bool> {
            Ok(self
                .state
                .lock()
                .unwrap()
                .shadows
                .remove(&(thing_name.to_string(), shadow_name.to_string()))
                .is_some())
        }

        async fn get_parameters_by_path(
            &self,
            path: &str,
            next_token: Option<&str>,
        ) -> Result<ParameterPage> {
            let state = self.state.lock().unwrap();
            let normalized = normalize_catalog_path(path);
            let prefix = format!("{normalized}/");
            let mut parameters: Vec<ParameterRecord> = state
                .parameters
                .iter()
                .filter(|(name, _)| name.starts_with(&prefix))
                .map(|(name, value)| ParameterRecord {
                    name: name.clone(),
                    value: value.clone(),
                })
                .collect();
            parameters.sort_by(|left, right| left.name.cmp(&right.name));
            let start = next_token
                .and_then(|token| token.parse::<usize>().ok())
                .unwrap_or(0);
            if let Some(page_size) = state.parameter_page_size {
                let end = usize::min(start + page_size, parameters.len());
                Ok(ParameterPage {
                    parameters: parameters[start..end].to_vec(),
                    next_token: (end < parameters.len()).then(|| end.to_string()),
                })
            } else {
                Ok(ParameterPage {
                    parameters,
                    next_token: None,
                })
            }
        }

        async fn list_thing_principals(
            &self,
            thing_name: &str,
            _next_token: Option<&str>,
        ) -> Result<PrincipalPage> {
            Ok(PrincipalPage {
                principals: self
                    .state
                    .lock()
                    .unwrap()
                    .principals
                    .get(thing_name)
                    .cloned()
                    .unwrap_or_default(),
                next_token: None,
            })
        }

        async fn detach_thing_principal(&self, thing_name: &str, principal: &str) -> Result<()> {
            let mut state = self.state.lock().unwrap();
            if let Some(principals) = state.principals.get_mut(thing_name) {
                principals.retain(|candidate| candidate != principal);
            }
            Ok(())
        }

        async fn create_thing_group(&self, thing_group_name: &str) -> Result<()> {
            self.state
                .lock()
                .unwrap()
                .thing_groups
                .entry(thing_group_name.to_string())
                .or_default();
            Ok(())
        }

        async fn list_thing_groups_for_thing(
            &self,
            thing_name: &str,
            _next_token: Option<&str>,
        ) -> Result<ThingGroupMembershipPage> {
            let mut thing_group_names = self
                .state
                .lock()
                .unwrap()
                .thing_groups
                .iter()
                .filter(|(_, members)| members.contains(thing_name))
                .map(|(name, _)| name.clone())
                .collect::<Vec<_>>();
            thing_group_names.sort();
            Ok(ThingGroupMembershipPage {
                thing_group_names,
                next_token: None,
            })
        }

        async fn add_thing_to_thing_group(
            &self,
            thing_name: &str,
            thing_group_name: &str,
        ) -> Result<()> {
            let mut state = self.state.lock().unwrap();
            if !state.things.contains_key(thing_name) {
                bail!("thing not found");
            }
            state
                .thing_groups
                .entry(thing_group_name.to_string())
                .or_default()
                .insert(thing_name.to_string());
            Ok(())
        }

        async fn remove_thing_from_thing_group(
            &self,
            thing_name: &str,
            thing_group_name: &str,
        ) -> Result<()> {
            if let Some(members) = self
                .state
                .lock()
                .unwrap()
                .thing_groups
                .get_mut(thing_group_name)
            {
                members.remove(thing_name);
            }
            Ok(())
        }
    }

    #[derive(Debug, Clone, Default)]
    struct FakeResponder {
        calls: Arc<Mutex<Vec<CfnCall>>>,
    }

    #[derive(Debug, Clone, PartialEq)]
    struct CfnCall {
        status: CfnStatus,
        data: Value,
        reason: Option<String>,
        physical_resource_id: String,
    }

    #[async_trait]
    impl CfnResponder for FakeResponder {
        async fn send(
            &self,
            _event: &Value,
            status: CfnStatus,
            data: Value,
            reason: Option<String>,
            physical_resource_id: String,
        ) -> Result<()> {
            self.calls.lock().unwrap().push(CfnCall {
                status,
                data,
                reason,
                physical_resource_id,
            });
            Ok(())
        }
    }

    fn validate_iot_attributes(attributes: &BTreeMap<String, String>) -> Result<()> {
        for (key, value) in attributes {
            if !value.chars().all(is_iot_attribute_char) {
                bail!("invalid attribute {key}={value:?}");
            }
        }
        Ok(())
    }

    fn matches_query(thing: &ThingRecord, query: &str) -> bool {
        query.split(" AND ").all(|predicate| {
            let (key, value) = predicate.split_once(':').unwrap_or((predicate, ""));
            if key == "thingTypeName" {
                return value == "*" || thing.thing_type_name == value;
            }
            if let Some(attribute_name) = key.strip_prefix("attributes.") {
                let attribute_value = thing.attributes.get(attribute_name);
                return value == "*" && attribute_value.is_some()
                    || attribute_value.map(String::as_str) == Some(value);
            }
            false
        })
    }

    fn seed_type_catalog(aws: &FakeAws) {
        put_record(
            aws,
            "/txing/town",
            &[
                ("kind", "townType"),
                ("displayName", "Town"),
                ("defaultName", "town"),
                ("capabilities", "sparkplug"),
                ("requiredAttributes", "name,shortId"),
                ("searchableAttributes", "name"),
            ],
        );
        put_record(
            aws,
            "/txing/town/cloud",
            &[
                ("kind", "rigType"),
                ("thingType", "cloud"),
                ("rigType", "cloud"),
                ("displayName", "Cloud Rig"),
                ("defaultName", "aws"),
                ("capabilities", "sparkplug"),
                ("requiredAttributes", "name,shortId,townId"),
                ("searchableAttributes", "name,townId"),
            ],
        );
        put_record(
            aws,
            "/txing/town/raspi",
            &[
                ("kind", "rigType"),
                ("thingType", "raspi"),
                ("rigType", "raspi"),
                ("displayName", "Raspberry Pi Rig"),
                ("defaultName", "server"),
                ("capabilities", "sparkplug"),
                ("hostServices", "bluetooth.service"),
                ("requiredAttributes", "name,shortId,townId"),
                ("searchableAttributes", "name,townId"),
            ],
        );
        put_record(
            aws,
            "/txing/town/cloud/time",
            &[
                ("kind", "deviceType"),
                ("thingType", "time"),
                ("deviceType", "time"),
                ("rigType", "cloud"),
                ("displayName", "Time"),
                ("defaultName", "clock"),
                ("capabilities", "sparkplug,mcp,time"),
                ("redconCommandLevels", "4,1"),
                ("redconRules/4", "sparkplug"),
                ("redconRules/1", "sparkplug,time,mcp"),
                ("requiredAttributes", "name,shortId,townId,rigId"),
                ("searchableAttributes", "name,townId,rigId"),
                ("web/adapter", "web/time-adapter.tsx"),
                ("shadows/mcp/defaultPayload", r#"{"state":{"reported":{}}}"#),
                (
                    "shadows/time/defaultPayload",
                    r#"{"state":{"reported":{"mode":"sleep"}}}"#,
                ),
            ],
        );
        put_record(
            aws,
            "/txing/town/raspi/unit",
            &[
                ("kind", "deviceType"),
                ("thingType", "unit"),
                ("deviceType", "unit"),
                ("rigType", "raspi"),
                ("displayName", "Unit"),
                ("defaultName", "bot"),
                ("capabilities", "sparkplug,mcu,board,mcp,video"),
                ("redconCommandLevels", "4,3,2,1"),
                ("redconRules/4", "sparkplug"),
                ("redconRules/3", "sparkplug,mcu"),
                ("redconRules/2", "sparkplug,mcu,board"),
                ("redconRules/1", "sparkplug,mcu,board,mcp,video"),
                ("requiredAttributes", "name,shortId,townId,rigId"),
                ("searchableAttributes", "name,townId,rigId"),
                ("web/adapter", "web/unit-adapter.tsx"),
                ("shadows/mcu/defaultPayload", r#"{"state":{"reported":{}}}"#),
                (
                    "shadows/board/defaultPayload",
                    r#"{"state":{"reported":{}}}"#,
                ),
                ("shadows/mcp/defaultPayload", r#"{"state":{"reported":{}}}"#),
                (
                    "shadows/video/defaultPayload",
                    r#"{"state":{"reported":{}}}"#,
                ),
            ],
        );
    }

    fn put_record(aws: &FakeAws, path: &str, leaves: &[(&str, &str)]) {
        for (leaf, value) in leaves {
            aws.put_parameter(&format!("{path}/{leaf}"), value);
        }
    }

    fn result_str(value: &Value, key: &str) -> String {
        value[key].as_str().expect("string field").to_string()
    }

    async fn enlist_town(service: &mut EnlistService<'_, FakeAws, SequenceShortIds>) -> Value {
        service
            .handle(&json!({"action": "enlistTown", "townName": "town"}))
            .await
            .unwrap()
    }

    async fn enlist_rig(
        service: &mut EnlistService<'_, FakeAws, SequenceShortIds>,
        town_id: &str,
        rig_type: &str,
        rig_name: &str,
    ) -> Value {
        service
            .handle(&json!({
                "action": "enlistRig",
                "townId": town_id,
                "rigType": rig_type,
                "rigName": rig_name,
            }))
            .await
            .unwrap()
    }

    async fn enlist_device(
        service: &mut EnlistService<'_, FakeAws, SequenceShortIds>,
        rig_id: &str,
        device_type: &str,
        device_name: &str,
    ) -> Value {
        service
            .handle(&json!({
                "action": "enlistDevice",
                "rigId": rig_id,
                "deviceType": device_type,
                "deviceName": device_name,
            }))
            .await
            .unwrap()
    }

    #[tokio::test]
    async fn enlist_town_creates_attributes_and_sparkplug_shadow() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());

        let result = enlist_town(&mut service).await;

        assert_eq!(result["created"], true);
        assert_eq!(result["thingTypeName"], "town");
        assert_eq!(result["thingName"], "town-000001");
        assert_eq!(
            result["attributes"],
            json!({
                "name": "town",
                "shortId": "000001",
                "kind": "townType",
                "typePath": "/txing/town",
                "displayName": "Town",
                "capabilities": "sparkplug",
            })
        );
        assert_eq!(result["initializedShadows"], json!(["sparkplug"]));
        let shadow = aws.shadow_json("town-000001", "sparkplug");
        assert_eq!(
            shadow["state"]["reported"]["payload"]["metrics"]["redcon"],
            1
        );
    }

    #[tokio::test]
    async fn enlist_rigs_use_type_catalog_attributes_and_initialize_shadow() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;

        let cloud = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let raspi = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "raspi",
            "server",
        )
        .await;

        assert_eq!(cloud["thingTypeName"], "cloud");
        assert_eq!(cloud["attributes"]["kind"], "rigType");
        assert_eq!(cloud["attributes"]["rigType"], "cloud");
        assert_eq!(cloud["attributes"]["displayName"], "Cloud-Rig");
        assert_eq!(cloud["attributes"]["townId"], town["thingName"]);
        assert!(cloud["attributes"].get("hostServices").is_none());
        assert_eq!(cloud["initializedShadows"], json!(["sparkplug"]));
        assert_eq!(
            cloud["auxiliaryResources"],
            json!({ "thingGroupName": "txing-rig-type-cloud" })
        );
        assert_eq!(
            aws.thing_group_members("txing-rig-type-cloud"),
            BTreeSet::from([result_str(&cloud, "thingName")])
        );

        assert_eq!(raspi["thingTypeName"], "raspi");
        assert_eq!(raspi["attributes"]["displayName"], "Raspberry-Pi-Rig");
        assert_eq!(raspi["attributes"]["hostServices"], "bluetooth.service");
        assert_eq!(
            raspi["auxiliaryResources"],
            json!({ "thingGroupName": "txing-rig-type-raspi" })
        );
        assert_eq!(
            aws.thing_group_members("txing-rig-type-raspi"),
            BTreeSet::from([result_str(&raspi, "thingName")])
        );
    }

    #[tokio::test]
    async fn repeated_enlist_repairs_rig_type_group_membership() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let cloud = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let thing_name = result_str(&cloud, "thingName");
        aws.create_thing_group("txing-rig-type-raspi")
            .await
            .unwrap();
        aws.add_thing_to_thing_group(&thing_name, "txing-rig-type-raspi")
            .await
            .unwrap();

        let repaired = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;

        assert_eq!(repaired["created"], false);
        assert_eq!(
            aws.thing_group_members("txing-rig-type-cloud"),
            BTreeSet::from([thing_name.clone()])
        );
        assert!(aws.thing_group_members("txing-rig-type-raspi").is_empty());
    }

    #[tokio::test]
    async fn enlist_time_device_validates_rig_compatibility_and_initializes_shadows() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let raspi = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "raspi",
            "server",
        )
        .await;

        let error = service
            .handle(&json!({
                "action": "enlistDevice",
                "rigId": result_str(&raspi, "thingName"),
                "deviceType": "time",
                "deviceName": "clock",
            }))
            .await
            .unwrap_err();
        assert!(error.to_string().contains("not compatible"));

        let cloud = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let result = enlist_device(
            &mut service,
            &result_str(&cloud, "thingName"),
            "time",
            "clock",
        )
        .await;

        assert_eq!(result["thingTypeName"], "time");
        assert_eq!(result["attributes"]["kind"], "deviceType");
        assert_eq!(result["attributes"]["rigType"], "cloud");
        assert_eq!(result["attributes"]["deviceType"], "time");
        assert_eq!(result["attributes"]["webAdapter"], "web/time-adapter.tsx");
        assert_eq!(result["attributes"]["capabilities"], "sparkplug,mcp,time");
        assert_eq!(result["attributes"]["redconCommandLevels"], "4,1");
        assert_eq!(
            result["initializedShadows"],
            json!(["sparkplug", "mcp", "time"])
        );
        let time_shadow = aws.shadow_json(&result_str(&result, "thingName"), "time");
        assert_eq!(time_shadow["state"]["reported"]["mode"], "sleep");
    }

    #[tokio::test]
    async fn enlist_unit_creates_all_shadows_without_auxiliary_resources() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let raspi = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "raspi",
            "server",
        )
        .await;

        let result = enlist_device(
            &mut service,
            &result_str(&raspi, "thingName"),
            "unit",
            "bot",
        )
        .await;

        assert_eq!(result["thingTypeName"], "unit");
        assert_eq!(result["attributes"]["redconCommandLevels"], "4,3,2,1");
        assert_eq!(
            result["initializedShadows"],
            json!(["sparkplug", "mcu", "board", "mcp", "video"])
        );
        assert_eq!(result["auxiliaryResources"], json!({}));
    }

    #[tokio::test]
    async fn repeated_enlist_repairs_attributes_without_replacing_shadows() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let cloud = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let first = enlist_device(
            &mut service,
            &result_str(&cloud, "thingName"),
            "time",
            "clock",
        )
        .await;
        let thing_name = result_str(&first, "thingName");
        aws.remove_attribute(&thing_name, "webAdapter");
        aws.put_shadow(
            &thing_name,
            "mcp",
            br#"{"state":{"reported":{"custom":true}}}"#,
        );
        let update_count = aws.shadow_update_count();

        let second = enlist_device(
            &mut service,
            &result_str(&cloud, "thingName"),
            "time",
            "clock",
        )
        .await;

        assert_eq!(second["created"], false);
        assert_eq!(second["initializedShadows"], json!([]));
        assert_eq!(second["attributes"]["webAdapter"], "web/time-adapter.tsx");
        assert_eq!(second["attributes"]["redconCommandLevels"], "4,1");
        assert_eq!(aws.shadow_update_count(), update_count);
        assert_eq!(
            aws.shadow_bytes(&thing_name, "mcp"),
            br#"{"state":{"reported":{"custom":true}}}"#.to_vec()
        );
    }

    #[tokio::test]
    async fn assign_device_validates_compatibility_and_does_not_reset_shadows() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let cloud_a = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let cloud_b = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "backup",
        )
        .await;
        let device = enlist_device(
            &mut service,
            &result_str(&cloud_a, "thingName"),
            "time",
            "clock",
        )
        .await;
        let update_count = aws.shadow_update_count();

        let result = service
            .handle(&json!({
                "action": "assignDevice",
                "deviceId": result_str(&device, "thingName"),
                "rigId": result_str(&cloud_b, "thingName"),
            }))
            .await
            .unwrap();

        assert_eq!(result["created"], false);
        assert_eq!(result["initializedShadows"], json!([]));
        assert_eq!(result["attributes"]["rigId"], cloud_b["thingName"]);
        assert_eq!(
            aws.thing_attributes(&result_str(&device, "thingName"))["rigId"],
            result_str(&cloud_b, "thingName")
        );
        assert_eq!(aws.shadow_update_count(), update_count);
    }

    #[tokio::test]
    async fn discharge_thing_deletes_shadows_principals_and_thing() {
        let aws = FakeAws::seeded();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let raspi = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "raspi",
            "server",
        )
        .await;
        let device = enlist_device(
            &mut service,
            &result_str(&raspi, "thingName"),
            "unit",
            "bot",
        )
        .await;
        let thing_name = result_str(&device, "thingName");
        aws.add_principals(
            &thing_name,
            vec![
                "arn:aws:iot:eu-central-1:123:cert/one",
                "arn:aws:iot:eu-central-1:123:cert/two",
            ],
        );
        assert_eq!(device["auxiliaryResources"], json!({}));

        let result = service
            .handle(&json!({"action": "dischargeThing", "thingId": thing_name}))
            .await
            .unwrap();

        assert_eq!(result["deleted"], true);
        assert_eq!(result["thingName"], thing_name);
        assert_eq!(
            result["deletedShadows"],
            json!(["sparkplug", "mcu", "board", "mcp", "video"])
        );
        assert_eq!(
            result["detachedPrincipals"],
            json!([
                "arn:aws:iot:eu-central-1:123:cert/one",
                "arn:aws:iot:eu-central-1:123:cert/two",
            ])
        );
        assert_eq!(result["auxiliaryResources"], json!({}));
        assert!(!aws.thing_names().contains(&thing_name));
    }

    #[tokio::test]
    async fn discharge_all_deletes_devices_then_rigs_then_towns_with_paginated_search() {
        let aws = FakeAws::seeded();
        aws.set_search_page_size(1);
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let cloud = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let device = enlist_device(
            &mut service,
            &result_str(&cloud, "thingName"),
            "time",
            "clock",
        )
        .await;

        let result = service
            .handle(&json!({"action": "dischargeAll"}))
            .await
            .unwrap();

        assert_eq!(result["deletedThingCount"], 3);
        assert_eq!(
            result["deletedThings"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| result_str(row, "thingName"))
                .collect::<Vec<_>>(),
            vec![
                result_str(&device, "thingName"),
                result_str(&cloud, "thingName"),
                result_str(&town, "thingName"),
            ]
        );
        assert!(aws.thing_names().is_empty());
    }

    #[tokio::test]
    async fn malformed_events_and_unsupported_actions_return_error_envelope() {
        let aws = FakeAws::seeded();
        let responder = FakeResponder::default();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());

        let result = handle_lambda_event_with_service(
            json!({"action": "unsupported"}),
            &mut service,
            &responder,
        )
        .await;

        assert_eq!(result["ok"], false);
        assert_eq!(result["errorType"], "EnlistError");
        assert_eq!(
            result["message"],
            "unsupported enlist action: 'unsupported'"
        );
        assert!(result["processedAt"].as_str().unwrap().ends_with('Z'));

        let missing = handle_lambda_event_with_service(json!({}), &mut service, &responder).await;
        assert_eq!(missing["ok"], false);
        assert_eq!(missing["errorType"], "EnlistError");
        assert!(
            missing["message"]
                .as_str()
                .unwrap()
                .contains("missing required field")
        );
    }

    #[tokio::test]
    async fn cfn_create_update_skip_delete_discharges_and_failure_sends_failed() {
        let aws = FakeAws::seeded();
        aws.set_parameter_page_size(2);
        let responder = FakeResponder::default();
        let mut service = EnlistService::new(&aws, SequenceShortIds::new());
        let town = enlist_town(&mut service).await;
        let cloud = enlist_rig(
            &mut service,
            &result_str(&town, "thingName"),
            "cloud",
            "aws",
        )
        .await;
        let _device = enlist_device(
            &mut service,
            &result_str(&cloud, "thingName"),
            "time",
            "clock",
        )
        .await;

        let create = handle_lambda_event_with_service(
            cfn_event("Create", "TxingDischargeThings"),
            &mut service,
            &responder,
        )
        .await;
        assert_eq!(create["ok"], true);
        assert_eq!(create["skipped"], true);

        let delete = handle_lambda_event_with_service(
            cfn_event("Delete", "TxingDischargeThings"),
            &mut service,
            &responder,
        )
        .await;
        assert_eq!(delete["ok"], true);
        assert_eq!(delete["deletedThingCount"], 3);
        assert!(aws.thing_names().is_empty());

        let failed = handle_lambda_event_with_service(
            cfn_event("Delete", "Wrong"),
            &mut service,
            &responder,
        )
        .await;
        assert_eq!(failed["ok"], false);
        assert_eq!(failed["errorType"], "EnlistError");
        assert!(
            failed["message"]
                .as_str()
                .unwrap()
                .contains("Unsupported CleanupType")
        );

        let calls = responder.calls.lock().unwrap().clone();
        assert_eq!(calls[0].status, CfnStatus::Success);
        assert_eq!(calls[0].data, json!({"skipped": true}));
        assert_eq!(calls[1].status, CfnStatus::Success);
        assert_eq!(calls[1].data["deletedThingCount"], 3);
        assert_eq!(calls[2].status, CfnStatus::Failed);
        assert_eq!(calls[2].physical_resource_id, CFN_DISCHARGE_PHYSICAL_ID);
    }

    fn cfn_event(request_type: &str, cleanup_type: &str) -> Value {
        json!({
            "RequestType": request_type,
            "ResponseURL": "https://cloudformation-response.example",
            "StackId": "stack",
            "RequestId": "request",
            "LogicalResourceId": ACTIVE_CFN_DISCHARGE_LOGICAL_ID,
            "ResourceProperties": {
                "CleanupType": cleanup_type,
                "PhysicalResourceId": CFN_DISCHARGE_PHYSICAL_ID,
            },
        })
    }
}
