export enum GlobalPositionSrc {
	GLOBAL_POSITION_SRC_UNKNOWN = 0, // Source is unknown or not one of the listed types.
	GLOBAL_POSITION_SRC_GNSS = 1, // Global Navigation Satellite System (e.g.: GPS, Galileo, Glonass, BeiDou).
	GLOBAL_POSITION_SRC_VISION = 2, // Vision system (e.g.: map matching).
	GLOBAL_POSITION_SRC_PSEUDOLITES = 3, // A pseudo-satellite system using transceiver beacons to perform GNSS-like positioning.
	GLOBAL_POSITION_SRC_TERRAIN = 4, // Terrain referenced navigation.
	GLOBAL_POSITION_SRC_MAGNETIC = 5, // Magnetic positioning.
	GLOBAL_POSITION_SRC_ESTIMATOR = 6, // Estimated position based on various sensors (eg. a Kalman Filter).
	GLOBAL_POSITION_SRC_LEO = 7, // Low Earth Orbit satellite-based positioning (e.g.: Starlink, Xona PULSAR).
	GLOBAL_POSITION_SRC_ENUM_END = 8, // 
}