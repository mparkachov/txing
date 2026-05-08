use std::collections::VecDeque;
use std::time::{Duration, Instant};

use async_trait::async_trait;

use crate::ble::{BleCentral, BleConnectConfig, TimedState};
use crate::error::{Result, RigError};
use crate::event::EventEmitter;
use crate::protocol::{
    ConnectionParams, REDCON_ACTIVE, REDCON_IDLE, WeatherState, connection_fields, encode_command,
    encode_state,
};

#[derive(Debug, Clone, Default)]
pub struct SimBleBehavior {
    pub missing_advertisement: bool,
    pub connect_failures: u32,
    pub wake_timeout: bool,
    pub low_battery_updates: bool,
    pub invalid_state_on_wake: bool,
    pub unexpected_disconnect_on_wake: bool,
}

#[derive(Debug)]
pub struct SimBleCentral {
    behavior: SimBleBehavior,
    connected: bool,
    remaining_connect_failures: u32,
    queued: VecDeque<SimEvent>,
    sleep_disconnect_pending: bool,
    last_state: WeatherState,
}

#[derive(Debug)]
enum SimEvent {
    State(WeatherState),
    InvalidState,
    Disconnect,
}

impl Default for SimBleCentral {
    fn default() -> Self {
        Self::new(SimBleBehavior::default())
    }
}

impl SimBleCentral {
    pub fn new(behavior: SimBleBehavior) -> Self {
        Self {
            remaining_connect_failures: behavior.connect_failures,
            behavior,
            connected: false,
            queued: VecDeque::new(),
            sleep_disconnect_pending: false,
            last_state: WeatherState {
                redcon: REDCON_IDLE,
                active: false,
                battery_mv: None,
            },
        }
    }

    fn push_state(&mut self, redcon: u8, battery_mv: u16) {
        let state = crate::protocol::decode_state(&encode_state(redcon, battery_mv))
            .expect("simulated state is valid");
        self.last_state = state.clone();
        self.queued.push_back(SimEvent::State(state));
    }
}

#[async_trait]
impl BleCentral for SimBleCentral {
    async fn connect(
        &mut self,
        config: &BleConnectConfig,
        events: &mut EventEmitter,
    ) -> Result<()> {
        if self.behavior.missing_advertisement {
            return Err(RigError::new(
                "discover",
                format!("no matching advertisement for {:?}", config.name),
            ));
        }
        events.emit(
            "adv",
            &[
                ("name", config.name.clone()),
                ("address", "SIMULATED".to_string()),
                ("rssi", "-48".to_string()),
                ("service", "1".to_string()),
            ],
        );
        if self.remaining_connect_failures > 0 {
            self.remaining_connect_failures -= 1;
            return Err(RigError::new("connect", "simulated connect failure"));
        }
        self.connected = true;
        events.emit(
            "connected",
            &[
                ("name", config.name.clone()),
                ("address", "SIMULATED".to_string()),
                ("os", std::env::consts::OS.to_string()),
                ("backend", "sim".to_string()),
                ("attempt", "1".to_string()),
                ("connectMs", "1".to_string()),
                ("sinceStartMs", "1".to_string()),
            ],
        );
        events.emit(
            "services",
            &[
                ("command", "1".to_string()),
                ("state", "1".to_string()),
                ("servicesMs", "0".to_string()),
            ],
        );
        events.emit(
            "notify",
            &[
                ("characteristic", "state".to_string()),
                ("enabled", "1".to_string()),
            ],
        );
        Ok(())
    }

    async fn is_connected(&self) -> bool {
        self.connected
    }

    async fn read_state(&mut self) -> Result<TimedState> {
        Ok(TimedState {
            received_at: Instant::now(),
            state: self.last_state.clone(),
        })
    }

    async fn write_redcon(
        &mut self,
        redcon: u8,
        conn_params: Option<&ConnectionParams>,
        events: &mut EventEmitter,
    ) -> Result<Instant> {
        if !self.connected {
            return Err(RigError::new("connect", "not connected"));
        }
        let payload = encode_command(redcon, conn_params);
        let mut fields = vec![
            ("redcon", redcon.to_string()),
            ("payload", hex_lower(&payload)),
        ];
        fields.extend(connection_fields(conn_params));
        events.emit("command", &fields);

        if redcon == REDCON_ACTIVE {
            if self.behavior.unexpected_disconnect_on_wake {
                self.queued.push_back(SimEvent::Disconnect);
            } else if self.behavior.invalid_state_on_wake {
                self.queued.push_back(SimEvent::InvalidState);
            } else if !self.behavior.wake_timeout {
                self.push_state(REDCON_ACTIVE, 3795);
                if self.behavior.low_battery_updates {
                    self.push_state(REDCON_ACTIVE, 3794);
                } else {
                    self.push_state(REDCON_ACTIVE, 3794);
                    self.push_state(REDCON_ACTIVE, 3793);
                    self.push_state(REDCON_ACTIVE, 3792);
                }
            }
        } else if redcon == REDCON_IDLE {
            self.push_state(REDCON_IDLE, 3792);
            self.sleep_disconnect_pending = true;
        }
        Ok(Instant::now())
    }

    async fn next_state(&mut self, _timeout: Duration) -> Result<TimedState> {
        match self.queued.pop_front() {
            Some(SimEvent::State(state)) => Ok(TimedState {
                received_at: Instant::now(),
                state,
            }),
            Some(SimEvent::InvalidState) => Err(RigError::new(
                "state",
                "unsupported state protocol version: 255",
            )),
            Some(SimEvent::Disconnect) => {
                self.connected = false;
                Err(RigError::new("disconnect", "unexpected disconnect"))
            }
            None => Err(RigError::new("timeout", "state deadline expired")),
        }
    }

    async fn wait_for_disconnect(&mut self, _timeout: Duration) -> Result<()> {
        if self.sleep_disconnect_pending {
            self.sleep_disconnect_pending = false;
            self.connected = false;
            return Ok(());
        }
        Err(RigError::new(
            "sleep",
            "device did not disconnect after REDCON 4",
        ))
    }

    async fn close(&mut self) -> Result<()> {
        self.connected = false;
        self.queued.clear();
        self.sleep_disconnect_pending = false;
        Ok(())
    }
}

fn hex_lower(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
