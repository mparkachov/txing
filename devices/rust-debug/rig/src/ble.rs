use std::time::{Duration, Instant};

use async_trait::async_trait;

use crate::error::Result;
use crate::event::EventEmitter;
use crate::protocol::{ConnectionParams, WeatherState};

#[derive(Debug, Clone)]
pub struct BleConnectConfig {
    pub name: String,
    pub require_service: bool,
    pub scan_timeout: Duration,
    pub connect_timeout: Duration,
    pub connect_attempts: u32,
    pub retry_delay: Duration,
}

#[derive(Debug, Clone)]
pub struct TimedState {
    pub received_at: Instant,
    pub state: WeatherState,
}

#[async_trait]
pub trait BleCentral: Send {
    async fn connect(&mut self, config: &BleConnectConfig, events: &mut EventEmitter)
    -> Result<()>;

    async fn is_connected(&self) -> bool;

    async fn read_state(&mut self) -> Result<TimedState>;

    async fn write_redcon(
        &mut self,
        redcon: u8,
        conn_params: Option<&ConnectionParams>,
        events: &mut EventEmitter,
    ) -> Result<Instant>;

    async fn next_state(&mut self, timeout: Duration) -> Result<TimedState>;

    async fn wait_for_disconnect(&mut self, timeout: Duration) -> Result<()>;

    async fn close(&mut self) -> Result<()>;
}
