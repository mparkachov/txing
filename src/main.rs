#![no_std]
#![no_main]

use defmt_rtt as _;
use embedded_hal::digital::OutputPin;
use nrf_softdevice::ble::{Connection, gatt_server, peripheral};
use nrf_softdevice::{Softdevice, raw};
use nrf52840_hal as hal;
use panic_probe as _;

defmt::timestamp!("{=u64:us}", 0u64);

#[defmt::panic_handler]
fn defmt_panic() -> ! {
    panic_probe::hard_fault()
}

const DEFAULT_BATTERY_PCT: u8 = 50;
const SLEEP_ADV_INTERVAL_UNITS: u32 = 80; // 50 ms (0.625 ms units)
const TXING_ADV_DATA: [u8; 9] = [
    0x02, 0x01, 0x06, // Flags
    0x05, 0xFF, 0xFF, 0xFF, b'T', b'X', // Manufacturer data: company=0xFFFF, marker="TX"
];
const TXING_SCAN_DATA: [u8; 7] = [0x06, 0x09, b't', b'x', b'i', b'n', b'g'];

#[derive(Clone, Copy)]
struct DeviceState {
    battery_pct: u8,
    sleep: bool,
}

impl DeviceState {
    const fn boot_default() -> Self {
        Self {
            battery_pct: DEFAULT_BATTERY_PCT,
            sleep: false,
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
            source: raw::NRF_CLOCK_LF_SRC_RC as u8,
            rc_ctiv: 16,
            rc_temp_ctiv: 2,
            accuracy: raw::NRF_CLOCK_LF_ACCURACY_500_PPM as u8,
        }),
        conn_gap: Some(raw::ble_gap_conn_cfg_t {
            conn_count: 1,
            event_length: 24,
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
    let mut config = peripheral::Config::default();
    config.interval = SLEEP_ADV_INTERVAL_UNITS;
    // Keep advertising payloads in RAM; SoftDevice may reject flash-backed pointers.
    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: &TXING_ADV_DATA,
        scan_data: &TXING_SCAN_DATA,
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
    // Keep advertising payloads in RAM; SoftDevice may reject flash-backed pointers.
    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: &TXING_ADV_DATA,
        scan_data: &TXING_SCAN_DATA,
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
