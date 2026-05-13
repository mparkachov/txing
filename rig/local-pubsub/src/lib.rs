use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};
use std::sync::Arc;

use anyhow::{Context, Result, anyhow, bail};
use base64::Engine;
use base64::engine::general_purpose::STANDARD;
use serde::{Deserialize, Serialize};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::net::{UnixListener, UnixStream};
use tokio::sync::{Mutex, mpsc};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LocalMessage {
    pub topic: String,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone)]
pub struct LocalPubSubPublisher {
    writer: Arc<Mutex<tokio::net::unix::OwnedWriteHalf>>,
}

pub struct LocalPubSubClient {
    publisher: LocalPubSubPublisher,
    receiver: mpsc::UnboundedReceiver<Result<LocalMessage, String>>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "camelCase")]
enum ClientFrame {
    Subscribe { topic: String },
    Publish { topic: String, payload: String },
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "camelCase")]
enum ServerFrame {
    Message { topic: String, payload: String },
    Error { message: String },
}

#[derive(Debug, Default)]
struct BrokerState {
    next_client_id: u64,
    clients: BTreeMap<u64, BrokerClient>,
}

#[derive(Debug)]
struct BrokerClient {
    filters: BTreeSet<String>,
    sender: mpsc::UnboundedSender<ServerFrame>,
}

impl LocalPubSubClient {
    pub async fn connect(socket_path: impl AsRef<Path>) -> Result<Self> {
        let stream = UnixStream::connect(socket_path.as_ref())
            .await
            .with_context(|| {
                format!(
                    "connect local pub/sub socket {}",
                    socket_path.as_ref().display()
                )
            })?;
        let (reader, writer) = stream.into_split();
        let (sender, receiver) = mpsc::unbounded_channel();
        tokio::spawn(async move {
            let mut lines = BufReader::new(reader).lines();
            loop {
                match lines.next_line().await {
                    Ok(Some(line)) => {
                        if line.trim().is_empty() {
                            continue;
                        }
                        match serde_json::from_str::<ServerFrame>(&line) {
                            Ok(ServerFrame::Message { topic, payload }) => {
                                let decoded = STANDARD
                                    .decode(payload.as_bytes())
                                    .map_err(|err| format!("decode local pub/sub payload: {err}"))
                                    .map(|payload| LocalMessage { topic, payload });
                                if sender.send(decoded).is_err() {
                                    break;
                                }
                            }
                            Ok(ServerFrame::Error { message }) => {
                                if sender.send(Err(message)).is_err() {
                                    break;
                                }
                            }
                            Err(err) => {
                                if sender
                                    .send(Err(format!("decode local pub/sub frame: {err}")))
                                    .is_err()
                                {
                                    break;
                                }
                            }
                        }
                    }
                    Ok(None) => break,
                    Err(err) => {
                        let _ = sender.send(Err(format!("read local pub/sub socket: {err}")));
                        break;
                    }
                }
            }
        });
        Ok(Self {
            publisher: LocalPubSubPublisher {
                writer: Arc::new(Mutex::new(writer)),
            },
            receiver,
        })
    }

    pub fn publisher(&self) -> LocalPubSubPublisher {
        self.publisher.clone()
    }

    pub async fn subscribe(&self, topic: impl Into<String>) -> Result<()> {
        self.publisher.subscribe(topic).await
    }

    pub async fn publish(&self, topic: impl Into<String>, payload: impl AsRef<[u8]>) -> Result<()> {
        self.publisher.publish(topic, payload).await
    }

    pub async fn recv(&mut self) -> Option<Result<LocalMessage, String>> {
        self.receiver.recv().await
    }
}

impl LocalPubSubPublisher {
    pub async fn subscribe(&self, topic: impl Into<String>) -> Result<()> {
        self.write_frame(&ClientFrame::Subscribe {
            topic: topic.into(),
        })
        .await
    }

    pub async fn publish(&self, topic: impl Into<String>, payload: impl AsRef<[u8]>) -> Result<()> {
        self.write_frame(&ClientFrame::Publish {
            topic: topic.into(),
            payload: STANDARD.encode(payload.as_ref()),
        })
        .await
    }

    async fn write_frame(&self, frame: &ClientFrame) -> Result<()> {
        let mut encoded = serde_json::to_vec(frame)?;
        encoded.push(b'\n');
        let mut writer = self.writer.lock().await;
        writer
            .write_all(&encoded)
            .await
            .context("write local pub/sub frame")
    }
}

pub async fn run_broker_until_shutdown(
    socket_path: PathBuf,
    shutdown: impl std::future::Future<Output = ()>,
) -> Result<()> {
    prepare_socket_path(&socket_path)?;
    let listener = UnixListener::bind(&socket_path)
        .with_context(|| format!("bind local pub/sub socket {}", socket_path.display()))?;
    let state = Arc::new(Mutex::new(BrokerState::default()));
    tokio::pin!(shutdown);
    loop {
        tokio::select! {
            _ = &mut shutdown => break,
            accepted = listener.accept() => {
                let (stream, _) = accepted.context("accept local pub/sub client")?;
                spawn_client(stream, state.clone()).await;
            }
        }
    }
    let _ = std::fs::remove_file(&socket_path);
    Ok(())
}

