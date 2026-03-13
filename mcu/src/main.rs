#![no_std]
#![no_main]

use core::cell::Cell;
use core::sync::atomic::{AtomicBool, Ordering};

use defmt_rtt as _;
use embassy_futures::select::{Either, select};
use embassy_sync::blocking_mutex::raw::CriticalSectionRawMutex;
use embassy_sync::signal::Signal;
use embedded_hal::digital::OutputPin;
use nrf_softdevice::ble::{Connection, gatt_server, peripheral};
use nrf_softdevice::{RawError, Softdevice, raw};
use nrf52840_hal as hal;
use nrf52840_hal::pac::interrupt;
use panic_probe as _;

defmt::timestamp!("{=u64:us}", 0u64);

#[defmt::panic_handler]
fn defmt_panic() -> ! {
    panic_probe::hard_fault()
}

const BATTERY_SAADC_FULL_SCALE_MV: u32 = 3600;
const BATTERY_DIVIDER_UPPER_OHMS: u32 = 1_000_000;
const BATTERY_DIVIDER_LOWER_OHMS: u32 = 510_000;
const BATTERY_CALIBRATION_LOW_REPORTED_MV: i64 = 3700;
const BATTERY_CALIBRATION_LOW_MEASURED_MV: i64 = 3790;
const BATTERY_CALIBRATION_HIGH_REPORTED_MV: i64 = 4085;
const BATTERY_CALIBRATION_HIGH_MEASURED_MV: i64 = 4170;
const BATTERY_ADC_MAX_READING: u32 = (1 << 14) - 1;
const LOW_FREQ_CLOCK_HZ: u32 = 32_768;
const RENDEZVOUS_SLEEP_TICKS: u32 = 5 * LOW_FREQ_CLOCK_HZ;
const BATTERY_REFRESH_TICKS: u32 = 5 * LOW_FREQ_CLOCK_HZ;
const RENDEZVOUS_COMMAND_WINDOW_TICKS: u32 = 15 * LOW_FREQ_CLOCK_HZ;
const RENDEZVOUS_ADV_WINDOW_10MS: u16 = 200;
const AWAKE_ADV_REFRESH_WINDOW_10MS: u16 = 500;
const RENDEZVOUS_ADV_INTERVAL_UNITS: u32 = 160; // 100 ms (0.625 ms units)
const RTC2_APP_PRIORITY: u8 = 0xE0;
const RTC_COUNTER_MASK: u32 = 0x00FF_FFFF;
const POWER_MODE_AWAKE_COMMAND_VALUE: u8 = 0x00;
const POWER_MODE_SLEEP_COMMAND_VALUE: u8 = 0x01;
const TXING_MFG_ID_LE: [u8; 2] = [0xFF, 0xFF];
const TXING_MFG_MAGIC: [u8; 2] = [b'T', b'X'];
const TXING_SERVICE_UUID_ADV_LE: [u8; 16] = [
    0x00, 0xA0, 0xB4, 0xF6, 0x32, 0x7B, 0x2D, 0x4D, 0x9F, 0x4B, 0x4F, 0xF0, 0xA2, 0xB8, 0xF1, 0x00,
];
const TXING_SCAN_DATA: [u8; 7] = [0x06, 0x09, b't', b'x', b'i', b'n', b'g'];

static RTC_SIGNAL: Signal<CriticalSectionRawMutex, ()> = Signal::new();
static RTC_ARMED: AtomicBool = AtomicBool::new(false);
static POWER_COMMAND_SIGNAL: Signal<CriticalSectionRawMutex, u8> = Signal::new();

struct DeviceState {
    battery_mv: Cell<u16>,
    sleep: Cell<bool>,
}

impl DeviceState {
    const fn boot_default() -> Self {
        Self {
            battery_mv: Cell::new(0),
            sleep: Cell::new(true),
        }
    }

    fn report_bytes(&self) -> [u8; 3] {
        let mut report = [0u8; 3];
        report[0] = if self.sleep.get() { 0x01 } else { 0x00 };
        report[1..3].copy_from_slice(&self.battery_mv.get().to_le_bytes());
        report
    }

