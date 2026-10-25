#!/usr/bin/env bash
# Delete EVERYTHING this project created in AWS (users, scores, content, the web app). Cannot be undone.
set -euo pipefail
STACK=imt-pulse
REGION=ap-southeast-2
export AWS_PAGER=""
read -r -p "Type DELETE to remove the whole IMT Pulse stack and all its data: " ok
[ "$ok" = "DELETE" ] || { echo "Cancelled."; exit 1; }
BUCKET=$(aws cloudformation describe-stacks --stack-name "$STACK" --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='WebBucketName'].OutputValue" --output text)
aws s3 rm "s3://$BUCKET" --recursive --region "$REGION"     # a bucket must be empty before it can be deleted
aws cloudformation delete-stack --stack-name "$STACK" --region "$REGION"
aws cloudformation wait stack-delete-complete --stack-name "$STACK" --region "$REGION"
echo "Stack deleted. Optional: also delete the SAM artifacts bucket with"
echo "  aws cloudformation delete-stack --stack-name aws-sam-cli-managed-default --region $REGION  (empty its bucket first)"
echo "The IMT-Pulse-Pilot budget is separate; delete it in the Billing console if you no longer want alerts."
