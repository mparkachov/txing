#![no_std]
#![no_main]

use core::cell::Cell;
use core::sync::atomic::{AtomicBool, Ordering};

use defmt_rtt as _;
use embassy_futures::select::select;
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::signal::Signal;
use embedded_hal::digital::OutputPin;
use nrf_softdevice::ble::{Connection, gatt_server, peripheral};
use nrf_softdevice::{Softdevice, raw};
use nrf52840_hal as hal;
use nrf52840_hal::pac::interrupt;
use panic_probe as _;

defmt::timestamp!("{=u64:us}", 0u64);

#[defmt::panic_handler]
fn defmt_panic() -> ! {
    panic_probe::hard_fault()
}

const BATTERY_PCT_FALLBACK: u8 = 0;
const BATTERY_SAADC_FULL_SCALE_MV: u32 = 3600;
const BATTERY_EMPTY_MV: u32 = 3300;
const BATTERY_FULL_MV: u32 = 4200;
const BATTERY_DIVIDER_UPPER_OHMS: u32 = 1_000_000;
const BATTERY_DIVIDER_LOWER_OHMS: u32 = 510_000;
const BATTERY_ADC_MAX_READING: u32 = (1 << 14) - 1;
const BATTERY_REFRESH_INTERVAL_TICKS: u32 = 60 * 32_768;
const SLEEP_ADV_INTERVAL_UNITS: u32 = 80; // 50 ms (0.625 ms units)
const RTC2_APP_PRIORITY: u8 = 0xE0;
const RTC_COUNTER_MASK: u32 = 0x00FF_FFFF;
const TXING_ADV_DATA: [u8; 9] = [
    0x02, 0x01, 0x06, // Flags
    0x05, 0xFF, 0xFF, 0xFF, b'T', b'X', // Manufacturer data: company=0xFFFF, marker="TX"
];
const TXING_SCAN_DATA: [u8; 7] = [0x06, 0x09, b't', b'x', b'i', b'n', b'g'];

static BATTERY_REFRESH_SIGNAL: Signal<CriticalSectionRawMutex, ()> = Signal::new();
static BATTERY_REFRESH_ARMED: AtomicBool = AtomicBool::new(false);

struct DeviceState {
    battery_pct: Cell<u8>,
    battery_volt: Cell<f32>,
    sleep: Cell<bool>,
}

impl DeviceState {
    const fn boot_default() -> Self {
        Self {
            battery_pct: Cell::new(BATTERY_PCT_FALLBACK),
            battery_volt: Cell::new(0.0),
            sleep: Cell::new(false),
        }
    }

    fn report_bytes(&self) -> [u8; 6] {
        let mut report = [0u8; 6];
        report[0] = self.battery_pct.get();
        report[1] = if self.sleep.get() { 0x01 } else { 0x00 };
        report[2..6].copy_from_slice(&self.battery_volt.get().to_le_bytes());
        report
    }

    fn set_battery_pct(&self, battery_pct: u8) {
        self.battery_pct.set(battery_pct);
    }

    fn set_battery_volt(&self, battery_volt: f32) {
        self.battery_volt.set(battery_volt);
    }

    fn sleep(&self) -> bool {
        self.sleep.get()
    }

    fn set_sleep(&self, sleep: bool) {
        self.sleep.set(sleep);
    }
}

struct BatteryMonitor {
    saadc: hal::Saadc,
    sense_enable: hal::gpio::p0::P0_14<hal::gpio::Output<hal::gpio::PushPull>>,
    sense_pin: hal::gpio::p0::P0_31<hal::gpio::Disconnected>,
}

impl BatteryMonitor {
    fn new(
        saadc: hal::pac::SAADC,
        sense_enable: hal::gpio::p0::P0_14<hal::gpio::Disconnected>,
        sense_pin: hal::gpio::p0::P0_31<hal::gpio::Disconnected>,
    ) -> Self {
        let mut saadc_config = hal::saadc::SaadcConfig::default();
        saadc_config.reference = hal::saadc::Reference::INTERNAL;
        saadc_config.gain = hal::saadc::Gain::GAIN1_6;

        Self {
            saadc: hal::Saadc::new(saadc, saadc_config),
            // On XIAO nRF52840, P0.14 is active-low battery-sense enable. Keep it low
            // so the divider stays connected and P0.31 never sees raw battery voltage.
            sense_enable: sense_enable.into_push_pull_output(hal::gpio::Level::Low),
            sense_pin,
        }
    }

