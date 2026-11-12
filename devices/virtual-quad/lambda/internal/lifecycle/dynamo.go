package lifecycle

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strconv"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

type DynamoDBClient interface {
	GetItem(context.Context, *dynamodb.GetItemInput, ...func(*dynamodb.Options)) (*dynamodb.GetItemOutput, error)
	PutItem(context.Context, *dynamodb.PutItemInput, ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error)
	Scan(context.Context, *dynamodb.ScanInput, ...func(*dynamodb.Options)) (*dynamodb.ScanOutput, error)
}

type DynamoStore struct {
	client DynamoDBClient
	table  string
}

func NewDynamoStore(client DynamoDBClient, table string) DynamoStore {
	return DynamoStore{client: client, table: table}
}

func (s DynamoStore) Load(ctx context.Context, deviceID string) (Record, error) {
	result, err := s.client.GetItem(ctx, &dynamodb.GetItemInput{
		TableName: aws.String(s.table), ConsistentRead: aws.Bool(true),
		Key: map[string]types.AttributeValue{"deviceId": &types.AttributeValueMemberS{Value: deviceID}},
	})
	if err != nil {
		return Record{}, fmt.Errorf("read virtual quad session: %w", err)
	}
	if len(result.Item) == 0 {
		return Record{DeviceID: deviceID}, nil
	}
	record, err := decodeRecord(result.Item)
	if err == nil && record.DeviceID != deviceID {
		return Record{}, errors.New("virtual quad session key differs from requested device")
	}
	return record, err
}

func (s DynamoStore) Records(ctx context.Context) ([]Record, error) {
	paginator := dynamodb.NewScanPaginator(s.client, &dynamodb.ScanInput{
		TableName: aws.String(s.table), ConsistentRead: aws.Bool(true),
	})
	var records []Record
	tokens := map[string]bool{}
	for paginator.HasMorePages() {
		page, err := paginator.NextPage(ctx)
		if err != nil {
			return nil, fmt.Errorf("scan virtual quad sessions: %w", err)
		}
		if len(page.LastEvaluatedKey) != 0 {
			key, ok := page.LastEvaluatedKey["deviceId"].(*types.AttributeValueMemberS)
			if !ok || key.Value == "" || tokens[key.Value] {
				return nil, errors.New("virtual quad session scan did not advance")
			}
			tokens[key.Value] = true
		}
		for _, item := range page.Items {
			record, err := decodeRecord(item)
			if err != nil {
				return nil, err
			}
			records = append(records, record)
		}
	}
	return records, nil
}

func decodeRecord(item map[string]types.AttributeValue) (Record, error) {
	device, hasDevice := item["deviceId"].(*types.AttributeValueMemberS)
	payload, hasRecord := item["record"].(*types.AttributeValueMemberB)
	version, hasVersion := item["version"].(*types.AttributeValueMemberN)
	if !hasDevice || !hasRecord || !hasVersion {
		return Record{}, errors.New("virtual quad session is missing its key, record, or version")
	}
	var record Record
	if err := json.Unmarshal(payload.Value, &record); err != nil {
		return Record{}, fmt.Errorf("decode virtual quad session: %w", err)
	}
	if record.DeviceID == "" || record.DeviceID != device.Value || record.Version == 0 || version.Value != strconv.FormatUint(record.Version, 10) {
		return Record{}, errors.New("virtual quad session key or version does not match its record")
	}
	return record, nil
}

func (s DynamoStore) CompareAndSwap(ctx context.Context, version uint64, replacement Record) (bool, error) {
	if replacement.DeviceID == "" || replacement.Version == 0 || replacement.Version != version+1 {
		return false, ErrInvalidRequest
	}
	payload, err := json.Marshal(replacement)
	if err != nil {
		return false, fmt.Errorf("encode virtual quad session: %w", err)
	}
	request := &dynamodb.PutItemInput{
		TableName: aws.String(s.table),
		Item: map[string]types.AttributeValue{
			"deviceId": &types.AttributeValueMemberS{Value: replacement.DeviceID},
			"version":  &types.AttributeValueMemberN{Value: strconv.FormatUint(replacement.Version, 10)},
			"record":   &types.AttributeValueMemberB{Value: payload},
		},
	}
	if version == 0 {
		request.ConditionExpression = aws.String("attribute_not_exists(#device)")
		request.ExpressionAttributeNames = map[string]string{"#device": "deviceId"}
	} else {
		request.ConditionExpression = aws.String("#version = :expected")
		request.ExpressionAttributeNames = map[string]string{"#version": "version"}
		request.ExpressionAttributeValues = map[string]types.AttributeValue{
			":expected": &types.AttributeValueMemberN{Value: strconv.FormatUint(version, 10)},
		}
	}
	_, err = s.client.PutItem(ctx, request)
	var conflict *types.ConditionalCheckFailedException
	if errors.As(err, &conflict) {
		return false, nil
	}
	if err != nil {
		return false, fmt.Errorf("persist virtual quad session: %w", err)
	}
	return true, nil
}
