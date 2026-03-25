use txing_board_kvs_master::h264::AnnexBAccessUnitParser;
use txing_board_kvs_master::rpicam::{CameraConfig, build_command_arguments};

#[test]
fn parser_finishes_trailing_access_unit() {
    let mut parser = AnnexBAccessUnitParser::new();
    let stream = [0x00, 0x00, 0x00, 0x01, 0x65, 0x80];
    assert!(parser.push(&stream).is_empty());
    let final_units = parser.finish();
    assert_eq!(final_units.len(), 1);
    assert!(final_units[0].is_keyframe);
}

#[test]
fn command_uses_expected_defaults() {
    let arguments = build_command_arguments(&CameraConfig {
        path: "/usr/bin/rpicam-vid".into(),
        camera: 0,
        width: 1920,
        height: 1080,
        framerate: 30,
        bitrate: 8_000_000,
        intra: 30,
    });

    assert!(arguments.contains(&"--inline".to_string()));
    assert!(arguments.contains(&"1920".to_string()));
    assert!(arguments.contains(&"1080".to_string()));
    assert!(arguments.contains(&"8000000".to_string()));
}