    fn sample_raw(&mut self) -> u32 {
        let _ = self.sense_enable.set_low();

        // Take a few samples and average them to smooth ADC noise.
        let mut total: u32 = 0;
        let mut samples: u32 = 0;
        for _ in 0..4 {
            let raw = self
                .saadc
                .read_channel(&mut self.sense_pin)
                .unwrap_or(0)
                .max(0) as u32;
            total = total.saturating_add(raw);
            samples += 1;
        }

        if samples == 0 { 0 } else { total / samples }
    }
}

#[nrf_softdevice::gatt_service(uuid = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100")]
struct TxingControlService {
    #[characteristic(uuid = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100", write)]
    sleep_command: u8,

    #[characteristic(uuid = "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100", read, notify)]
    state_report: [u8; 6],
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
    let rtc2 = p.RTC2;
    let port0 = hal::gpio::p0::Parts::new(p.P0);
    let mut led = port0.p0_06.into_push_pull_output(hal::gpio::Level::High);
    let mut battery_monitor = BatteryMonitor::new(p.SAADC, port0.p0_14, port0.p0_31);

    let sd = Softdevice::enable(&softdevice_config());
    init_battery_refresh_timer(rtc2);
    let server = Server::new(sd).unwrap();
    spawner.spawn(softdevice_task(sd)).unwrap();

    let state = DeviceState::boot_default();
    refresh_battery_state(&state, &mut battery_monitor);
    set_led_for_sleep_state(&mut led, state.sleep());
    publish_state_report(&server, None, &state);

