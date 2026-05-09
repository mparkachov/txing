use std::collections::HashMap;
use std::time::Duration;

use crate::ble::{BleCentral, BleConnectConfig};
use crate::error::{Result, RigError};
use crate::event::EventEmitter;
use crate::protocol::{REDCON_ACTIVE, REDCON_IDLE};
use crate::pubsub::{
    COMMAND_ACCEPTED, COMMAND_FAILED, COMMAND_SUCCEEDED, CONTROL_IMMEDIATE, ConnectivityCommand,
    ConnectivityCommandResult, ConnectivityState, InMemoryPubSub, PRESENCE_ONLINE,
    SLEEP_MODEL_BLE_CONNECTED_IDLE, TRANSPORT_BLE_GATT, build_command_result_topic,
    build_state_topic, now_ms,
};

pub struct BleConnectivityComponent<B: BleCentral> {
    pub adapter_id: String,
    pub thing_name: String,
    pub ble_name: String,
    pub bus: InMemoryPubSub,
    pub central: B,
    seq: u64,
}

impl<B: BleCentral> BleConnectivityComponent<B> {
    pub fn new(
        adapter_id: impl Into<String>,
        thing_name: impl Into<String>,
        ble_name: impl Into<String>,
        bus: InMemoryPubSub,
        central: B,
    ) -> Self {
        Self {
            adapter_id: adapter_id.into(),
            thing_name: thing_name.into(),
            ble_name: ble_name.into(),
            bus,
            central,
            seq: 0,
        }
    }

    pub async fn handle_command_payload(&mut self, topic: &str, payload: &[u8]) -> Result<()> {
        let command = ConnectivityCommand::from_slice(payload)?;
        if topic != crate::pubsub::build_command_topic(&command.thing_name) {
            return Err(RigError::new(
                "pubsub",
                "command topic thing differs from payload thing",
            ));
        }
        if command.thing_name != self.thing_name {
            return Ok(());
        }
        self.publish_command_result(&command, COMMAND_ACCEPTED, None)
            .await?;

        let mut events = EventEmitter::quiet();
        if !self.central.is_connected().await {
            self.central
                .connect(
                    &BleConnectConfig {
                        name: self.ble_name.clone(),
                        require_service: true,
                        scan_timeout: Duration::from_secs(60),
                        connect_timeout: Duration::from_secs(30),
                        connect_attempts: 3,
                        retry_delay: Duration::from_secs(2),
                    },
                    &mut events,
                )
                .await?;
        }
        let target_redcon = if command.target.power {
            REDCON_ACTIVE
        } else {
            REDCON_IDLE
        };
        let command_at = self
            .central
            .write_redcon(target_redcon, &mut events)
            .await?;
        let state = loop {
            let state = self.central.next_state(Duration::from_secs(10)).await?;
            if state.received_at >= command_at && state.state.redcon == target_redcon {
                break state.state;
            }
        };
        self.seq += 1;
        self.bus
            .publish(
                build_state_topic(&self.thing_name),
                ConnectivityState {
                    schema_version: crate::pubsub::SCHEMA_VERSION.to_string(),
                    adapter_id: self.adapter_id.clone(),
                    thing_name: self.thing_name.clone(),
                    transport: TRANSPORT_BLE_GATT.to_string(),
                    native_identity: HashMap::new(),
                    presence: PRESENCE_ONLINE.to_string(),
                    control_availability: CONTROL_IMMEDIATE.to_string(),
                    power: Some(state.redcon == REDCON_ACTIVE),
                    sleep_model: SLEEP_MODEL_BLE_CONNECTED_IDLE.to_string(),
                    battery_mv: state.battery_mv,
                    observed_at_ms: now_ms(),
                    seq: self.seq,
                }
                .to_json()?,
            )
            .await?;
        self.publish_command_result(&command, COMMAND_SUCCEEDED, None)
            .await?;
        Ok(())
    }

    pub async fn publish_failed_result(
        &self,
        command: &ConnectivityCommand,
        message: impl Into<String>,
    ) -> Result<()> {
        self.publish_command_result(command, COMMAND_FAILED, Some(message.into()))
            .await
    }

    async fn publish_command_result(
        &self,
        command: &ConnectivityCommand,
        status: &str,
        message: Option<String>,
    ) -> Result<()> {
        self.bus
            .publish(
                build_command_result_topic(&command.thing_name),
                ConnectivityCommandResult {
                    schema_version: crate::pubsub::SCHEMA_VERSION.to_string(),
                    adapter_id: self.adapter_id.clone(),
                    command_id: command.command_id.clone(),
                    thing_name: command.thing_name.clone(),
                    status: status.to_string(),
                    message,
                    observed_at_ms: now_ms(),
                    seq: 0,
                }
                .to_json()?,
            )
            .await
    }
}
