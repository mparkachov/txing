// IoT role-alias credential exchange copied from
// devices/unit/daemon/internal/daemon/runtime.go. Pure stdlib: the mac
// daemon does not use the AWS SDK. The daemon is the credential
// authority for the KVS worker over the BoardVideoBridge.
package action

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

type IotCredentialsRequest struct {
	URL       string
	ThingName string
}

type iotCredentialsEnvelope struct {
	Credentials IotTemporaryCredentials `json:"credentials"`
}

type IotTemporaryCredentials struct {
	AccessKeyID     string `json:"accessKeyId"`
	SecretAccessKey string `json:"secretAccessKey"`
	SessionToken    string `json:"sessionToken"`
	Expiration      string `json:"expiration"`
}

func BuildIotCredentialsRequest(config Config) (IotCredentialsRequest, error) {
	if err := validateEndpointHost(config.IoTCredentialEndpoint, "iot-credential-endpoint"); err != nil {
		return IotCredentialsRequest{}, err
	}
	if err := validateRoleAlias(config.IoTRoleAlias); err != nil {
		return IotCredentialsRequest{}, err
	}
	return IotCredentialsRequest{URL: fmt.Sprintf("https://%s/role-aliases/%s/credentials", config.IoTCredentialEndpoint, config.IoTRoleAlias), ThingName: config.ThingID}, nil
}

func ParseIotCredentialsResponse(payload []byte) (IotTemporaryCredentials, error) {
	var envelope iotCredentialsEnvelope
	if err := json.Unmarshal(payload, &envelope); err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("parse AWS IoT credential provider response: %w", err)
	}
	if err := envelope.Credentials.validate(); err != nil {
		return IotTemporaryCredentials{}, err
	}
	return envelope.Credentials, nil
}

func (c IotTemporaryCredentials) validate() error {
	if strings.TrimSpace(c.AccessKeyID) == "" {
		return errors.New("accessKeyId must not be empty")
	}
	if strings.TrimSpace(c.SecretAccessKey) == "" {
		return errors.New("secretAccessKey must not be empty")
	}
	if strings.TrimSpace(c.SessionToken) == "" {
		return errors.New("sessionToken must not be empty")
	}
	if strings.TrimSpace(c.Expiration) == "" {
		return errors.New("expiration must not be empty")
	}
	return nil
}

func ParseIotTemporaryCredentialsExpiration(value string) (time.Time, error) {
	parsed, err := time.Parse(time.RFC3339, value)
	if err != nil {
		return time.Time{}, fmt.Errorf("parse IoT temporary credential expiration %q: %w", value, err)
	}
	return parsed, nil
}

func FetchIotTemporaryCredentials(ctx context.Context, config Config) (IotTemporaryCredentials, error) {
	request, err := BuildIotCredentialsRequest(config)
	if err != nil {
		return IotTemporaryCredentials{}, err
	}
	cert, err := tls.LoadX509KeyPair(config.IoTCertFile, config.IoTPrivateKeyFile)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("load IoT client identity: %w", err)
	}
	rootPEM, err := os.ReadFile(config.IoTRootCAFile)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("read IoT root CA %s: %w", config.IoTRootCAFile, err)
	}
	roots := x509.NewCertPool()
	if !roots.AppendCertsFromPEM(rootPEM) {
		return IotTemporaryCredentials{}, errors.New("load IoT root CA")
	}
	client := http.Client{Transport: &http.Transport{TLSClientConfig: &tls.Config{Certificates: []tls.Certificate{cert}, RootCAs: roots, MinVersion: tls.VersionTLS12}}}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, request.URL, nil)
	if err != nil {
		return IotTemporaryCredentials{}, err
	}
	req.Header.Set("x-amzn-iot-thingname", request.ThingName)
	response, err := client.Do(req)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("request AWS IoT temporary credentials: %w", err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return IotTemporaryCredentials{}, fmt.Errorf("read AWS IoT temporary credential response: %w", err)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return IotTemporaryCredentials{}, fmt.Errorf("AWS IoT temporary credential request failed: %s", response.Status)
	}
	return ParseIotCredentialsResponse(body)
}
