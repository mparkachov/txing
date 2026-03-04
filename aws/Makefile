SHELL := /bin/bash

MAKEFILE_DIR := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
PROJECT_ROOT ?= $(abspath $(MAKEFILE_DIR)/..)

STACK_NAME ?= txing-iot
TEMPLATE_FILE ?= template.yaml
REGION ?= eu-central-1
PROFILE ?=
THING_NAME ?= txing
POLICY_NAME ?= txing-gw-policy
CERT_DIR ?= $(PROJECT_ROOT)/certs
CERT_BASENAME ?= $(THING_NAME)-gw
CERT_ARN_FILE ?= $(CERT_DIR)/$(CERT_BASENAME).cert.arn
ENDPOINT_FILE ?= $(CERT_DIR)/iot-data-ats.endpoint
CA_FILE ?= $(CERT_DIR)/AmazonRootCA1.pem
CA_URL ?= https://www.amazontrust.com/repository/AmazonRootCA1.pem
DEFAULT_SHADOW_FILE ?= default-shadow.json
SHADOW_RESPONSE_FILE ?= $(CERT_DIR)/$(THING_NAME).shadow-response.json
IOT_DATA_ENDPOINT ?=
AWS_FLAGS := --region $(REGION) $(if $(PROFILE),--profile $(PROFILE),)
CFN_FLAGS := --stack-name $(STACK_NAME) --template-body file://$(TEMPLATE_FILE) $(AWS_FLAGS)

ifeq ($(strip $(REGION)),)
$(error REGION is empty and no default AWS region is configured. Set REGION=<aws-region>)
endif

.PHONY: create update deploy delete validate describe cert endpoint ca init-shadow bootstrap

create:
	aws cloudformation create-stack $(CFN_FLAGS)
	aws cloudformation wait stack-create-complete --stack-name $(STACK_NAME) $(AWS_FLAGS)
	$(MAKE) describe

update:
	@set -e; \
	OUTPUT="$$(aws cloudformation update-stack $(CFN_FLAGS) 2>&1)" || { \
		if echo "$$OUTPUT" | grep -q "No updates are to be performed"; then \
			echo "$$OUTPUT"; \
			exit 0; \
		fi; \
		echo "$$OUTPUT"; \
		exit 1; \
	}; \
	echo "$$OUTPUT"; \
	aws cloudformation wait stack-update-complete --stack-name $(STACK_NAME) $(AWS_FLAGS); \
	$(MAKE) describe STACK_NAME=$(STACK_NAME) TEMPLATE_FILE=$(TEMPLATE_FILE) REGION=$(REGION) PROFILE="$(PROFILE)"

deploy:
	@set -e; \
	if aws cloudformation describe-stacks --stack-name $(STACK_NAME) $(AWS_FLAGS) >/dev/null 2>&1; then \
		$(MAKE) update STACK_NAME=$(STACK_NAME) TEMPLATE_FILE=$(TEMPLATE_FILE) REGION=$(REGION) PROFILE="$(PROFILE)"; \
	else \
		$(MAKE) create STACK_NAME=$(STACK_NAME) TEMPLATE_FILE=$(TEMPLATE_FILE) REGION=$(REGION) PROFILE="$(PROFILE)"; \
	fi

delete:
	@set -e; \
	PRINCIPALS="$$(aws iot list-thing-principals --thing-name $(THING_NAME) $(AWS_FLAGS) --query principals --output text 2>/dev/null || true)"; \
	if [ -n "$$PRINCIPALS" ] && [ "$$PRINCIPALS" != "None" ]; then \
		for PRINCIPAL in $$PRINCIPALS; do \
			aws iot detach-thing-principal --thing-name $(THING_NAME) --principal "$$PRINCIPAL" $(AWS_FLAGS) || true; \
		done; \
	fi; \
	TARGETS="$$(aws iot list-targets-for-policy --policy-name $(POLICY_NAME) $(AWS_FLAGS) --query targets --output text 2>/dev/null || true)"; \
	if [ -n "$$TARGETS" ] && [ "$$TARGETS" != "None" ]; then \
		for TARGET in $$TARGETS; do \
			aws iot detach-policy --policy-name $(POLICY_NAME) --target "$$TARGET" $(AWS_FLAGS) || true; \
		done; \
	fi
	aws cloudformation delete-stack --stack-name $(STACK_NAME) $(AWS_FLAGS)
	aws cloudformation wait stack-delete-complete --stack-name $(STACK_NAME) $(AWS_FLAGS)

validate:
	aws cloudformation validate-template --template-body file://$(TEMPLATE_FILE) $(AWS_FLAGS)

describe:
	aws cloudformation describe-stacks \
		--stack-name $(STACK_NAME) \
		$(AWS_FLAGS) \
		--query "Stacks[0].Outputs" \
		--output table

cert:
	@mkdir -p $(CERT_DIR)
	@if [ -f $(CERT_ARN_FILE) ]; then \
		echo "$(CERT_ARN_FILE) already exists. Reuse this certificate or delete the file to issue a new one."; \
		exit 0; \
	fi
	@set -e; \
	CERT_ARN="$$(aws iot create-keys-and-certificate \
		--set-as-active \
		--certificate-pem-outfile $(CERT_DIR)/$(CERT_BASENAME).cert.pem \
		--public-key-outfile $(CERT_DIR)/$(CERT_BASENAME).public.key \
		--private-key-outfile $(CERT_DIR)/$(CERT_BASENAME).private.key \
		$(AWS_FLAGS) \
		--query certificateArn \
		--output text)"; \
	echo "$$CERT_ARN" | tee $(CERT_ARN_FILE); \
	aws iot attach-policy --policy-name $(POLICY_NAME) --target "$$CERT_ARN" $(AWS_FLAGS); \
	aws iot attach-thing-principal --thing-name $(THING_NAME) --principal "$$CERT_ARN" $(AWS_FLAGS); \
	echo "Certificate ARN saved to $(CERT_ARN_FILE)"

endpoint:
	@mkdir -p $(CERT_DIR)
	aws iot describe-endpoint \
		--endpoint-type iot:Data-ATS \
		$(AWS_FLAGS) \
		--query endpointAddress \
		--output text | tee $(ENDPOINT_FILE)

ca:
	@mkdir -p $(CERT_DIR)
	curl -fsSL $(CA_URL) -o $(CA_FILE)
	@echo "Root CA saved to $(CA_FILE)"

init-shadow:
	@mkdir -p $(CERT_DIR)
	@set -e; \
	ENDPOINT="$${IOT_DATA_ENDPOINT:-$$(aws iot describe-endpoint --endpoint-type iot:Data-ATS $(AWS_FLAGS) --query endpointAddress --output text)}"; \
	aws iot-data update-thing-shadow \
		--endpoint-url https://$$ENDPOINT \
		--thing-name $(THING_NAME) \
		--payload fileb://$(DEFAULT_SHADOW_FILE) \
		$(AWS_FLAGS) \
		$(SHADOW_RESPONSE_FILE)
	@echo "Shadow initialized from $(DEFAULT_SHADOW_FILE)"

bootstrap: deploy cert endpoint ca init-shadow
