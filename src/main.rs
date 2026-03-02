#![no_std]
#![no_main]

use defmt_rtt as _;
use embedded_hal::digital::OutputPin;
use nrf_softdevice::ble::{Connection, gatt_server, peripheral};
use nrf_softdevice::{Softdevice, raw};
use nrf52840_hal as hal;
use panic_probe as _;

const DEFAULT_BATTERY_PCT: u8 = 50;
const SLEEP_POLL_PERIOD_MS: u64 = 4_000;
const SLEEP_LISTEN_WINDOW_10MS: u16 = 50; // 500 ms

const ADV_DATA: &[u8] = &[0x02, 0x01, 0x06, 0x06, 0x09, b't', b'x', b'i', b'n', b'g'];
const SCAN_DATA: &[u8] = &[];

#[derive(Clone, Copy)]
struct DeviceState {
    battery_pct: u8,
    sleep: bool,
}

impl DeviceState {
    const fn boot_default() -> Self {
        Self {
            battery_pct: DEFAULT_BATTERY_PCT,
            sleep: true,
        }
    }

    fn report_bytes(&self) -> [u8; 2] {
        [self.battery_pct, if self.sleep { 0x01 } else { 0x00 }]
    }
}

#[nrf_softdevice::gatt_service(uuid = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100")]
struct TxingControlService {
    #[characteristic(uuid = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100", write)]
    sleep_command: u8,

    #[characteristic(uuid = "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100", read, notify)]
    state_report: [u8; 2],
}

#[nrf_softdevice::gatt_server]
struct Server {
    txing: TxingControlService,
}

#[embassy_executor::task]
async fn softdevice_task(sd: &'static Softdevice) {
    sd.run().await;
}

#[embassy_executor::main]
async fn main(spawner: embassy_executor::Spawner) {
    let p = hal::pac::Peripherals::take().unwrap();
    let port0 = hal::gpio::p0::Parts::new(p.P0);
    let mut led = port0.p0_06.into_push_pull_output(hal::gpio::Level::High);

    let sd = Softdevice::enable(&softdevice_config());
    let server = Server::new(sd).unwrap();
    spawner.spawn(softdevice_task(sd)).unwrap();

    let mut state = DeviceState::boot_default();
    set_led_for_sleep_state(&mut led, state.sleep);
    let _ = server.txing.state_report_set(&state.report_bytes());

    loop {
        if state.sleep {
            sleep_poll_cycle(sd, &server, &mut state, &mut led).await;
        } else {
            awake_cycle(sd, &server, &mut state, &mut led).await;
        }
    }
}

fn softdevice_config() -> nrf_softdevice::Config {
    nrf_softdevice::Config {
        clock: Some(raw::nrf_clock_lf_cfg_t {
            source: raw::NRF_CLOCK_LF_SRC_XTAL as u8,
            rc_ctiv: 0,
            rc_temp_ctiv: 0,
            accuracy: raw::NRF_CLOCK_LF_ACCURACY_20_PPM as u8,
        }),
        conn_gap: Some(raw::ble_gap_conn_cfg_t {
            conn_count: 1,
            event_length: 24,
        }),
        conn_gatt: Some(raw::ble_gatt_conn_cfg_t { att_mtu: 64 }),
        gatts_attr_tab_size: Some(raw::ble_gatts_cfg_attr_tab_size_t { attr_tab_size: 512 }),
        gap_role_count: Some(raw::ble_gap_cfg_role_count_t {
            adv_set_count: 1,
            periph_role_count: 1,
            central_role_count: 0,
            central_sec_count: 0,
            _bitfield_1: raw::ble_gap_cfg_role_count_t::new_bitfield_1(0),
        }),
        ..Default::default()
    }
}

fn set_led_for_sleep_state<P: OutputPin>(led: &mut P, sleep: bool) {
    if sleep {
        let _ = led.set_high();
    } else {
        let _ = led.set_low();
    }
}

async fn sleep_poll_cycle<P: OutputPin>(
    sd: &'static Softdevice,
    server: &Server,
    state: &mut DeviceState,
    led: &mut P,
) {
    set_led_for_sleep_state(led, true);
    embassy_time::Timer::after_millis(SLEEP_POLL_PERIOD_MS).await;

    let mut config = peripheral::Config::default();
    config.timeout = Some(SLEEP_LISTEN_WINDOW_10MS);

    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: ADV_DATA,
        scan_data: SCAN_DATA,
    };

    if let Ok(conn) = peripheral::advertise_connectable(sd, adv, &config).await {
        run_connection(conn, server, state, led).await;
    }
}

async fn awake_cycle<P: OutputPin>(
    sd: &'static Softdevice,
    server: &Server,
    state: &mut DeviceState,
    led: &mut P,
) {
    set_led_for_sleep_state(led, false);

    let config = peripheral::Config::default();
    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: ADV_DATA,
        scan_data: SCAN_DATA,
    };

    if let Ok(conn) = peripheral::advertise_connectable(sd, adv, &config).await {
        run_connection(conn, server, state, led).await;
    }
}

async fn run_connection<P: OutputPin>(
    conn: Connection,
    server: &Server,
    state: &mut DeviceState,
    led: &mut P,
) {
    let report = state.report_bytes();
    let _ = server.txing.state_report_set(&report);
    let _ = server.txing.state_report_notify(&conn, &report);

    let _ = gatt_server::run(&conn, server, |event| match event {
        ServerEvent::Txing(TxingControlServiceEvent::SleepCommandWrite(value)) => {
            let next_sleep = match value {
                0x00 => Some(false),
                0x01 => Some(true),
                _ => None,
            };

            if let Some(next_sleep) = next_sleep {
                state.sleep = next_sleep;
                set_led_for_sleep_state(led, state.sleep);

                let report = state.report_bytes();
                let _ = server.txing.state_report_set(&report);
                let _ = server.txing.state_report_notify(&conn, &report);
            }
        }
        _ => {}
    })
    .await;
}
