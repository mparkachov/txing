export enum EngineControlOptions {
	ENGINE_CONTROL_OPTIONS_ALLOW_START_WHILE_DISARMED = 1, // Allow starting the engine while disarmed (without changing the vehicle's armed state). This effectively arms just the ICE, without arming the vehicle to start other motors or propellers.
	ENGINE_CONTROL_OPTIONS_ENUM_END = 2, // 
}