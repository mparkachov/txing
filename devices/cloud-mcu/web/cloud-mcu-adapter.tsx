import type { DeviceWebAdapter } from '../../../web/src/device-adapter'
import CloudMcuPanel from './CloudMcuPanel'
import { extractCloudMcuReportedState } from './cloud-mcu-model'

const cloudMcuDeviceAdapter: DeviceWebAdapter = {
  type: 'cloud-mcu',
  displayName: 'Cloud MCU',
  buildVideoChannelName: (deviceId) => `${deviceId}-cloud-mcu`,
  canUseBoardVideo: () => false,
  canUseDriveControl: () => false,
  extractTelemetry: (shadow) => {
    const reportedState = extractCloudMcuReportedState(shadow)
    return {
      reportedBatteryMv: null,
      reportedBoardPower: null,
      reportedBoardOnline: null,
      reportedMcuOnline: true,
      reportedMcuPower: reportedState.powered,
    }
  },
  getAutoOpenState: ({ hasActiveSession, routeKind }) => {
    if (routeKind !== 'device' || !hasActiveSession) {
      return null
    }
    return {
      isDetailPanelOpen: true,
      isBoardVideoExpanded: false,
    }
  },
  shouldCloseDetail: () => false,
  renderDetail: (props) =>
    createCloudMcuElement(
      CloudMcuPanel as (panelProps: Record<string, unknown>) => CloudMcuElement,
      { shadow: props.shadow },
    ),
  renderVideo: () =>
    createCloudMcuElement(
      'section',
      { className: 'power-device-panel', 'aria-label': 'Cloud MCU video' },
      createCloudMcuElement(
        'div',
        { className: 'power-device-metric' },
        createCloudMcuElement('span', { className: 'power-device-metric-label' }, 'Video'),
        createCloudMcuElement('span', { className: 'power-device-metric-value' }, 'unsupported'),
      ),
    ),
}

type CloudMcuElement = ReturnType<DeviceWebAdapter['renderDetail']>
type CloudMcuElementType = string | ((props: Record<string, unknown>) => CloudMcuElement)

const createCloudMcuElement = (
  type: CloudMcuElementType,
  props: Record<string, unknown> | null,
  ...children: unknown[]
): CloudMcuElement =>
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
  }) as CloudMcuElement

export default cloudMcuDeviceAdapter
