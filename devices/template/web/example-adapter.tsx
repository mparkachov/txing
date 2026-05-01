import type { DeviceWebAdapter } from "../../../web/src/device-adapter";

const exampleAdapter: DeviceWebAdapter = {
  type: "example",
  displayName: "Example Device",
  buildVideoChannelName: (deviceId) => `${deviceId}-board-video`,
  canUseBoardVideo: () => false,
  extractTelemetry: () => ({
    reportedBatteryMv: null,
    reportedBoardPower: null,
    reportedBoardOnline: null,
    reportedMcuOnline: null,
    reportedMcuPower: null
  }),
  getAutoOpenState: () => null,
  shouldCloseDetail: () => false,
  renderDetail: () => (
    <section className="card catalog-card">
      <h1>Example Device</h1>
      <p>Replace this scaffold with the device-specific detail panel.</p>
    </section>
  ),
  renderVideo: () => (
    <section className="card catalog-card">
      <h1>Video unavailable</h1>
    </section>
  )
};

export default exampleAdapter;