    fn set_battery_mv(&self, battery_mv: u16) {
        self.battery_mv.set(battery_mv);
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

struct WakeOutput;

impl WakeOutput {
    fn new() -> Self {
        Self
    }

    fn trigger(&mut self) {
        // The board-specific wake GPIO mapping is not described in this repo yet.
        // Keep the wake hook isolated so a real output can be wired in here directly.
        defmt::info!("wake_action triggered");
    }
}

#[nrf_softdevice::gatt_service(uuid = "f6b4a000-7b32-4d2d-9f4b-4ff0a2b8f100")]
struct TxingControlService {
    #[characteristic(uuid = "f6b4a001-7b32-4d2d-9f4b-4ff0a2b8f100", write)]
    sleep_command: u8,

    #[characteristic(uuid = "f6b4a002-7b32-4d2d-9f4b-4ff0a2b8f100", read, notify)]
    state_report: [u8; 3],
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
    let mut wake_output = WakeOutput::new();

    let sd = Softdevice::enable(&softdevice_config());
    enable_dcdc();
    init_rtc2(rtc2);
    let server = Server::new(sd).unwrap();
    spawner.spawn(softdevice_task(sd)).unwrap();

    let state = DeviceState::boot_default();
    refresh_battery_state(&state, &mut battery_monitor);
    set_led_for_sleep_state(&mut led, state.sleep());
    publish_state_report(&server, None, &state);
    defmt::info!(
        "boot sleep={} battery_mv={}",
        state.sleep(),
        state.battery_mv.get()
    );

    loop {
        if state.sleep() {
            sleep_rendezvous_cycle(
                sd,
                &server,
                &state,
                &mut led,
                &mut battery_monitor,
                &mut wake_output,
            )
            .await;
            if state.sleep() {
                log_state_transition("sleep");
                set_led_for_sleep_state(&mut led, true);
                wait_for_timer_ticks(RENDEZVOUS_SLEEP_TICKS).await;
            }
        } else {
            awake_cycle(
                sd,
                &server,
                &state,
                &mut led,
                &mut battery_monitor,
                &mut wake_output,
            )
            .await;
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

fn log_state_transition(label: &'static str) {
    defmt::info!("state={}", label);
}

fn enable_dcdc() {
    let ret = unsafe {
        raw::sd_power_dcdc_mode_set(raw::NRF_POWER_DCDC_MODES_NRF_POWER_DCDC_ENABLE as u8)
    };
    match RawError::convert(ret) {
        Ok(()) => {}
        Err(err) => panic!("sd_power_dcdc_mode_set err {:?}", err),
    }
}

fn refresh_battery_state(state: &DeviceState, battery_monitor: &mut BatteryMonitor) {
    let battery_mv = battery_mv_from_raw(battery_monitor.sample_raw());
    state.set_battery_mv(battery_mv.min(u16::MAX as u32) as u16);
}

fn publish_state_report(server: &Server, conn: Option<&Connection>, state: &DeviceState) {
    let report = state.report_bytes();
    let _ = server.txing.state_report_set(&report);
    if let Some(conn) = conn {
        let _ = server.txing.state_report_notify(conn, &report);
    }
}

fn init_rtc2(rtc2: hal::pac::RTC2) {
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

fn arm_timer_ticks(ticks: u32) {
    critical_section::with(|_| {
        RTC_SIGNAL.reset();

        let rtc = unsafe { &*hal::pac::RTC2::ptr() };
        let counter = rtc.counter.read().bits() & RTC_COUNTER_MASK;
        let compare = counter.wrapping_add(ticks) & RTC_COUNTER_MASK;

        unsafe { rtc.events_compare[0].write(|w| w.bits(0)) };
        unsafe { rtc.cc[0].write(|w| w.bits(compare)) };
        RTC_ARMED.store(true, Ordering::Release);
    });
}

async fn wait_for_timer_ticks(ticks: u32) {
    arm_timer_ticks(ticks);
    RTC_SIGNAL.wait().await;
}

fn build_adv_data(report: [u8; 3]) -> [u8; 30] {
    let mut adv = [0u8; 30];
    adv[0..3].copy_from_slice(&[0x02, 0x01, 0x06]);
    adv[3..12].copy_from_slice(&[
        0x08,
        0xFF,
        TXING_MFG_ID_LE[0],
        TXING_MFG_ID_LE[1],
        TXING_MFG_MAGIC[0],
        TXING_MFG_MAGIC[1],
        report[0],
        report[1],
        report[2],
    ]);
    adv[12..30].copy_from_slice(&[
        0x11,
        0x07,
        TXING_SERVICE_UUID_ADV_LE[0],
        TXING_SERVICE_UUID_ADV_LE[1],
        TXING_SERVICE_UUID_ADV_LE[2],
        TXING_SERVICE_UUID_ADV_LE[3],
        TXING_SERVICE_UUID_ADV_LE[4],
        TXING_SERVICE_UUID_ADV_LE[5],
        TXING_SERVICE_UUID_ADV_LE[6],
        TXING_SERVICE_UUID_ADV_LE[7],
        TXING_SERVICE_UUID_ADV_LE[8],
        TXING_SERVICE_UUID_ADV_LE[9],
        TXING_SERVICE_UUID_ADV_LE[10],
        TXING_SERVICE_UUID_ADV_LE[11],
        TXING_SERVICE_UUID_ADV_LE[12],
        TXING_SERVICE_UUID_ADV_LE[13],
        TXING_SERVICE_UUID_ADV_LE[14],
        TXING_SERVICE_UUID_ADV_LE[15],
    ]);
    adv
}

fn battery_mv_from_raw(raw: u32) -> u32 {
    if raw == 0 {
        return 0;
    }

    let sense_mv = raw.saturating_mul(BATTERY_SAADC_FULL_SCALE_MV) / BATTERY_ADC_MAX_READING;
    let battery_mv_one_point = sense_mv
        .saturating_mul(BATTERY_DIVIDER_UPPER_OHMS + BATTERY_DIVIDER_LOWER_OHMS)
        / BATTERY_DIVIDER_LOWER_OHMS;

    apply_battery_calibration(battery_mv_one_point as i64)
}

fn apply_battery_calibration(reported_mv: i64) -> u32 {
    let reported_span = BATTERY_CALIBRATION_HIGH_REPORTED_MV - BATTERY_CALIBRATION_LOW_REPORTED_MV;
    let measured_span = BATTERY_CALIBRATION_HIGH_MEASURED_MV - BATTERY_CALIBRATION_LOW_MEASURED_MV;
    let reported_delta = reported_mv - BATTERY_CALIBRATION_LOW_REPORTED_MV;
    let corrected_mv = BATTERY_CALIBRATION_LOW_MEASURED_MV
        + round_div_i64(reported_delta * measured_span, reported_span);

    corrected_mv.max(0) as u32
}

fn round_div_i64(numerator: i64, denominator: i64) -> i64 {
    if numerator >= 0 {
        (numerator + (denominator / 2)) / denominator
    } else {
        (numerator - (denominator / 2)) / denominator
    }
}

async fn sleep_rendezvous_cycle<P: OutputPin>(
    sd: &'static Softdevice,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
    wake_output: &mut WakeOutput,
) {
    log_state_transition("wake");
    refresh_battery_state(state, battery_monitor);
    publish_state_report(server, None, state);
    set_led_for_sleep_state(led, false);
    let adv_data = build_adv_data(state.report_bytes());

    log_state_transition("advertising");
    let mut config = peripheral::Config::default();
    config.interval = RENDEZVOUS_ADV_INTERVAL_UNITS;
    config.timeout = Some(RENDEZVOUS_ADV_WINDOW_10MS);

    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: &adv_data,
        scan_data: &TXING_SCAN_DATA,
    };

    match peripheral::advertise_connectable(sd, adv, &config).await {
        Ok(conn) => {
            run_connection(conn, server, state, led, battery_monitor, wake_output).await;
        }
        Err(peripheral::AdvertiseError::Timeout) => {
            defmt::debug!("advertising_timeout");
        }
        Err(err) => {
            defmt::warn!("advertising_err={:?}", err);
        }
    }

    publish_state_report(server, None, state);
    if state.sleep() {
        log_state_transition("return_to_sleep");
    }
}

async fn awake_cycle<P: OutputPin>(
    sd: &'static Softdevice,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
    wake_output: &mut WakeOutput,
) {
    refresh_battery_state(state, battery_monitor);
    publish_state_report(server, None, state);
    set_led_for_sleep_state(led, false);
    log_state_transition("awake_advertising");
    let adv_data = build_adv_data(state.report_bytes());

    let mut config = peripheral::Config::default();
    config.interval = RENDEZVOUS_ADV_INTERVAL_UNITS;
    config.timeout = Some(AWAKE_ADV_REFRESH_WINDOW_10MS);

    let adv = peripheral::ConnectableAdvertisement::ScannableUndirected {
        adv_data: &adv_data,
        scan_data: &TXING_SCAN_DATA,
    };

    match peripheral::advertise_connectable(sd, adv, &config).await {
        Ok(conn) => {
            run_connection(conn, server, state, led, battery_monitor, wake_output).await;
        }
        Err(peripheral::AdvertiseError::Timeout) => {}
        Err(err) => {
            defmt::warn!("awake_advertising_err={:?}", err);
        }
    }
}

async fn run_connection<P: OutputPin>(
    conn: Connection,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
    wake_output: &mut WakeOutput,
) {
    log_state_transition("connected");
    refresh_battery_state(state, battery_monitor);
    set_led_for_sleep_state(led, state.sleep());
    publish_state_report(server, Some(&conn), state);

    POWER_COMMAND_SIGNAL.reset();
    let mut gatt_run = core::pin::pin!(gatt_server::run(&conn, server, |event| match event {
        ServerEvent::Txing(TxingControlServiceEvent::SleepCommandWrite(value)) => {
            POWER_COMMAND_SIGNAL.signal(value);
        }
        _ => {}
    }));
    let mut command_window_remaining = if state.sleep() {
        Some(RENDEZVOUS_COMMAND_WINDOW_TICKS)
    } else {
        None
    };

    loop {
        let wait_ticks = match command_window_remaining {
            Some(remaining) => remaining.min(BATTERY_REFRESH_TICKS),
            None => BATTERY_REFRESH_TICKS,
        };

        match select(
            select(gatt_run.as_mut(), POWER_COMMAND_SIGNAL.wait()),
            wait_for_timer_ticks(wait_ticks),
        )
        .await
        {
            Either::First(Either::First(_)) => {
                defmt::info!("connection_closed sleep={}", state.sleep());
                return;
            }
            Either::First(Either::Second(value)) => {
                handle_power_command(
                    value,
                    &conn,
                    server,
                    state,
                    led,
                    battery_monitor,
                    wake_output,
                );
                if state.sleep() {
                    let _ = conn.disconnect();
                } else {
                    command_window_remaining = None;
                }
            }
            Either::Second(()) => {
                if let Some(remaining) = command_window_remaining {
                    let remaining_after_wait = remaining.saturating_sub(wait_ticks);
                    if remaining_after_wait == 0 {
                        defmt::info!("command_window_timeout sleep=true");
                        let _ = conn.disconnect();
                        defmt::info!("sleep_connection_timeout_complete sleep=true");
                        return;
                    }
                    command_window_remaining = Some(remaining_after_wait);
                }

                refresh_battery_state(state, battery_monitor);
                publish_state_report(server, Some(&conn), state);
                if !state.sleep() {
                    command_window_remaining = None;
                }
            }
        }
    }
}

fn handle_power_command<P: OutputPin>(
    value: u8,
    conn: &Connection,
    server: &Server,
    state: &DeviceState,
    led: &mut P,
    battery_monitor: &mut BatteryMonitor,
    wake_output: &mut WakeOutput,
) {
    match value {
        POWER_MODE_AWAKE_COMMAND_VALUE => {
            log_state_transition("command_processing");
            let was_sleeping = state.sleep();
            if was_sleeping {
                wake_output.trigger();
            }
            state.set_sleep(false);
            refresh_battery_state(state, battery_monitor);
            set_led_for_sleep_state(led, false);
            publish_state_report(server, Some(conn), state);
            defmt::info!("power_command next_sleep=false");
        }
        POWER_MODE_SLEEP_COMMAND_VALUE => {
            log_state_transition("command_processing");
            state.set_sleep(true);
            refresh_battery_state(state, battery_monitor);
            set_led_for_sleep_state(led, true);
            publish_state_report(server, Some(conn), state);
            defmt::info!("power_command next_sleep=true");
        }
        _ => {
            defmt::warn!("unexpected_power_command value={}", value);
        }
    }
}

#[interrupt]
unsafe fn RTC2() {
    let rtc = unsafe { &*hal::pac::RTC2::ptr() };

    if rtc.events_compare[0].read().bits() != 0 {
        unsafe { rtc.events_compare[0].write(|w| w.bits(0)) };
        if RTC_ARMED.swap(false, Ordering::AcqRel) {
            RTC_SIGNAL.signal(());
        }
    }
}
