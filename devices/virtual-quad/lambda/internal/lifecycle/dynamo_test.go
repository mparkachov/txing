package lifecycle

import (
	"context"
	"errors"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb"
	"github.com/aws/aws-sdk-go-v2/service/dynamodb/types"
)

type fakeDynamo struct {
	get    *dynamodb.GetItemInput
	put    *dynamodb.PutItemInput
	item   map[string]types.AttributeValue
	putErr error
}

func (d *fakeDynamo) GetItem(_ context.Context, input *dynamodb.GetItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.GetItemOutput, error) {
	d.get = input
	return &dynamodb.GetItemOutput{Item: d.item}, nil
}

func (d *fakeDynamo) PutItem(_ context.Context, input *dynamodb.PutItemInput, _ ...func(*dynamodb.Options)) (*dynamodb.PutItemOutput, error) {
	d.put = input
	if d.putErr != nil {
		return nil, d.putErr
	}
	d.item = input.Item
	return &dynamodb.PutItemOutput{}, nil
}

func (d *fakeDynamo) Scan(_ context.Context, _ *dynamodb.ScanInput, _ ...func(*dynamodb.Options)) (*dynamodb.ScanOutput, error) {
	return &dynamodb.ScanOutput{Items: []map[string]types.AttributeValue{d.item}}, nil
}

func TestDynamoSessionUsesConditionalWritesAndConsistentReads(t *testing.T) {
	client := &fakeDynamo{}
	store := NewDynamoStore(client, "sessions")
	ledger := NewLedger(store)
	first := reserve(t, ledger, 0, testNow)
	if !aws.ToBool(client.get.ConsistentRead) || aws.ToString(client.get.TableName) != "sessions" {
		t.Fatal("session reads are not strongly consistent on the configured table")
	}
	if aws.ToString(client.put.ConditionExpression) != "attribute_not_exists(#device)" || client.put.ExpressionAttributeNames["#device"] != "deviceId" {
		t.Fatal("first reservation could overwrite an existing device record")
	}
	prepared := prepare(t, ledger, first.Session.ID, testNow)
	if aws.ToString(client.put.ConditionExpression) != "#version = :expected" ||
		client.put.ExpressionAttributeNames["#version"] != "version" ||
		client.put.ExpressionAttributeValues[":expected"].(*types.AttributeValueMemberN).Value != "1" {
		t.Fatal("launch update did not condition on the previous record version")
	}
	loaded, err := store.Load(t.Context(), target.DeviceID)
	if err != nil || loaded.Version != 2 || *loaded.Session.Launch != *prepared.Session.Launch {
		t.Fatalf("launch inputs did not round-trip through DynamoDB: %v", err)
	}
	if records, err := store.Records(t.Context()); err != nil || len(records) != 1 || records[0].DeviceID != target.DeviceID {
		t.Fatalf("session inventory did not decode the stored row: %v", err)
	}
	replacement := loaded
	replacement.Version++
	client.putErr = &types.ConditionalCheckFailedException{}
	if stored, err := store.CompareAndSwap(t.Context(), loaded.Version, replacement); err != nil || stored {
		t.Fatalf("conditional conflict became a successful write: %t %v", stored, err)
	}
	client.putErr = errors.New("ambiguous transport result")
	if stored, err := store.CompareAndSwap(t.Context(), loaded.Version, replacement); !errors.Is(err, client.putErr) || stored {
		t.Fatalf("unconfirmed storage write lost its error: %t %v", stored, err)
	}
}
