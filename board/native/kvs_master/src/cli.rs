use crate::RuntimeConfig;
use crate::rpicam::CameraConfig;
use clap::Parser;
use std::path::PathBuf;

#[derive(Debug, Clone, Parser)]
#[command(
    name = "txing-board-kvs-master",
    about = "Board-local AWS KVS WebRTC master for txing"
)]
pub struct Cli {
    #[arg(long, env = "TXING_BOARD_VIDEO_REGION")]
    pub region: String,

    #[arg(long = "channel-name", env = "TXING_BOARD_VIDEO_CHANNEL_NAME")]
    pub channel_name: String,

    #[arg(long, default_value = "txing-board-kvs-master")]
    pub client_id: String,

    #[arg(long = "rpicam-vid-path", default_value = "/usr/bin/rpicam-vid")]
    pub rpicam_vid_path: PathBuf,

    #[arg(long, default_value_t = 0)]
    pub camera: u32,

    #[arg(long, default_value_t = 1920)]
    pub width: u32,

    #[arg(long, default_value_t = 1080)]
    pub height: u32,

    #[arg(long, default_value_t = 30)]
    pub framerate: u32,

    #[arg(long, default_value_t = 8_000_000)]
    pub bitrate: u32,

    #[arg(long, default_value_t = 30)]
    pub intra: u32,
}

impl From<Cli> for RuntimeConfig {
    fn from(value: Cli) -> Self {
        Self {
            region: value.region,
            channel_name: value.channel_name,
            client_id: value.client_id,
            camera: CameraConfig {
                path: value.rpicam_vid_path,
                camera: value.camera,
                width: value.width,
                height: value.height,
                framerate: value.framerate,
                bitrate: value.bitrate,
                intra: value.intra,
            },
        }
    }
}

#[cfg(test)]
mod tests {
    use super::Cli;
    use clap::Parser;

    #[test]
    fn parses_explicit_cli_values() {
        let cli = Cli::parse_from([
            "txing-board-kvs-master",
            "--region",
            "eu-central-1",
            "--channel-name",
            "txing-board-video",
            "--client-id",
            "board-master",
            "--width",
            "1280",
            "--height",
            "720",
            "--framerate",
            "15",
            "--bitrate",
            "1200000",
            "--intra",
            "15",
        ]);

        assert_eq!(cli.region, "eu-central-1");
        assert_eq!(cli.channel_name, "txing-board-video");
        assert_eq!(cli.client_id, "board-master");
        assert_eq!(cli.width, 1280);
        assert_eq!(cli.height, 720);
        assert_eq!(cli.framerate, 15);
        assert_eq!(cli.bitrate, 1_200_000);
        assert_eq!(cli.intra, 15);
    }
}