fn prepare_socket_path(socket_path: &Path) -> Result<()> {
    if let Some(parent) = socket_path.parent() {
        std::fs::create_dir_all(parent).with_context(|| {
            format!("create local pub/sub socket directory {}", parent.display())
        })?;
    }
    match std::fs::remove_file(socket_path) {
        Ok(()) => Ok(()),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(err) => Err(err).with_context(|| {
            format!(
                "remove stale local pub/sub socket {}",
                socket_path.display()
            )
        }),
    }
}

async fn spawn_client(stream: UnixStream, state: Arc<Mutex<BrokerState>>) {
    let (reader, writer) = stream.into_split();
    let (sender, mut receiver) = mpsc::unbounded_channel::<ServerFrame>();
    let client_id = {
        let mut guard = state.lock().await;
        guard.next_client_id += 1;
        let client_id = guard.next_client_id;
        guard.clients.insert(
            client_id,
            BrokerClient {
                filters: BTreeSet::new(),
                sender,
            },
        );
        client_id
    };

    let state_for_reader = state.clone();
    tokio::spawn(async move {
        let mut lines = BufReader::new(reader).lines();
        loop {
            match lines.next_line().await {
                Ok(Some(line)) => {
                    if line.trim().is_empty() {
                        continue;
                    }
                    match serde_json::from_str::<ClientFrame>(&line) {
                        Ok(ClientFrame::Subscribe { topic }) => {
                            if let Err(err) =
                                subscribe_client(&state_for_reader, client_id, topic).await
                            {
                                send_error(&state_for_reader, client_id, err.to_string()).await;
                            }
                        }
                        Ok(ClientFrame::Publish { topic, payload }) => {
                            if let Err(err) =
                                publish_message(&state_for_reader, topic, payload).await
                            {
                                send_error(&state_for_reader, client_id, err.to_string()).await;
                            }
                        }
                        Err(err) => {
                            send_error(
                                &state_for_reader,
                                client_id,
                                format!("decode client frame: {err}"),
                            )
                            .await;
                        }
                    }
                }
                Ok(None) => break,
                Err(err) => {
                    send_error(
                        &state_for_reader,
                        client_id,
                        format!("read client frame: {err}"),
                    )
                    .await;
                    break;
                }
            }
        }
        state_for_reader.lock().await.clients.remove(&client_id);
    });

    tokio::spawn(async move {
        let mut writer = writer;
        while let Some(frame) = receiver.recv().await {
            let mut encoded = match serde_json::to_vec(&frame) {
                Ok(value) => value,
                Err(_) => continue,
            };
            encoded.push(b'\n');
            if writer.write_all(&encoded).await.is_err() {
                break;
            }
        }
    });
}

async fn subscribe_client(
    state: &Arc<Mutex<BrokerState>>,
    client_id: u64,
    topic: String,
) -> Result<()> {
    validate_filter(&topic)?;
    let mut guard = state.lock().await;
    let client = guard
        .clients
        .get_mut(&client_id)
        .ok_or_else(|| anyhow!("client is disconnected"))?;
    client.filters.insert(topic);
    Ok(())
}

async fn publish_message(
    state: &Arc<Mutex<BrokerState>>,
    topic: String,
    payload: String,
) -> Result<()> {
    validate_topic(&topic)?;
    STANDARD
        .decode(payload.as_bytes())
        .context("decode published payload")?;
    let frame = ServerFrame::Message {
        topic: topic.clone(),
        payload,
    };
    let recipients = {
        let guard = state.lock().await;
        guard
            .clients
            .values()
            .filter(|client| {
                client
                    .filters
                    .iter()
                    .any(|filter| topic_matches(filter, &topic))
            })
            .map(|client| client.sender.clone())
            .collect::<Vec<_>>()
    };
    for recipient in recipients {
        let _ = recipient.send(frame.clone());
    }
    Ok(())
}

async fn send_error(state: &Arc<Mutex<BrokerState>>, client_id: u64, message: String) {
    let sender = state
        .lock()
        .await
        .clients
        .get(&client_id)
        .map(|client| client.sender.clone());
    if let Some(sender) = sender {
        let _ = sender.send(ServerFrame::Error { message });
    }
}

