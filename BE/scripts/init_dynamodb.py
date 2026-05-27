import os

import boto3
from botocore.exceptions import ClientError


TABLE_NAME = os.environ.get("DOCUMENTS_TABLE", "StudyBotDocuments")
ENDPOINT_URL = os.environ.get("DDB_ENDPOINT_URL", "http://localhost:8000")
AWS_REGION = os.environ.get("AWS_REGION", "ap-southeast-1")


def main():
    ddb = boto3.client(
        "dynamodb",
        endpoint_url=ENDPOINT_URL,
        region_name=AWS_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "dummy"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "dummy"),
    )

    try:
        ddb.describe_table(TableName=TABLE_NAME)
        print(f"Table already exists: {TABLE_NAME}")
        return
    except ClientError as error:
        code = error.response.get("Error", {}).get("Code")
        if code != "ResourceNotFoundException":
            raise

    ddb.create_table(
        TableName=TABLE_NAME,
        AttributeDefinitions=[
            {"AttributeName": "PK", "AttributeType": "S"},
            {"AttributeName": "SK", "AttributeType": "S"},
        ],
        KeySchema=[
            {"AttributeName": "PK", "KeyType": "HASH"},
            {"AttributeName": "SK", "KeyType": "RANGE"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    print(f"Created table: {TABLE_NAME}")


if __name__ == "__main__":
    main()
