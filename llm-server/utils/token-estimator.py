import requests

def count_tokens(prompt: str, server_url: str = "http://localhost:8080") -> int:
    response = requests.post(
        f"{server_url}/tokenize",
        json={"content": prompt}
    )
    response.raise_for_status()
    return len(response.json()["tokens"])

if __name__ == "__main__":
    prompt = """You are analyzing error log messages from a backend service.
Existing categories: ["no_health_trends_data", "bad_request_payload_validation", "easy_bot_trigger_error", "failed_pdf_merge", "marketing_event_response", "order_edit_failure", "patient_details_fetch_error", "promotion_code_application", "cart_service_operations", "order_creation_response", "payment_status_update", "failed_to_generate_merged_report", "easy_bot_webhook_error", "customer_gateway_request_error", "order_details_response", "clear_cart_response", "phlebo_availability_error", "order_cancellation_success", "order_reschedule_success", "internal_server_error"]

New messages to categorize (first 20 words each):
- 2026-03-31 10:28:10.101 INFO 1 --- [ task-14684] c.p.bloom.service.PaymentStatusService : For orderId 6643237 Response received from tc PaymentStatusUpdateResponse(status=true, error=null, data=VL32C11E, respId=RES00001,

Group these into error categories. For each category:
- Use a snake_case label
- Pick a short distinctive phrase from the messages to match it (for use in Elasticsearch match_phrase)
- Do NOT reuse existing category labels unless the message clearly belongs there

Return ONLY valid JSON in this exact format, no explanation:
{
  "category_label": ["matching phrase"],
  "another_category": ["its matching phrase"]
}
"""
    print(f"Token count: {count_tokens(prompt)}")
