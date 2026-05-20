import type {
  DeviceDetailRenderProps,
  DeviceWebAdapter,
} from '../../../office/src/device-adapter'
import {
  extractWeatherPowerReportedState,
  extractWeatherReportedState,
  formatWeatherMetric,
} from './weather-model'

type WeatherPanelProps = Pick<DeviceDetailRenderProps, 'shadow'>
type WeatherPanelElement = ReturnType<DeviceWebAdapter['renderDetail']>

function WeatherPanel({ shadow }: WeatherPanelProps) {
  const reportedState = extractWeatherReportedState(shadow)
  const reportedPowerState = extractWeatherPowerReportedState(shadow)

  return createWeatherElement(
    'section',
    { className: 'weather-device-panel', 'aria-label': 'Weather device status' },
    createWeatherElement(
      'div',
      { className: 'weather-device-grid' },
      createMetric(
        'Temperature',
        formatWeatherMetric(reportedState.measuredTemperature, 'C', 2),
      ),
      createMetric(
        'Pressure',
        formatWeatherMetric(reportedState.measuredPressure, 'kPa', 1),
      ),
      createMetric(
        'Humidity',
        formatWeatherMetric(reportedState.measuredHumidity, '%RH', 2),
      ),
      createMetric(
        'Battery',
        reportedPowerState.batteryMv === null ? '--' : `${reportedPowerState.batteryMv} mV`,
      ),
    ),
  )
}

const createMetric = (label: string, value: string) =>
  createWeatherElement(
    'div',
    { className: 'weather-device-metric' },
    createWeatherElement('span', { className: 'weather-device-metric-label' }, label),
    createWeatherElement('span', { className: 'weather-device-metric-value' }, value),
  )

type WeatherElementType = string | ((props: Record<string, unknown>) => WeatherPanelElement)

const createWeatherElement = (
  type: WeatherElementType,
  props: Record<string, unknown> | null,
  ...children: unknown[]
): WeatherPanelElement =>
  ({
    $$typeof: Symbol.for('react.transitional.element'),
    type,
    key: null,
    props: {
      ...(props ?? {}),
      ...(children.length === 0
        ? {}
        : { children: children.length === 1 ? children[0] : children }),
    },
    _owner: null,
    _store: {},
  }) as WeatherPanelElement

export default WeatherPanel
