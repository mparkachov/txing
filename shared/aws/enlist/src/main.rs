use std::sync::Arc;

use lambda_runtime::{Error, LambdaEvent, service_fn};
use serde_json::Value;
use txing_enlist_lambda::{AwsEnlistClient, HttpCfnResponder, handle_lambda_event};

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .json()
        .init();

    let aws = Arc::new(AwsEnlistClient::from_env().await?);
    let responder = Arc::new(HttpCfnResponder::default());
    lambda_runtime::run(service_fn(move |event: LambdaEvent<Value>| {
        let aws = aws.clone();
        let responder = responder.clone();
        async move {
            Ok::<Value, Error>(
                handle_lambda_event(event.payload, aws.as_ref(), responder.as_ref()).await,
            )
        }
    }))
    .await
}