    loop {
        refresh_battery_state(&state, &mut battery_monitor);
        if state.sleep() {
            sleep_poll_cycle(sd, &server, &state, &mut led, &mut battery_monitor).await;
        } else {
            awake_cycle(sd, &server, &state, &mut led, &mut battery_monitor).await;
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

fn refresh_battery_state(state: &DeviceState, battery_monitor: &mut BatteryMonitor) {
    let battery_mv = battery_mv_from_raw(battery_monitor.sample_raw());
    state.set_battery_pct(battery_pct_from_mv(battery_mv));
    state.set_battery_volt(battery_volt_from_mv(battery_mv));
}

fn publish_state_report(server: &Server, conn: Option<&Connection>, state: &DeviceState) {
    let report = state.report_bytes();
    let _ = server.txing.state_report_set(&report);
    if let Some(conn) = conn {
        let _ = server.txing.state_report_notify(conn, &report);
    }
}

fn init_battery_refresh_timer(rtc2: hal::pac::RTC2) {
    rtc2.tasks_stop.write(|w| w.tasks_stop().set_bit());
    rtc2.tasks_clear.write(|w| w.tasks_clear().set_bit());
    unsafe { rtc2.prescaler.write(|w| w.bits(0)) };
    unsafe { rtc2.events_compare[0].write(|w| w.bits(0)) };
    rtc2.intenset.write(|w| w.compare0().set());

    let mut nvic = unsafe { cortex_m::Peripherals::steal().NVIC };
    unsafe {
        nvic.set_priority(hal::pac::Interrupt::RTC2, RTC2_APP_PRIORITY);
        cortex_m::peripheral::NVIC::unpend(hal::pac::Interrupt::RTC2);
        cortex_m::peripheral::NVIC::unmask(hal::pac::Interrupt::RTC2);
    }

    rtc2.tasks_start.write(|w| w.tasks_start().set_bit());
}

fn arm_battery_refresh_timer() {
    critical_section::with(|_| {
        BATTERY_REFRESH_SIGNAL.reset();

        let rtc = unsafe { &*hal::pac::RTC2::ptr() };
        let counter = rtc.counter.read().bits() & RTC_COUNTER_MASK;
        let compare = counter.wrapping_add(BATTERY_REFRESH_INTERVAL_TICKS) & RTC_COUNTER_MASK;

        unsafe { rtc.events_compare[0].write(|w| w.bits(0)) };
        unsafe { rtc.cc[0].write(|w| w.bits(compare)) };
        BATTERY_REFRESH_ARMED.store(true, Ordering::Release);
    });
}

async fn wait_for_battery_refresh_tick() {
    arm_battery_refresh_timer();
    BATTERY_REFRESH_SIGNAL.wait().await;
}

fn battery_mv_from_raw(raw: u32) -> u32 {
    if raw == 0 {
        return 0;
    }

    let sense_mv = raw.saturating_mul(BATTERY_SAADC_FULL_SCALE_MV) / BATTERY_ADC_MAX_READING;
    let battery_mv = sense_mv
        .saturating_mul(BATTERY_DIVIDER_UPPER_OHMS + BATTERY_DIVIDER_LOWER_OHMS)
        / BATTERY_DIVIDER_LOWER_OHMS;

    battery_mv
}

fn battery_pct_from_mv(battery_mv: u32) -> u8 {
    if battery_mv <= BATTERY_EMPTY_MV {
        return 0;
    }

    if battery_mv >= BATTERY_FULL_MV {
        return 100;
    }

    let span_mv = BATTERY_FULL_MV - BATTERY_EMPTY_MV;
    (((battery_mv - BATTERY_EMPTY_MV) * 100) / span_mv) as u8
}

fn battery_volt_from_mv(battery_mv: u32) -> f32 {
    battery_mv as f32 / 1000.0
}

async fn sleep_poll_cycle<P: OutputPin>(
    sd: &'static Softdevice,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
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
        run_connection(conn, server, state, led, battery_monitor).await;
    }
}

async fn awake_cycle<P: OutputPin>(
    sd: &'static Softdevice,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
) {
    set_led_for_sleep_state(led, false);

    let config = peripheral::Config::default();
    // Keep advertising payloads in RAM; SoftDevice may reject flash-backed pointers.
    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: &TXING_ADV_DATA,
        scan_data: &TXING_SCAN_DATA,
    };

    if let Ok(conn) = peripheral::advertise_connectable(sd, adv, &config).await {
        run_connection(conn, server, state, led, battery_monitor).await;
    }
}

async fn run_connection<P: OutputPin>(
    conn: Connection,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
) {
    publish_state_report(server, Some(&conn), state);

    let _ = select(
        gatt_server::run(&conn, server, |event| match event {
            ServerEvent::Txing(TxingControlServiceEvent::SleepCommandWrite(value)) => {
                let next_sleep = match value {
                    0x00 => Some(false),
                    0x01 => Some(true),
                    _ => None,
                };

                if let Some(next_sleep) = next_sleep {
                    state.set_sleep(next_sleep);
                    set_led_for_sleep_state(led, state.sleep());
                    publish_state_report(server, Some(&conn), state);
                }
            }
            _ => {}
        }),
        refresh_battery_while_connected(&conn, server, state, battery_monitor),
    )
    .await;
}

async fn refresh_battery_while_connected(
    conn: &Connection,
    server: &Server,
    state: &DeviceState,
    battery_monitor: &mut BatteryMonitor,
) {
    loop {
        wait_for_battery_refresh_tick().await;
        refresh_battery_state(state, battery_monitor);
        publish_state_report(server, Some(conn), state);
    }
}

#[interrupt]
unsafe fn RTC2() {
    let rtc = unsafe { &*hal::pac::RTC2::ptr() };

    if rtc.events_compare[0].read().bits() != 0 {
        unsafe { rtc.events_compare[0].write(|w| w.bits(0)) };
        if BATTERY_REFRESH_ARMED.swap(false, Ordering::AcqRel) {
            BATTERY_REFRESH_SIGNAL.signal(());
        }
    }
}
