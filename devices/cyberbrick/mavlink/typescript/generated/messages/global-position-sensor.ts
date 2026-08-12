import {MAVLinkMessage} from '../../runtime';
import {readInt64LE, readUInt64LE} from '../../runtime';
import {GlobalPositionSrc} from '../enums/global-position-src';
import {GlobalPositionFlags} from '../enums/global-position-flags';
/*
Reports measurement/estimate from a global position sensor. Used as navigation fusion source and optionally displayed in the UI.
*/
// target_system System ID (ID of target system, normally autopilot and ground station). uint8_t
// target_component Component ID (normally 0 for broadcast). uint8_t
// id Sensor ID uint8_t
// time_usec Timestamp of message transmission (UNIX Epoch time or time since system boot). The receiving end can infer timestamp format (since 1.1.1970 or since system boot) by checking for the magnitude of the number. uint64_t
// processing_time The time spent in processing the sensor data that is the basis for this position. The recipient can use this to improve time alignment of the data. This is the time between measurement (e.g. camera exposure time) and transmission of this message. Set to NaN if not known. uint32_t
// source Source of position/estimate (such as GNSS, estimator, etc.) uint8_t
// flags Status flags uint8_t
// lat Latitude (WGS84) int32_t
// lon Longitude (WGS84) int32_t
// alt_ellipsoid Altitude (WGS84 elipsoid), preferred if available float
// alt Altitude (MSL - position-system specific value) use if no alt_ellipsoid available float
// eph Standard deviation of horizontal position error float
// epv Standard deviation of vertical position error float
export class GlobalPositionSensor extends MAVLinkMessage {
	public target_system!: number;
	public target_component!: number;
	public id!: number;
	public time_usec!: number;
	public processing_time!: number;
	public source!: GlobalPositionSrc;
	public flags!: GlobalPositionFlags;
	public lat!: number;
	public lon!: number;
	public alt_ellipsoid!: number;
	public alt!: number;
	public eph!: number;
	public epv!: number;
	public _message_id: number = 296;
	public _message_name: string = 'GLOBAL_POSITION_SENSOR';
	public _crc_extra: number = 158;
	public _message_fields: [string, string, boolean][] = [
		['time_usec', 'uint64_t', false],
		['processing_time', 'uint32_t', false],
		['lat', 'int32_t', false],
		['lon', 'int32_t', false],
		['alt_ellipsoid', 'float', false],
		['alt', 'float', false],
		['eph', 'float', false],
		['epv', 'float', false],
		['target_system', 'uint8_t', false],
		['target_component', 'uint8_t', false],
		['id', 'uint8_t', false],
		['source', 'uint8_t', false],
		['flags', 'uint8_t', false],
	];
}