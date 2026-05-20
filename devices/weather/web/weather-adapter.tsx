import type { DeviceWebAdapter } from '../../../office/src/device-adapter'
import { extractWeatherPowerReportedState } from './weather-model'
import WeatherPanel from './WeatherPanel'

const isWeatherDetailRedcon = (
  redcon: number | null,
  detailRedcon: number | null,
): boolean => detailRedcon !== null && redcon === detailRedcon

const weatherDeviceAdapter: DeviceWebAdapter = {
  type: 'weather',
  displayName: 'Weather',
  buildVideoChannelName: (deviceId) => `${deviceId}-weather`,
  canUseBoardVideo: () => false,
  canUseDriveControl: () => false,
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
  getAutoOpenState: ({
    detailRedcon,
    hasActiveSession,
    nextRedcon,
    routeKind,
  }) => {
    if (
      routeKind !== 'device' ||
      !hasActiveSession ||
      !isWeatherDetailRedcon(nextRedcon, detailRedcon)
    ) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    }
  },
  shouldCloseDetail: ({ detailRedcon, reportedRedcon }) =>
    !isWeatherDetailRedcon(reportedRedcon, detailRedcon),
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
