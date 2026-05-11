use std::sync::Arc;

use lambda_runtime::{Error, LambdaEvent, service_fn};
use serde_json::Value;
use txing_time_lambda::{AwsTimeClient, handle_lambda_event_from_env};

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .json()
        .init();

    let aws = Arc::new(AwsTimeClient::from_env().await?);
    lambda_runtime::run(service_fn(move |event: LambdaEvent<Value>| {
        let aws = aws.clone();
        async move {
            handle_lambda_event_from_env(event.payload, aws.as_ref())
                .await
                .map_err(Error::from)
        }
    }))
    .await
}
