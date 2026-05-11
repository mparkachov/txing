import type { DeviceWebAdapter } from '../../../web/src/device-adapter'
import {
  extractWeatherPowerReportedState,
  extractWeatherReportedState,
} from './weather-model'
import WeatherPanel from './WeatherPanel'

const weatherDeviceAdapter: DeviceWebAdapter = {
  type: 'weather',
  displayName: 'Weather',
  buildVideoChannelName: (deviceId) => `${deviceId}-weather`,
  canUseBoardVideo: () => false,
  extractTelemetry: (shadow) => {
    const reportedPowerState = extractWeatherPowerReportedState(shadow)
    return {
      reportedBatteryMv: reportedPowerState.batteryMv,
      reportedBoardPower: null,
      reportedBoardOnline: null,
      reportedMcuOnline: null,
      reportedMcuPower: null,
    }
  },
  getAutoOpenState: () => null,
  shouldCloseDetail: () => false,
  renderDetail: (props) =>
    createWeatherElement(
      WeatherPanel as (panelProps: Record<string, unknown>) => WeatherElement,
      { shadow: props.shadow },
    ),
  renderVideo: () =>
    createWeatherElement(
      'section',
      { className: 'weather-device-panel', 'aria-label': 'Weather device video' },
      createWeatherElement(
        'div',
        { className: 'weather-device-metric' },
        createWeatherElement('span', { className: 'weather-device-metric-label' }, 'Video'),
        createWeatherElement('span', { className: 'weather-device-metric-value' }, 'unsupported'),
      ),
    ),
}

type WeatherElement = ReturnType<DeviceWebAdapter['renderDetail']>
type WeatherElementType = string | ((props: Record<string, unknown>) => WeatherElement)

const createWeatherElement = (
  type: WeatherElementType,
  props: Record<string, unknown> | null,
  ...children: unknown[]
): WeatherElement =>
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
  }) as WeatherElement

export default weatherDeviceAdapter
