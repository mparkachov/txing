#![no_std]
#![no_main]

use panic_halt as _;
use cortex_m_rt::entry;
use nrf52840_hal as hal;
use hal::gpio::Level;
use embedded_hal::digital::OutputPin;
use embedded_hal::delay::DelayNs;

#[entry]
fn main() -> ! {
    // Get access to the device peripherals
    let p = hal::pac::Peripherals::take().unwrap();

    // Split the GPIO port into individual pins
    let port0 = hal::gpio::p0::Parts::new(p.P0);

    // Configure red=P0.26, gree=P0.30 blue=P.06 as a push-pull output
    let mut led = port0.p0_06.into_push_pull_output(Level::High);

    // Get access to the core peripherals for delay
    let core = hal::pac::CorePeripherals::take().unwrap();
    let mut delay = hal::delay::Delay::new(core.SYST);

    // Blink loop
    loop {
        led.set_low().unwrap();
        delay.delay_ms(200_u32);
        led.set_high().unwrap();
        delay.delay_ms(800_u32);
    }
}
