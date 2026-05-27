locals {
	studybot_tags = {
		Project     = "StudyBot"
		Environment = "W7Demo"
		ManagedBy   = "Terraform"
	}
}

resource "aws_dynamodb_table" "studybot_documents" {
	name         = "StudyBotDocuments"
	billing_mode = "PAY_PER_REQUEST"
	hash_key     = "PK"
	range_key    = "SK"

	attribute {
		name = "PK"
		type = "S"
	}

	attribute {
		name = "SK"
		type = "S"
	}

	tags = local.studybot_tags
}

resource "aws_dynamodb_table_item" "demo_user_profile" {
	table_name = aws_dynamodb_table.studybot_documents.name
	hash_key   = "PK"
	range_key  = "SK"

	item = <<ITEM
{
	"PK": {"S": "USER#demo"},
	"SK": {"S": "PROFILE"},
	"user_id": {"S": "demo"},
	"email": {"S": "demo@studybot.com"},
	"created_at": {"S": "2026-05-28T09:00:00Z"}
}
ITEM
}

resource "aws_dynamodb_table_item" "demo_document" {
	table_name = aws_dynamodb_table.studybot_documents.name
	hash_key   = "PK"
	range_key  = "SK"

	item = <<ITEM
{
	"PK": {"S": "USER#demo"},
	"SK": {"S": "DOC#doc_001"},
	"doc_id": {"S": "doc_001"},
	"title": {"S": "Distributed Systems Lecture.pdf"},
	"s3_key": {"S": "users/demo/docs/doc_001.pdf"},
	"kb_status": {"S": "READY"},
	"uploaded_at": {"S": "2026-05-28T10:00:00Z"},
	"page_count": {"N": "40"},
	"concepts": {
		"L": [
			{"S": "CAP theorem"},
			{"S": "Replication"},
			{"S": "Consistency model"},
			{"S": "Quorum"},
			{"S": "Partition tolerance"}
		]
	}
}
ITEM
}

resource "aws_dynamodb_table_item" "demo_summary" {
	table_name = aws_dynamodb_table.studybot_documents.name
	hash_key   = "PK"
	range_key  = "SK"

	item = <<ITEM
{
	"PK": {"S": "USER#demo"},
	"SK": {"S": "DOC#doc_001#SUMMARY"},
	"doc_id": {"S": "doc_001"},
	"summary": {"S": "This lecture explains..."},
	"testable_concepts": {
		"L": [
			{"S": "CAP theorem"},
			{"S": "Leader-based replication"},
			{"S": "Eventual consistency"},
			{"S": "Quorum read/write"},
			{"S": "Failure recovery"}
		]
	},
	"generated_at": {"S": "2026-05-28T10:05:00Z"}
}
ITEM
}

resource "aws_dynamodb_table_item" "demo_question_history" {
	table_name = aws_dynamodb_table.studybot_documents.name
	hash_key   = "PK"
	range_key  = "SK"

	item = <<ITEM
{
	"PK": {"S": "USER#demo"},
	"SK": {"S": "QUESTION#2026-05-28T10:35:00Z"},
	"doc_id": {"S": "doc_001"},
	"question": {"S": "What is CAP theorem?"},
	"answer": {"S": "CAP theorem says..."},
	"citations": {
		"L": [
			{
				"M": {
					"document": {"S": "Distributed Systems Lecture.pdf"},
					"slide": {"N": "12"},
					"chunk_id": {"S": "chunk_034"}
				}
			}
		]
	},
	"topic": {"S": "CAP theorem"},
	"created_at": {"S": "2026-05-28T10:35:00Z"}
}
ITEM
}

resource "aws_dynamodb_table_item" "demo_quiz" {
	table_name = aws_dynamodb_table.studybot_documents.name
	hash_key   = "PK"
	range_key  = "SK"

	item = <<ITEM
{
	"PK": {"S": "USER#demo"},
	"SK": {"S": "DOC#doc_001#QUIZ"},
	"doc_id": {"S": "doc_001"},
	"questions": {
		"L": [
			{
				"M": {
					"question": {"S": "What does CAP stand for?"},
					"options": {"L": [{"S": "A"}, {"S": "B"}, {"S": "C"}, {"S": "D"}]},
					"answer": {"S": "B"},
					"explanation": {"S": "CAP means Consistency, Availability, Partition tolerance."}
				}
			}
		]
	},
	"generated_at": {"S": "2026-05-28T10:20:00Z"}
}
ITEM
}