pub fn topic_matches(filter: &str, topic: &str) -> bool {
    if filter == topic {
        return true;
    }
    let filter_parts = filter.split('/').collect::<Vec<_>>();
    let topic_parts = topic.split('/').collect::<Vec<_>>();
    for (index, filter_part) in filter_parts.iter().enumerate() {
        if *filter_part == "#" {
            return index == filter_parts.len() - 1;
        }
        let Some(topic_part) = topic_parts.get(index) else {
            return false;
        };
        if *filter_part == "+" {
            continue;
        }
        if filter_part != topic_part {
            return false;
        }
    }
    filter_parts.len() == topic_parts.len()
}

fn validate_filter(filter: &str) -> Result<()> {
    if filter.trim().is_empty() {
        bail!("topic filter must not be empty");
    }
    for (index, part) in filter.split('/').enumerate() {
        if part.is_empty() {
            bail!("topic filter must not contain empty segments");
        }
        if part.contains('#') && (part != "#" || index != filter.split('/').count() - 1) {
            bail!("multi-level wildcard must occupy the final topic segment");
        }
        if part.contains('+') && part != "+" {
            bail!("single-level wildcard must occupy a complete topic segment");
        }
    }
    Ok(())
}

fn validate_topic(topic: &str) -> Result<()> {
    if topic.trim().is_empty() {
        bail!("topic must not be empty");
    }
    if topic.split('/').any(str::is_empty) {
        bail!("topic must not contain empty segments");
    }
    if topic.contains('+') || topic.contains('#') {
        bail!("published topic must not contain wildcards");
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::sync::oneshot;

    #[test]
    fn topic_matching_supports_mqtt_wildcards() {
        assert!(topic_matches(
            "dev/txing/rig/v2/#",
            "dev/txing/rig/v2/inventory"
        ));
        assert!(topic_matches(
            "dev/txing/rig/v2/capability/command/+",
            "dev/txing/rig/v2/capability/command/unit-1"
        ));
        assert!(!topic_matches(
            "dev/txing/rig/v2/capability/command/+",
            "dev/txing/rig/v2/capability/command/unit-1/extra"
        ));
        assert!(!topic_matches("dev/txing/rig/v2/+", "dev/txing/rig/v2"));
    }

    #[tokio::test]
    async fn broker_fans_out_binary_payloads() {
        let tempdir = tempfile::tempdir().unwrap();
        let socket = tempdir.path().join("pubsub.sock");
        let (shutdown_sender, shutdown_receiver) = oneshot::channel();
        let server_socket = socket.clone();
        let server = tokio::spawn(async move {
            run_broker_until_shutdown(server_socket, async {
                let _ = shutdown_receiver.await;
            })
            .await
            .unwrap();
        });
        wait_for_socket(&socket).await;

        let mut first = LocalPubSubClient::connect(&socket).await.unwrap();
        first.subscribe("test/+/state").await.unwrap();
        let mut second = LocalPubSubClient::connect(&socket).await.unwrap();
        second.subscribe("test/device/state").await.unwrap();
        let publisher = LocalPubSubClient::connect(&socket).await.unwrap();
        publisher
            .publish("test/device/state", [0, 1, 2, 255])
            .await
            .unwrap();

        assert_eq!(
            first.recv().await.unwrap().unwrap(),
            LocalMessage {
                topic: "test/device/state".to_string(),
                payload: vec![0, 1, 2, 255],
            }
        );
        assert_eq!(
            second.recv().await.unwrap().unwrap(),
            LocalMessage {
                topic: "test/device/state".to_string(),
                payload: vec![0, 1, 2, 255],
            }
        );
        let _ = shutdown_sender.send(());
        server.await.unwrap();
    }

    #[tokio::test]
    async fn disconnected_subscribers_are_removed() {
        let tempdir = tempfile::tempdir().unwrap();
        let socket = tempdir.path().join("pubsub.sock");
        let (shutdown_sender, shutdown_receiver) = oneshot::channel();
        let server_socket = socket.clone();
        let server = tokio::spawn(async move {
            run_broker_until_shutdown(server_socket, async {
                let _ = shutdown_receiver.await;
            })
            .await
            .unwrap();
        });
        wait_for_socket(&socket).await;

        let subscriber = LocalPubSubClient::connect(&socket).await.unwrap();
        subscriber.subscribe("test/#").await.unwrap();
        drop(subscriber);
        let mut replacement = LocalPubSubClient::connect(&socket).await.unwrap();
        replacement.subscribe("test/#").await.unwrap();
        let publisher = LocalPubSubClient::connect(&socket).await.unwrap();
        publisher.publish("test/topic", b"payload").await.unwrap();

        assert_eq!(
            replacement.recv().await.unwrap().unwrap(),
            LocalMessage {
                topic: "test/topic".to_string(),
                payload: b"payload".to_vec(),
            }
        );
        let _ = shutdown_sender.send(());
        server.await.unwrap();
    }

    async fn wait_for_socket(socket: &Path) {
        for _ in 0..100 {
            if socket.exists() {
                return;
            }
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        panic!("socket did not appear: {}", socket.display());
    }
}
