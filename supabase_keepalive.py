#!/usr/bin/env python3
"""
Supabase keepalive script - prevents free-tier projects from being paused due to inactivity.
Runs three times a week to maintain activity on the Supabase project.
"""

import os
import logging
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# Load environment variables
load_dotenv()

# Setup logging
log_dir = Path.home() / ".local/share/job-logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "supabase-keepalive.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("supabase_keepalive")

def send_keepalive():
    """Send a keepalive ping to Supabase to prevent project pause."""
    try:
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_ANON_KEY")

        if not supabase_url or not supabase_key:
            logger.error("Missing SUPABASE_URL or SUPABASE_ANON_KEY environment variables")
            return False

        logger.info("Connecting to Supabase...")
        supabase: Client = create_client(supabase_url, supabase_key)

        # Simple query to any table - just to trigger activity
        # This counts records in the whatsapp_sessions table
        logger.info("Sending keepalive ping to Supabase...")
        response = supabase.table("whatsapp_sessions").select("id", count="exact").limit(1).execute()

        if response:
            logger.info(f"✓ Keepalive successful - Supabase project is active")
            return True
        else:
            logger.warning(f"Keepalive returned empty response")
            return False

    except Exception as e:
        logger.error(f"✗ Keepalive failed: {str(e)}")
        return False

if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Starting Supabase keepalive at {timestamp}")

    success = send_keepalive()

    if success:
        logger.info("Keepalive completed successfully")
        exit(0)
    else:
        logger.error("Keepalive failed")
        exit(1)
