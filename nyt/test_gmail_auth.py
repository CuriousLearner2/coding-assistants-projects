from utils import get_gmail_service

try:
    service = get_gmail_service()
    results = service.users().messages().list(userId='me', maxResults=1).execute()
    print("SUCCESS: Gmail service is working.")
    print(f"Sample result keys: {results.keys()}")
except Exception as e:
    print(f"FAILURE: {e}")
