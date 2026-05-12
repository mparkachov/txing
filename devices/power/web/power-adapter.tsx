import type { DeviceWebAdapter } from '../../../web/src/device-adapter'
import { extractPowerReportedState } from './power-model'
import PowerPanel from './PowerPanel'

const isPowerDetailRedcon = (
  redcon: number | null,
  detailRedcon: number | null,
): boolean => detailRedcon !== null && redcon === detailRedcon

const powerDeviceAdapter: DeviceWebAdapter = {
  type: 'power',
  displayName: 'Power',
  buildVideoChannelName: (deviceId) => `${deviceId}-power`,
  canUseBoardVideo: () => false,
  extractTelemetry: (shadow) => {
    const reportedState = extractPowerReportedState(shadow)
    return {
      reportedBatteryMv: reportedState.batteryMv,
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
      !isPowerDetailRedcon(nextRedcon, detailRedcon)
    ) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    }
  },
  shouldCloseDetail: ({ detailRedcon, reportedRedcon }) =>
    !isPowerDetailRedcon(reportedRedcon, detailRedcon),
  renderDetail: (props) =>
    createPowerElement(
      PowerPanel as (panelProps: Record<string, unknown>) => PowerElement,
      { shadow: props.shadow },
    ),
  renderVideo: () =>
    createPowerElement(
      'section',
      { className: 'power-device-panel', 'aria-label': 'Power device video' },
      createPowerElement(
        'div',
        { className: 'power-device-metric' },
        createPowerElement('span', { className: 'power-device-metric-label' }, 'Video'),
        createPowerElement('span', { className: 'power-device-metric-value' }, 'unsupported'),
      ),
    ),
}

type PowerElement = ReturnType<DeviceWebAdapter['renderDetail']>
type PowerElementType = string | ((props: Record<string, unknown>) => PowerElement)

const createPowerElement = (
  type: PowerElementType,
  props: Record<string, unknown> | null,
  ...children: unknown[]
): PowerElement =>
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
  }) as PowerElement

export default powerDeviceAdapter
