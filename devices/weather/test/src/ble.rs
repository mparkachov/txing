use std::time::{Duration, Instant};

use async_trait::async_trait;

use crate::error::Result;
use crate::event::EventEmitter;
use crate::protocol::{PowerMeasurement, RedconState, WeatherMeasurement};

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
    pub state: RedconState,
}

#[derive(Debug, Clone)]
pub struct TimedPowerMeasurement {
    pub received_at: Instant,
    pub measurement: PowerMeasurement,
}

#[derive(Debug, Clone)]
pub struct TimedWeatherMeasurement {
    pub received_at: Instant,
    pub measurement: WeatherMeasurement,
}

#[async_trait]
pub trait BleCentral: Send {
    async fn connect(&mut self, config: &BleConnectConfig, events: &mut EventEmitter)
    -> Result<()>;

    async fn is_connected(&self) -> bool;

    async fn read_state(&mut self) -> Result<TimedState>;

    async fn read_power_measurement(&mut self) -> Result<TimedPowerMeasurement>;

    async fn read_weather_measurement(&mut self) -> Result<TimedWeatherMeasurement>;

    async fn write_redcon(&mut self, redcon: u8, events: &mut EventEmitter) -> Result<Instant>;

    async fn next_state(&mut self, timeout: Duration) -> Result<TimedState>;

    async fn next_power_measurement(&mut self, timeout: Duration) -> Result<TimedPowerMeasurement>;

    async fn next_weather_measurement(
        &mut self,
        timeout: Duration,
    ) -> Result<TimedWeatherMeasurement>;

    async fn close(&mut self) -> Result<()>;
}
