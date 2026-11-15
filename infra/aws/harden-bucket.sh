#!/usr/bin/env bash
# Locks down the existing bucket Sahaj stores uploaded documents in. It only CHANGES SETTINGS on the bucket: it never
# creates, empties or deletes it. Needs an AWS identity allowed to administer the bucket (not the app's own role).
#
#   aws sso login   (or export AWS_PROFILE=...)
#   infra/aws/harden-bucket.sh            # BUCKET=paytm-sahaj REGION=ap-southeast-2 by default
#
# After it, give the app's IAM role/user the policy in infra/aws/iam-policy.json.
set -euo pipefail
BUCKET="${BUCKET:-paytm-sahaj}"
REGION="${REGION:-ap-southeast-2}"
command -v aws >/dev/null || { echo "AWS CLI not found: brew install awscli" >&2; exit 1; }
aws sts get-caller-identity --query Arn -o text
aws s3api head-bucket --bucket "$BUCKET" --region "$REGION"

echo "Blocking all public access"
aws s3api put-public-access-block --bucket "$BUCKET" --region "$REGION" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

echo "Default encryption: SSE-S3 (the app also asks for it on every upload)"
aws s3api put-bucket-encryption --bucket "$BUCKET" --region "$REGION" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'

echo "Bucket owner enforced (no object ACLs)"
aws s3api put-bucket-ownership-controls --bucket "$BUCKET" --region "$REGION" \
  --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'

echo "Refusing any request that is not over TLS"
aws s3api put-bucket-policy --bucket "$BUCKET" --region "$REGION" --policy "{
  \"Version\":\"2012-10-17\",
  \"Statement\":[{\"Sid\":\"DenyInsecureTransport\",\"Effect\":\"Deny\",\"Principal\":\"*\",\"Action\":\"s3:*\",
    \"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"],
    \"Condition\":{\"Bool\":{\"aws:SecureTransport\":\"false\"}}}]}"

echo "Done. Versioning is left as it is: the app deletes every version of a withdrawn person's files either way."
echo "Do NOT add a lifecycle rule that keeps deleted versions, or consent withdrawal would not really erase."
