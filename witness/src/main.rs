use std::sync::Arc;

use lambda_runtime::{Error, LambdaEvent, service_fn};
use serde_json::Value;
use txing_witness_lambda::{AwsWitnessClient, handle_lambda_event};

#[tokio::main]
async fn main() -> Result<(), Error> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .json()
        .init();

    let aws = Arc::new(AwsWitnessClient::from_env().await?);
    lambda_runtime::run(service_fn(move |event: LambdaEvent<Value>| {
        let aws = aws.clone();
        async move {
            handle_lambda_event(event.payload, aws.as_ref())
                .await
                .map_err(Error::from)
        }
    }))
    .await
}
